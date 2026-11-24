import { useEffect, useState } from "react";
import { accept, isCurrentSnapshot, nextSeq, type Buffered } from "./stream";
import { briefUrl, hasBrief } from "./taskBrief";
import type { BriefStatus } from "./CaseBrief";
import type { CaseBrief, EventRecord, RunSummary, SessionInfo, Snapshot, StudyReport } from "./types";

export async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json() as Promise<T>;
}

/** Ids travel as a query value because real ones contain "/", "|" and "#". */
export function eventsUrl(sessionId: string): string {
  return `/api/events?${new URLSearchParams({ session_id: sessionId })}`;
}

export function snapshotUrl(sessionId: string, seq: number): string {
  return `/api/snapshot?${new URLSearchParams({ session_id: sessionId, at: String(seq) })}`;
}

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** Session list, refreshed every `intervalMs`, with whether the first load finished or failed. */
export function useSessions(intervalMs = 2000): {
  sessions: SessionInfo[];
  loaded: boolean;
  error: string | null;
} {
  const [state, setState] = useState<{ sessions: SessionInfo[]; loaded: boolean; error: string | null }>({
    sessions: [], loaded: false, error: null,
  });
  useEffect(() => {
    const ctl = new AbortController();
    const load = () =>
      getJSON<SessionInfo[]>("/api/sessions", ctl.signal)
        .then((sessions) => setState({ sessions, loaded: true, error: null }))
        .catch((err) => {
          if (!ctl.signal.aborted) setState((prev) => ({ ...prev, loaded: true, error: message(err) }));
        });
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      ctl.abort();
      clearInterval(id);
    };
  }, [intervalMs]);
  return state;
}

export type StreamStatus =
  | "idle" | "loading" | "connecting" | "live" | "reconnecting" | "archived" | "error";

interface StreamState {
  id: string | null; // the session these events belong to
  events: EventRecord[];
  status: StreamStatus;
  error: string | null;
}

/**
 * The events of one session. A recorded session is read once over REST. A running one is read
 * over REST and then followed on the WebSocket, resuming from one past the last contiguous event
 * after a drop and backfilling any gap over REST before moving on. Switching sessions cancels the
 * old fetches and socket, and nothing from the old session is ever returned for the new one.
 */
export function useSessionEvents(sessionId: string | null): {
  events: EventRecord[];
  status: StreamStatus;
  error: string | null;
} {
  const [state, setState] = useState<StreamState>({ id: null, events: [], status: "idle", error: null });

  useEffect(() => {
    if (!sessionId) {
      setState({ id: null, events: [], status: "idle", error: null });
      return;
    }
    setState({ id: sessionId, events: [], status: "loading", error: null });
    const ctl = new AbortController();
    let buf: Buffered = { events: [], pending: [] };
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let finished = false;
    let backfilling = false;

    const patch = (p: Partial<StreamState>) => {
      if (!stopped) setState((prev) => ({ ...prev, id: sessionId, ...p }));
    };
    const terminated = () => buf.events.some((e) => e.tag === "TERM");
    const publish = (incoming: EventRecord[]) => {
      const { gap, ...next } = accept(buf, incoming);
      buf = next;
      patch({ events: next.events });
      return gap;
    };
    const finish = () => {
      finished = true;
      clearTimeout(retry);
      socket?.close();
      patch({ status: "archived" });
    };
    const backfill = async () => {
      if (backfilling) return;
      backfilling = true;
      try {
        publish(await getJSON<EventRecord[]>(eventsUrl(sessionId), ctl.signal));
      } catch (err) {
        if (!ctl.signal.aborted) patch({ status: "error", error: message(err) });
      } finally {
        backfilling = false;
      }
    };
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const params = new URLSearchParams({ session_id: sessionId, from_seq: String(nextSeq(buf)) });
      const ws = new WebSocket(`${proto}://${location.host}/ws?${params}`);
      socket = ws;
      ws.onmessage = (msg) => {
        const frame = JSON.parse(msg.data);
        if (frame.type === "synced") return patch({ status: "live" });
        if (frame.type !== "event") return;
        const gap = publish([frame.event as EventRecord]);
        if (terminated()) finish();
        else if (gap !== null) void backfill();
      };
      ws.onclose = () => {
        if (stopped || finished) return;
        patch({ status: "reconnecting" });
        retry = setTimeout(connect, 1000);
      };
    };

    (async () => {
      try {
        publish(await getJSON<EventRecord[]>(eventsUrl(sessionId), ctl.signal));
      } catch (err) {
        if (ctl.signal.aborted) return;
        const unknown = /^404/.test(message(err));
        patch({ status: "error", error: unknown ? "Unknown session" : message(err) });
        return;
      }
      if (terminated()) return finish();
      patch({ status: "connecting" });
      connect();
    })();

    return () => {
      stopped = true;
      ctl.abort();
      clearTimeout(retry);
      socket?.close();
    };
  }, [sessionId]);

  if (state.id !== sessionId) {
    return { events: [], status: sessionId ? "loading" : "idle", error: null };
  }
  return { events: state.events, status: state.status, error: state.error };
}

