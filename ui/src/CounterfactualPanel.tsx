import { useMemo } from "react";
import { rollbacks } from "./layout";
import { TAG_COLOURS } from "./tags";
import type { EventRecord } from "./types";

function Step({ e, faded }: { e: EventRecord; faded?: boolean }) {
  return (
    <li className={faded ? "step faded" : "step"}>
      <span className="chip" style={{ background: TAG_COLOURS[e.tag ?? "INIT"] }}>{e.tag}</span>
      <span className="who">{e.author}</span>
      <span className="what">{e.prediction}</span>
      <span className="why">{e.explanation}</span>
    </li>
  );
}

/** Split panel (C3): for each rollback, what really happened next to the counterfactual replay. */
export function CounterfactualPanel({ events }: { events: EventRecord[] }) {
  const groups = useMemo(() => rollbacks(events), [events]);
  if (!groups.length) return null;
  return (
    <section className="cf">
      <h3>Counterfactual replays</h3>
      {groups.map((rb) => (
        <article key={rb.start.seq} className="cf-card">
          <header>
            <b>{rb.start.author}</b> replays seq {rb.start.reply_to}
            {rb.start.explanation && <span className="muted"> · “{rb.start.explanation}”</span>}
            <span className="cf-meta">
              {rb.end ? (
                rb.creditDelta !== null && (
                  <span className={rb.creditDelta < 0 ? "delta good" : "delta"}>
                    credit Δ {rb.creditDelta > 0 ? "+" : ""}{rb.creditDelta}
                  </span>
                )
              ) : (
                <span className="delta">replaying…</span>
              )}
              <span className="muted">{rb.tokens.toLocaleString()} tokens</span>
            </span>
          </header>
          <div className="cf-split">
            <div>
              <h4>What happened</h4>
              <ol>{rb.real.map((e) => <Step key={e.seq} e={e} faded />)}</ol>
            </div>
            <div>
              <h4>What if (replay, isolated from the board)</h4>
              <ol>{rb.steps.map((e) => <Step key={e.seq} e={e} />)}</ol>
              {rb.end?.explanation && <p className="muted">{rb.end.explanation}</p>}
            </div>
          </div>
        </article>
      ))}
    </section>
  );
}
