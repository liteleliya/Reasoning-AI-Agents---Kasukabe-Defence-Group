import type { Snapshot } from "./types";

const LABELS: Record<Snapshot["intelligibility"]["label"], string> = {
  ultra_strong: "Ultra-Strong",
  strong: "Strong",
  failed: "Not intelligible",
};

/** Board state at the scrubber position, rebuilt by the server from the log. */
export function StatePanel({ snap }: { snap: Snapshot | null }) {
  if (!snap) return <section className="state muted">Pick a session.</section>;
  const t = snap.tokens;
  return (
    <section className="state">
      <h3>State at seq {snap.seq}</h3>
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
        <dd>{snap.terminated ? `stopped on ${snap.stop_reason}` : "running"}</dd>
        <dt>Intelligibility</dt>
        <dd className={`intel ${snap.intelligibility.label}`}>
          {LABELS[snap.intelligibility.label]} ({snap.intelligibility.revises} REVISE)
        </dd>
        <dt>Tokens</dt>
        <dd>
          {t.total.toLocaleString()} total
          {t.rollback_in + t.rollback_out > 0 &&
            ` · ${(t.rollback_in + t.rollback_out).toLocaleString()} in rollbacks`}
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
    </section>
  );
}
