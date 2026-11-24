import { useMemo, useState } from "react";
import type { StudyArm, StudyReport } from "./types";

interface Props {
  report: StudyReport;
  onOpen: (sessionId: string) => void;
}

type Filter = "all" | "eligible" | "adopted" | "recovered";

const ARM_LABEL: Record<StudyArm, string> = {
  standard: "Ordinary continuation",
  forward: "Forward rethink",
  replay: "Counterfactual replay",
};

const COMPACT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const signed = (value: number | null) => (value === null ? "—" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)} pp`);

function Metric({ label, value, detail, tone = "plain" }: { label: string; value: string; detail: string; tone?: string }) {
  return (
    <article className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function ArmRows({ report }: { report: StudyReport }) {
  const peak = Math.max(1, ...report.outcomes.map((outcome) => outcome.correct_recovery));
  return (
    <section className="study-block arm-block">
      <div className="block-heading">
        <div>
          <p className="eyebrow">Matched comparison</p>
          <h3>What changed after the same stalled prefix?</h3>
        </div>
        <p>Every row below starts from an identical saved prefix. Correct recovery is kept distinct from agreement.</p>
      </div>
      <div className="arm-rows" role="table" aria-label="Paired arm outcomes">
        <div className="arm-row arm-head" role="row">
          <span role="columnheader">Arm</span><span role="columnheader">Correct recovery</span>
          <span role="columnheader">Consensus</span><span role="columnheader">Median full cost</span>
        </div>
        {report.outcomes.map((outcome) => (
          <div className={`arm-row arm-${outcome.arm}`} role="row" key={outcome.arm}>
            <div role="cell"><strong>{ARM_LABEL[outcome.arm]}</strong><small>{outcome.arm}</small></div>
            <div className="recovery-bar" role="cell">
              <span className="bar-track"><i style={{ width: `${(outcome.correct_recovery / peak) * 100}%` }} /></span>
              <b>{`${outcome.correct_recovery} / ${outcome.eligible}`}</b>
            </div>
            <span role="cell">{`${outcome.consensus} / ${outcome.trials}`}</span>
            <span role="cell">{outcome.median_cost === null ? "—" : COMPACT.format(outcome.median_cost)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Funnel({ report, onFilter }: { report: StudyReport; onFilter: (filter: Filter) => void }) {
  const peak = Math.max(1, ...report.funnel.map((stage) => stage.count));
  const filterFor = (stage: string): Filter => {
    if (stage === "eligible") return "eligible";
    if (stage === "adopted") return "adopted";
    if (stage === "correct_recovery") return "recovered";
    return "all";
  };
  return (
    <section className="study-block funnel-block">
      <div className="block-heading">
        <div><p className="eyebrow">Replay decision path</p><h3>Where the intervention was lost</h3></div>
        <p>Click a stage to inspect the corresponding case/seed units below.</p>
      </div>
      <ol className="research-funnel">
        {report.funnel.map((stage, index) => (
          <li key={stage.stage}>
            <button onClick={() => onFilter(filterFor(stage.stage))}>
              <span className="funnel-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="funnel-label">{stage.stage.replaceAll("_", " ")}</span>
              <span className="funnel-bar"><i style={{ width: `${(stage.count / peak) * 100}%` }} /></span>
              <strong>{stage.count}</strong>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Comparison({ report }: { report: StudyReport }) {
  const rows = Object.values(report.comparisons);
  return (
    <section className="study-block comparison-block">
      <div className="block-heading">
        <div><p className="eyebrow">Paired estimate</p><h3>Replay relative to each control</h3></div>
        <p>Positive values favour replay. Intervals resample cases, while retaining all of a case’s seeds.</p>
      </div>
      <div className="comparisons">
        {rows.map((comparison) => {
          const extra = comparison.differences.intervention_tokens?.mean;
          return (
            <article key={comparison.other} className="comparison-card">
              <p>{`Replay vs ${comparison.other}`}</p>
              <strong>{signed(comparison.rate_difference)}</strong>
              <span>{comparison.ci ? `${signed(comparison.ci[0])} to ${signed(comparison.ci[1])}` : "interval unavailable"}</span>
              <small>{`${comparison.wins} wins · ${comparison.losses} losses · ${comparison.ties} ties across ${comparison.pairs} eligible pairs`}</small>
              {extra !== null && extra !== undefined && <em>{`${extra >= 0 ? "+" : ""}${COMPACT.format(extra)} intervention tokens on average`}</em>}
              {comparison.small && <mark>Small eligible sample</mark>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function Verdict({ value }: { value: boolean | null }) {
  if (value === true) return <span className="case-verdict good">correct</span>;
  if (value === false) return <span className="case-verdict bad">incorrect</span>;
  return <span className="case-verdict unknown">ungraded</span>;
}

function CaseMatrix({ report, filter, onOpen }: { report: StudyReport; filter: Filter; onOpen: (id: string) => void }) {
  const units = useMemo(() => report.units.filter((unit) => {
    if (filter === "eligible") return unit.checkpoint === "opened";
    if (filter === "adopted") return unit.arms.replay?.recovery_outcome === "reply_accepted";
    if (filter === "recovered") {
      const replay = unit.arms.replay;
      return replay?.stop_reason === "consensus" && replay.correct === true;
    }
    return true;
  }), [report.units, filter]);
  return (
    <section className="study-block case-block">
      <div className="block-heading">
        <div><p className="eyebrow">Trace index</p><h3>Open the evidence behind any result</h3></div>
        <p>{`${units.length} of ${report.units.length} case × seed units shown`}</p>
      </div>
      <div className="matrix-wrap">
        <table className="case-matrix">
          <thead><tr><th>Case</th><th>Seed</th><th>Checkpoint</th>{(["standard", "forward", "replay"] as StudyArm[]).map((arm) => <th key={arm}>{arm}</th>)}</tr></thead>
          <tbody>
            {units.map((unit) => (
              <tr key={`${unit.case_id}|${unit.seed}`}>
                <th scope="row"><span>{unit.label}</span><small>{unit.domain}</small></th>
                <td>{unit.seed}</td>
                <td><span className={`checkpoint ${unit.checkpoint}`}>{unit.checkpoint === "opened" ? "opened" : "none"}</span></td>
                {(["standard", "forward", "replay"] as StudyArm[]).map((arm) => {
                  const result = unit.arms[arm];
                  return <td key={arm}>{result ? <button className="case-cell" onClick={() => onOpen(result.session_id)}><Verdict value={result.correct} /><small>{result.stop_reason}{result.recovery_outcome ? ` · ${result.recovery_outcome.replaceAll("_", " ")}` : ""}</small></button> : "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Integrity({ report }: { report: StudyReport }) {
  const { grading, authored_answers: answers, allowance } = report.integrity;
  const issues = [
    answers.unresolved > 0 ? `${answers.unresolved} of ${answers.total} authored final answers do not resolve to the public response schema.` : "All authored final answers resolve to the public response schema.",
    allowance.violations.length ? `${allowance.violations.length} arms exceeded the ${allowance.limit}-call post-checkpoint allowance in this archived run.` : allowance.limit !== null ? `Every recorded arm stayed within the ${allowance.limit}-call post-checkpoint allowance.` : "No call allowance was recorded.",
  ];
  return (
    <section className="study-block integrity-block">
      <div className="block-heading"><div><p className="eyebrow">Evidence quality</p><h3>What to claim, and what not to claim</h3></div></div>
      <div className="integrity-grid">
        <div><span>Verdict source</span><strong>{`${grading.rubric} rubric · ${grading.automatic} automatic · ${grading.missing} missing`}</strong></div>
        <ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
      </div>
    </section>
  );
}

/** A presentation-ready index over real, saved experiment outputs. */
export function StudyView({ report, onOpen }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const replay = report.outcomes.find((outcome) => outcome.arm === "replay");
  const checks = replay?.eligible ?? 0;
  return (
    <div className="study">
      <header className="study-hero">
        <div>
          <p className="eyebrow">Intelligible Blackboard · local paired experiment</p>
          <h2>Counterfactual recovery, inspected rather than asserted.</h2>
          <p>{report.note}</p>
        </div>
        <dl>
          <div><dt>Model</dt><dd>{report.provenance.model}</dd></div>
          <div><dt>Agents</dt><dd>{report.provenance.n_agents ?? "—"}</dd></div>
          <div><dt>Persona setup</dt><dd>{report.provenance.persona_set}</dd></div>
          <div><dt>Source</dt><dd>{report.provenance.analysis_source}</dd></div>
        </dl>
      </header>

      <section className="metric-grid" aria-label="Study headline metrics">
        <Metric label="Checkpoints opened" value={`${report.activity.checkpoints} / ${report.activity.prefixes}`} detail="unique shared case × seed prefixes" tone="blue" />
        <Metric label="Replay recovery" value={replay ? `${replay.correct_recovery} / ${checks}` : "—"} detail="eligible prefixes ending correct and consensual" tone="green" />
        <Metric label="Replay accepted" value={`${report.activity.replay_accepted} / ${report.activity.replay_attempts}`} detail="candidate adopted into live answer" tone="orange" />
        <Metric label="Replay median cost" value={replay?.median_cost === null || replay?.median_cost === undefined ? "—" : COMPACT.format(replay.median_cost)} detail="tokens per complete arm, including prefix" tone="orange" />
      </section>

      <section className="study-block activity-block">
        <div className="block-heading"><div><p className="eyebrow">Observed interaction activity</p><h3>What the agents did across the run</h3></div><p>{`${report.activity.trials} arm trials across ${report.activity.prefixes} matched prefixes. Tag and rollback totals include all arms; replay acceptance is counted only in the replay arm.`}</p></div>
        <div className="activity-grid">
          <Metric label="Refute messages" value={COMPACT.format(report.activity.tags.refute)} detail="challenge / corrective-information moves" />
          <Metric label="Revise messages" value={COMPACT.format(report.activity.tags.revise)} detail="changed-prediction moves" />
          <Metric label="Reject messages" value={COMPACT.format(report.activity.tags.reject)} detail="declined-contribution moves" />
          <Metric label="Ratify messages" value={COMPACT.format(report.activity.tags.ratify)} detail="explicit agreement moves" />
          <Metric label="Rollback operations" value={COMPACT.format(report.activity.rollbacks)} detail="recorded branch operations across arms" tone="blue" />
          <Metric label="Replay accepted" value={COMPACT.format(report.activity.replay_accepted)} detail="reply_accepted outcome in replay arm" tone="green" />
          <Metric label="Replay not helpful" value={COMPACT.format(report.activity.replay_outcomes.not_helpful ?? 0)} detail="candidate did not improve the live board" />
          <Metric label="Replay incomplete" value={COMPACT.format(report.activity.replay_outcomes.incomplete ?? 0)} detail="candidate generation or evaluation incomplete" tone="orange" />
        </div>
        <p className="activity-note">These are counts of recorded protocol actions, not unique agents or independent successful recoveries. The paired outcome table below reports correctness and consensus separately.</p>
      </section>

      <ArmRows report={report} />
      <div className="study-two-col"><Funnel report={report} onFilter={setFilter} /><Comparison report={report} /></div>
      <div className="filter-strip" aria-label="Case matrix filter">
        {(["all", "eligible", "adopted", "recovered"] as Filter[]).map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "All units" : value.replaceAll("_", " ")}</button>)}
      </div>
      <CaseMatrix report={report} filter={filter} onOpen={onOpen} />
      <Integrity report={report} />
    </div>
  );
}
