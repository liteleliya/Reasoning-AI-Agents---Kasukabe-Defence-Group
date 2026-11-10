import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCaseBrief, useResults, useSessionEvents, useSessions, useSnapshot } from "./api";
import { CaseBrief } from "./CaseBrief";
import { CounterfactualPanel } from "./CounterfactualPanel";
import { EventInspector } from "./EventInspector";
import { EventList } from "./EventList";
import { Graph } from "./Graph";
import { firstChallenge, terminationSeq } from "./inspector";
import { rosterOf, upTo } from "./layout";
import { ResultsView } from "./ResultsView";
import { Scrubber } from "./Scrubber";
import { SessionHeader } from "./SessionHeader";
import { SessionList } from "./SessionList";
import { siblings } from "./sessions";
import { StatePanel } from "./StatePanel";
import { buildSearch, parseSearch, type View } from "./urlState";

export function App() {
  const { sessions, loaded, error: listError } = useSessions();
  const [initial] = useState(() => parseSearch(location.search));
  // the one place that owns which session is open, where the cursor is and whether it follows
  const [view, setView] = useState<View>(initial.view);
  const [sessionId, setSessionId] = useState<string | null>(initial.session);
  const [cursor, setCursor] = useState(initial.seq ?? 0);
  const [follow, setFollow] = useState(initial.seq === null);
  const wantedSeq = useRef(initial.seq); // the address-bar position, applied once the events load

  const { events, status, error } = useSessionEvents(sessionId);
  const results = useResults(view === "results");

  useEffect(() => {
    if (!sessionId && sessions.length) setSessionId(sessions[0].session_id);
  }, [sessions, sessionId]);

  useEffect(() => {
    if (!events.length) return;
    const last = events[events.length - 1].seq;
    if (wantedSeq.current !== null) {
      setCursor(Math.min(wantedSeq.current, last));
      setFollow(false);
      wantedSeq.current = null;
    } else if (follow) {
      setCursor(last); // paused cursors are left where they are when new events arrive
    }
  }, [events, follow]);

  useEffect(() => {
    const search = buildSearch(sessionId, follow ? null : cursor, view);
    if (search !== location.search) history.replaceState(null, "", `${location.pathname}${search}`);
  }, [sessionId, cursor, follow, view]);

  const selectSession = useCallback((id: string) => {
    wantedSeq.current = null;
    setSessionId(id);
    setCursor(0);
    setFollow(true);
  }, []);
  const openFromResults = useCallback(
    (id: string) => {
      selectSession(id);
      setView("explore");
    },
    [selectSession],
  );
  const scrub = useCallback((seq: number, following: boolean) => {
    setCursor(seq);
    setFollow(following);
  }, []);

  const visible = useMemo(() => upTo(events, cursor), [events, cursor]);
  const snap = useSnapshot(sessionId, events.length ? cursor : null);
  const term = events.find((e) => e.tag === "TERM");
  const termSeq = useMemo(() => terminationSeq(events), [events]);
  const firstChallengeSeq = useMemo(() => firstChallenge(events), [events]);
  const roster = useMemo(() => rosterOf(events), [events]);
  const pick = useCallback((seq: number) => scrub(seq, false), [scrub]); // selecting pauses
  const info = sessions.find((s) => s.session_id === sessionId);
  const caseBrief = useCaseBrief(view === "explore" ? (info?.case_id ?? null) : null);

  let body;
  if (!sessionId) {
    body = <p className="empty">{loaded ? "No session selected." : "Loading sessions…"}</p>;
  } else if (status === "error") {
    body = <p className="empty error" role="alert">Could not open this session: {error}</p>;
  } else if (!events.length) {
    body = <p className="empty">Loading session…</p>;
  } else {
    body = (
      <>
        <Scrubber
          events={events}
          cursor={cursor}
          live={follow}
          firstChallenge={firstChallengeSeq}
          termSeq={termSeq}
          onChange={scrub}
        />
        <div className="body">
          <div className="left">
            <Graph events={events} roster={roster} cursor={cursor} onSelect={(e) => pick(e.seq)} />
            <CounterfactualPanel events={visible} cursor={cursor} onSelectSeq={pick} />
          </div>
          <div className="side">
            <EventInspector events={events} cursor={cursor} onSelectSeq={pick} />
            <StatePanel snap={snap} session={info} termSeq={termSeq} />
            <EventList events={events} cursor={cursor} onSelectSeq={pick} />
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="app">
      <aside>
        <h1>Blackboard</h1>
        <nav className="views" role="tablist" aria-label="View">
          {(["explore", "results"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              className={view === v ? "tab active" : "tab"}
              onClick={() => setView(v)}
            >
              {v === "explore" ? "Explore" : "Results"}
            </button>
          ))}
        </nav>
        <SessionList
          sessions={sessions}
          loaded={loaded}
          error={listError}
          selected={sessionId}
          onSelect={selectSession}
        />
      </aside>
      <main>
        {view === "results" && (
          <ResultsView
            summary={results.summary}
            status={results.status}
            error={results.error}
            onOpen={openFromResults}
          />
        )}
        {view === "explore" && sessionId && (
          <SessionHeader
            sessionId={sessionId}
            info={info}
            tabs={info ? siblings(sessions, info) : []}
            status={status}
            events={events.length}
            stopDetail={term ? term.explanation : null}
            onSelect={selectSession}
          />
        )}
        {view === "explore" && sessionId && (
          <CaseBrief caseId={info?.case_id ?? null} brief={caseBrief.brief} status={caseBrief.status} />
        )}
        {view === "explore" && body}
      </main>
    </div>
  );
}
