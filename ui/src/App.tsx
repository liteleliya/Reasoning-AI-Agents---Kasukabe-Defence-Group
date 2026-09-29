import { useCallback, useEffect, useMemo, useState } from "react";
import { useEventStream, useSessions, useSnapshot } from "./api";
import { CounterfactualPanel } from "./CounterfactualPanel";
import { Graph } from "./Graph";
import { upTo } from "./layout";
import { Legend } from "./Legend";
import { Scrubber } from "./Scrubber";
import { StatePanel } from "./StatePanel";

export function App() {
  const sessions = useSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { events, connected } = useEventStream(sessionId);
  const [cursor, setCursor] = useState(0);
  const [live, setLive] = useState(true);

  useEffect(() => {
    if (!sessionId && sessions.length) setSessionId(sessions[0].session_id);
  }, [sessions, sessionId]);

  const last = events.length ? events[events.length - 1].seq : 0;
  useEffect(() => {
    if (live) setCursor(last);
  }, [live, last]);

  const selectSession = (id: string) => {
    setSessionId(id);
    setLive(true);
  };
  const scrub = useCallback((seq: number, follow: boolean) => {
    setCursor(seq);
    setLive(follow);
  }, []);

  const visible = useMemo(() => upTo(events, cursor), [events, cursor]);
  const snap = useSnapshot(sessionId, events.length ? cursor : null);
  const term = events.find((e) => e.tag === "TERM");

  return (
    <div className="app">
      <aside>
        <h1>Blackboard</h1>
        <ul className="sessions">
          {sessions.map((s) => (
            <li key={s.session_id}>
              <button
                className={s.session_id === sessionId ? "active" : ""}
                onClick={() => selectSession(s.session_id)}
              >
                <span>{s.session_id}</span>
                <span className={`badge ${s.stop_reason ?? "live"}`}>
                  {s.stop_reason ?? "live"}
                </span>
              </button>
            </li>
          ))}
          {!sessions.length && <li className="muted">No sessions. Start the server with --demo.</li>}
        </ul>
      </aside>
      <main>
        <header>
          <h2>{sessionId ?? "—"}</h2>
          <span className={connected ? "dot on" : "dot"} title={connected ? "live" : "offline"} />
          <span className="muted">
            {events.length} events{term ? ` · stopped on ${term.explanation}` : ""}
          </span>
          <Legend />
        </header>
        <Scrubber events={events} cursor={cursor} live={live} onChange={scrub} />
        <div className="body">
          <div className="left">
            <Graph events={visible} highlightSeq={cursor} onSelect={(e) => scrub(e.seq, false)} />
            <CounterfactualPanel events={visible} />
          </div>
          <StatePanel snap={snap} />
        </div>
      </main>
    </div>
  );
}
