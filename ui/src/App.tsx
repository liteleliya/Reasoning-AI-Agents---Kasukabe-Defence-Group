import { useEffect, useState } from "react";
import { useEventStream, useSessions } from "./api";
import { Graph } from "./Graph";
import { Legend } from "./Legend";

export function App() {
  const sessions = useSessions();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { events, connected } = useEventStream(sessionId);

  useEffect(() => {
    if (!sessionId && sessions.length) setSessionId(sessions[0].session_id);
  }, [sessions, sessionId]);

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
                onClick={() => setSessionId(s.session_id)}
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
        <Graph events={events} />
      </main>
    </div>
  );
}
