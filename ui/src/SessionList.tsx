import { useMemo, useState } from "react";
import { conditionLabel, conditionOptions, filterSessions, outcomeOf } from "./sessions";
import type { SessionInfo } from "./types";

interface Props {
  sessions: SessionInfo[];
  loaded: boolean;
  error: string | null;
  selected: string | null;
  onSelect: (sessionId: string) => void;
}

const OUTCOMES = ["live", "consensus", "impasse", "cap"];

/** Sessions by case and condition, with search and outcome and condition filters. */
export function SessionList({ sessions, loaded, error, selected, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState("");
  const [condition, setCondition] = useState("");
  const shown = useMemo(
    () => filterSessions(sessions, { query, outcome, condition }),
    [sessions, query, outcome, condition],
  );
  const conditions = useMemo(() => conditionOptions(sessions), [sessions]);

  return (
    <>
      <input
        type="search"
        className="search"
        placeholder="Search case, condition or id"
        aria-label="Search sessions"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="filters">
        <select aria-label="Filter by outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">Any outcome</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        {conditions.length > 0 && (
          <select aria-label="Filter by condition" value={condition} onChange={(e) => setCondition(e.target.value)}>
            <option value="">Any condition</option>
            {conditions.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        )}
      </div>
      <p className="muted count" aria-live="polite">
        {loaded ? `${shown.length} of ${sessions.length} sessions` : "Loading sessions…"}
      </p>
      {error && <p className="notice error" role="alert">Session list unavailable: {error}</p>}
      <ul className="sessions">
        {shown.map((s) => {
          const result = outcomeOf(s);
          return (
            <li key={s.session_id}>
              <button
                className={s.session_id === selected ? "active" : ""}
                aria-current={s.session_id === selected ? "true" : undefined}
                title={s.session_id}
                onClick={() => onSelect(s.session_id)}
              >
                <span className="row-main">
                  <strong>{s.label}</strong>
                  <span className="muted">
                    {conditionLabel(s)}
                    {s.seed !== null && ` · seed ${s.seed}`}
                  </span>
                </span>
                <span className="row-side">
                  <span className={`badge ${result}`}>{result}</span>
                  {s.correct !== null && (
                    <span className={s.correct ? "verdict ok" : "verdict bad"}
                      aria-label={s.correct ? "correct answer" : "wrong answer"}>
                      {s.correct ? "correct" : "wrong"}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
        {loaded && !sessions.length && (
          <li className="muted empty-row">No sessions. Start the server with --db or --demo.</li>
        )}
        {loaded && sessions.length > 0 && !shown.length && (
          <li className="muted empty-row">No session matches these filters.</li>
        )}
      </ul>
    </>
  );
}
