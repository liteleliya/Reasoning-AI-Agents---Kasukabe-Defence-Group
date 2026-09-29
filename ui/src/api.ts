import { useEffect, useState } from "react";
import type { EventRecord, SessionInfo, Snapshot } from "./types";

export async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json() as Promise<T>;
}

/** Session list, refreshed every `intervalMs`. */
export function useSessions(intervalMs = 2000): SessionInfo[] {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      getJSON<SessionInfo[]>("/api/sessions")
        .then((s) => alive && setSessions(s))
        .catch(() => undefined);
    load();
    const id = setInterval(load, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);
  return sessions;
}

/** All events of one session: the stored backlog, then live events over the WebSocket.
 * Reconnects with from_seq after a drop, so nothing is lost or duplicated. */
export function useEventStream(sessionId: string | null): {
  events: EventRecord[];
  connected: boolean;
} {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setEvents([]);
    if (!sessionId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let next = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const params = new URLSearchParams({ session_id: sessionId, from_seq: String(next) });
      ws = new WebSocket(`${proto}://${location.host}/ws?${params}`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (msg) => {
        const frame = JSON.parse(msg.data);
        if (frame.type !== "event") return;
        const e = frame.event as EventRecord;
        if (e.seq < next) return;
        next = e.seq + 1;
        setEvents((prev) => [...prev, e]);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [sessionId]);

  return { events, connected };
}

/** Board state rebuilt by the server from the log at `seq` (C4). */
export function useSnapshot(sessionId: string | null, seq: number | null): Snapshot | null {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  useEffect(() => {
    if (!sessionId || seq === null || seq < 0) {
      setSnap(null);
      return;
    }
    let alive = true;
    getJSON<Snapshot>(`/api/sessions/${encodeURIComponent(sessionId)}/snapshot?at=${seq}`)
      .then((s) => alive && setSnap(s))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [sessionId, seq]);
  return snap;
}
