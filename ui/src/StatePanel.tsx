import { outcomeOf } from "./sessions";
import type { SessionInfo, Snapshot } from "./types";

const LABELS: Record<Snapshot["intelligibility"]["label"], string> = {
  ultra_strong: "Ultra-Strong",
  strong: "Strong",
  failed: "Not intelligible",
};

interface Props {
  snap: Snapshot | null;
  session: SessionInfo | undefined;
  termSeq: number | null;
}

const verdict = (correct: boolean | null) =>
  correct === null ? "Unavailable" : correct ? "correct" : "wrong";

/**
 * Board state at the cursor, rebuilt by the server from the log. Before TERM it is in progress
 * whatever the session ended in; how the whole session ended is shown apart from it.
 */
export function StatePanel({ snap, session, termSeq }: Props) {
  const final = session && (
    <>
      <h3>Whole session</h3>
      <dl>
        <dt>Ended</dt>
        <dd>{outcomeOf(session)}</dd>
        <dt>Answer</dt>
        <dd className={`verdict-line ${session.correct === null ? "" : session.correct ? "ok" : "bad"}`}>
          {verdict(session.correct)}
        </dd>
      </dl>
    </>
  );
  if (!snap) {
    return (
      <section className="state">
        <p className="muted">Loading the board state…</p>
        {final}
      </section>
    );
  }
  const t = snap.tokens;
  const inProgress = termSeq === null || snap.seq < termSeq;
  return (
    <section className="state">
      <h3>Board at seq {snap.seq}</h3>
      <table>
        <thead>
          <tr><th>Agent</th><th>Current prediction</th></tr>
        </thead>
        <tbody>
          {snap.agents.map((a) => (
            <tr key={a}><td>{a}</td><td>{snap.predictions[a]}</td></tr>
          ))}
        </tbody>
      </table>
      <dl>
        <dt>Status</dt>
        <dd>{inProgress ? "in progress" : `stopped on ${snap.stop_reason}`}</dd>
        <dt>Intelligibility</dt>
        <dd className={`intel ${snap.intelligibility.label}`}>
          {LABELS[snap.intelligibility.label]} ({snap.intelligibility.revises} REVISE)
        </dd>
        <dt>Tokens on the board</dt>
        <dd>
          {t.total.toLocaleString()} total
          {t.rollback_in + t.rollback_out > 0 &&
            ` · ${(t.rollback_in + t.rollback_out).toLocaleString()} in replays`}
        </dd>
      </dl>
      {snap.intelligibility.pairs.length > 0 && (
        <table className="pairs">
          <thead>
            <tr><th>Sender → receiver</th><th>Tags sent</th><th>One-way</th></tr>
          </thead>
          <tbody>
            {snap.intelligibility.pairs.map((p) => (
              <tr key={`${p.sender}-${p.receiver}`}>
                <td>{p.sender} → {p.receiver}</td>
                <td>{p.tags.join(", ")}</td>
                <td>{p.one_way ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {final}
    </section>
  );
}