/** Board state rebuilt by the server from the log at `seq` (C4); never one for another request. */
export function useSnapshot(sessionId: string | null, seq: number | null): Snapshot | null {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  useEffect(() => {
    if (!sessionId || seq === null || seq < 0) return;
    const ctl = new AbortController();
    getJSON<Snapshot>(snapshotUrl(sessionId, seq), ctl.signal)
      .then((s) => {
        if (isCurrentSnapshot(s, sessionId, seq)) setSnap(s);
      })
      .catch((err) => {
        if (!ctl.signal.aborted) console.error(`snapshot ${sessionId} @${seq}: ${message(err)}`);
      });
    return () => ctl.abort();
  }, [sessionId, seq]);
  return sessionId && snap?.session_id === sessionId ? snap : null;
}

export type ResultsStatus = "idle" | "loading" | "ready" | "unavailable" | "error";
export type StudyStatus = ResultsStatus;

/** The run summary from the server; read only when the Results view is open. */
export function useResults(active: boolean): {
  summary: RunSummary | null;
  status: ResultsStatus;
  error: string | null;
} {
  const [state, setState] = useState<{ summary: RunSummary | null; status: ResultsStatus; error: string | null }>({
    summary: null, status: "idle", error: null,
  });
  useEffect(() => {
    if (!active) return;
    const ctl = new AbortController();
    setState((prev) => ({ ...prev, status: "loading" }));
    getJSON<RunSummary>("/api/results", ctl.signal)
      .then((summary) => setState({ summary, status: "ready", error: null }))
      .catch((err) => {
        if (ctl.signal.aborted) return;
        const none = /^404/.test(message(err));
        setState({ summary: null, status: none ? "unavailable" : "error", error: message(err) });
      });
    return () => ctl.abort();
  }, [active]);
  return state;
}

/** A paired-study report prepared by the server from frozen local outputs, never recomputed in React. */
export function useStudy(active: boolean): {
  report: StudyReport | null;
  status: StudyStatus;
  error: string | null;
} {
  const [state, setState] = useState<{ report: StudyReport | null; status: StudyStatus; error: string | null }>({
    report: null, status: "idle", error: null,
  });
  useEffect(() => {
    if (!active) return;
    const ctl = new AbortController();
    setState((prev) => ({ ...prev, status: "loading" }));
    getJSON<StudyReport>("/api/study", ctl.signal)
      .then((report) => setState({ report, status: "ready", error: null }))
      .catch((err) => {
        if (ctl.signal.aborted) return;
        const unavailable = /^404/.test(message(err));
        setState({ report: null, status: unavailable ? "unavailable" : "error", error: message(err) });
      });
    return () => ctl.abort();
  }, [active]);
  return state;
}

/** The public record of the open session's case, fetched only for authored cases. */
export function useCaseBrief(caseId: string | null): { brief: CaseBrief | null; status: BriefStatus } {
  const [state, setState] = useState<{ brief: CaseBrief | null; status: BriefStatus }>({
    brief: null, status: "idle",
  });
  useEffect(() => {
    if (!caseId) return setState({ brief: null, status: "idle" });
    if (!hasBrief(caseId)) return setState({ brief: null, status: "unavailable" });
    const ctl = new AbortController();
    setState({ brief: null, status: "loading" }); // never show the previous case's task
    getJSON<CaseBrief>(briefUrl(caseId), ctl.signal)
      .then((brief) => setState({ brief, status: "ready" }))
      .catch((err) => {
        if (ctl.signal.aborted) return;
        setState({ brief: null, status: /^404/.test(message(err)) ? "unavailable" : "error" });
      });
    return () => ctl.abort();
  }, [caseId]);
  return state;
}
