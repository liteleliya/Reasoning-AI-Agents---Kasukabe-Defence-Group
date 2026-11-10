import type { ResultsStatus } from "./api";
import type { RunSummary } from "./types";

interface Props {
  summary: RunSummary | null;
  status: ResultsStatus;
  error: string | null;
  onOpen: (sessionId: string) => void;
}

const KIND_TEXT = {
  historical: "Historical pilot",
  controlled: "Controlled fixture",
  model: "Model evaluation",
};
const grouped = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

const Unavailable = () => <span className="unavailable">Unavailable</span>;
const count = (n: number | null) => (n === null ? <Unavailable /> : n);

/**
 * Run-level figures from the server. The UI only lays them out: which trials count, and whether
 * an answer is correct, were decided in Python. A figure the export did not record is shown as
 * unavailable, never as zero.
 */
export function ResultsView({ summary, status, error, onOpen }: Props) {
  if (status === "loading") return <p className="empty">Loading results…</p>;
  if (status === "unavailable") {
    return (
      <p className="empty">
        No results for this run. Start the server with --metrics &lt;metrics.csv&gt; to see them.
      </p>
    );
  }
  if (status === "error" || !summary) {
    return <p className="empty error" role="alert">Could not load the results: {error}</p>;
  }

  const { run, totals, conditions, recovery, examples } = summary;
  const known = recovery.filter((s) => s.stage !== "recorded" && s.count !== null);
  const peak = Math.max(1, ...recovery.map((s) => s.count ?? 0));
  const trace = (stage: string) =>
    examples.find((e) => (stage === "recovered" ? e.kind === "recovery" : false));

  return (
    <div className="results">
      <header className="results-head">
        <h2>Results</h2>
        <span className={`kind ${run.kind ?? "unstated"}`}>
          {run.kind ? KIND_TEXT[run.kind] : "Source not stated"}
        </span>
        <p className="muted">
          {run.label && <strong>{run.label}</strong>}
          {run.model && ` · ${run.model}`}
          {` · ${run.trials} trials · ${run.cases} cases · ${run.conditions} conditions`}
        </p>
      </header>

      <p className="headline">
        <strong>{`${totals.consensus} of ${totals.trials} trials reached consensus`}</strong>
        {`, ${totals.correct_consensus} of those were correct, and ${totals.recorded_replays} replays logged.`}
      </p>

      <section>
        <h3>Conditions</h3>
        <div className="table-wrap">
          <table className="conditions">
            <thead>
              <tr>
                <th scope="col">Condition</th>
                <th scope="col">Trials</th>
                <th scope="col">Consensus</th>
                <th scope="col">Correct</th>
                <th scope="col">Wrong</th>
                <th scope="col">No verdict</th>
                <th scope="col">Eligible</th>
                <th scope="col">Median tokens per trial (all model calls)</th>
              </tr>
            </thead>
            <tbody>
              {conditions.map((c) => (
                <tr key={c.condition}>
                  <th scope="row">
                    {c.enabled_agents !== null && c.n_agents !== null
                      ? `${c.enabled_agents} of ${c.n_agents} enabled`
                      : c.condition}
                    <span className="muted"> {c.condition}</span>
                  </th>
                  <td>{c.trials}</td>
                  <td>{c.consensus}</td>
                  <td>{c.correct_consensus}</td>
                  <td>{c.wrong_consensus}</td>
                  <td>{c.ungraded_consensus}</td>
                  <td>{count(c.eligible)}</td>
                  <td>{c.median_tokens === null ? <Unavailable /> : grouped.format(c.median_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted note">
          Correct and wrong count consensus trials only. Agreement says nothing about whether the answer is right.
        </p>
      </section>

      <section>
        <h3>Recovery outcomes</h3>
        <ul className="stages">
          {recovery.map((s) => {
            const link = trace(s.stage);
            return (
              <li key={s.stage}>
                <span className="stage-label">{s.label}</span>
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${((s.count ?? 0) / peak) * 100}%` }} />
                </span>
                <span className="stage-count">{count(s.count)}</span>
                {link && (
                  <button className="link" onClick={() => onOpen(link.session_id)}>Open a trace</button>
                )}
              </li>
            );
          })}
        </ul>
        {known.length === 0 && (
          <p className="muted note">
            This run did not export the recovery stages, so only the replays logged on the board are known.
          </p>
        )}
      </section>

      <section>
        <h3>Examples</h3>
        {examples.length === 0 && <p className="muted">No examples to show.</p>}
        <ul className="examples">
          {examples.map((e) => (
            <li key={`${e.kind}-${e.session_id}`} className="example">
              <button onClick={() => onOpen(e.session_id)}>
                <strong>{e.title}</strong>
                <span className="muted">{`${e.label} · ${e.condition} · ${e.outcome}`}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
