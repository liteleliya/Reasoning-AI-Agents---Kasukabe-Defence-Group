import { useEffect, useState } from "react";

type Condition = {
  enabled_agents: number;
  trials: number;
  checkpoints: number;
  rollbacks: number;
  consensus: number;
  correct_consensus: number;
  mean_tokens: number;
};

type Summary = {
  medagentbench: { tasks: number; correct: number; invalid_action: number; completed_incorrect: number; task_types: { task_type: string; trials: number; correct: number }[]; interpretation: string };
  stage2_adaptive: { total_sessions: number; expected_sessions: number; partial_level_3_sessions: number; completed_per_level: Record<string, Condition> };
  stage3_static: { total_sessions: number; expected_sessions: number; conditions: Condition[] };
  stage2_stage3_matched: { shared_unique_instances_per_level: number; compared_levels: number[]; results: { enabled_agents: number; metric: string; adaptive_wins: number; static_wins: number; ties: number; adaptive_minus_static_pp: number }[] };
  limitations: string[];
};

const number = new Intl.NumberFormat("en-US");

export function ProjectOutcomes() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/project-results", { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("Consolidated results are unavailable"); return response.json(); })
      .then(setData)
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => controller.abort();
  }, []);

  if (error) return <section className="study-block"><p className="eyebrow">Additional benchmarks</p><p>{error}</p></section>;
  if (!data) return <section className="study-block"><p className="eyebrow">Additional benchmarks</p><p>Loading consolidated project results…</p></section>;

  const med = data.medagentbench;
  const cross = data.stage2_stage3_matched.results.filter((row) => row.metric === "correct_consensus");
  return (
    <section className="project-outcomes" aria-label="Cross-benchmark results">
      <div className="block-heading">
        <div><p className="eyebrow">Project results across benchmarks</p><h3>What the full project has shown</h3></div>
        <p>Separate benchmark outcomes are shown with their sample sizes and evaluation limits.</p>
      </div>
      <section className="study-block">
        <div className="block-heading"><div><p className="eyebrow">MSCoRe density study</p><h3>Adaptive and static policies</h3></div>
          <p>Stage 2 stopped before the 3/3 condition finished. Cross-stage comparisons use only the shared 250 task IDs at complete levels.</p></div>
        <div className="matrix-wrap"><table className="case-matrix">
          <thead><tr><th>CF agents</th><th>Stage 2 adaptive</th><th>Stage 3 static</th><th>Matched correct-consensus difference</th></tr></thead>
          <tbody>{[0, 1, 2].map((level) => {
            const adaptive = data.stage2_adaptive.completed_per_level[String(level)];
            const stat = data.stage3_static.conditions.find((condition) => condition.enabled_agents === level);
            const comparison = cross.find((row) => row.enabled_agents === level);
            if (!adaptive || !stat || !comparison) return null;
            return <tr key={level}><th scope="row">{level} / 3</th>
              <td>{adaptive.trials} trials · {adaptive.checkpoints} checkpoints · {adaptive.rollbacks} rollback sessions · {adaptive.consensus} consensus · {adaptive.correct_consensus} correct consensus</td>
              <td>{stat.trials} trials · {stat.checkpoints} checkpoints · {stat.rollbacks} rollback sessions · {stat.consensus} consensus · {stat.correct_consensus} correct consensus</td>
              <td>{comparison.adaptive_minus_static_pp > 0 ? "+" : ""}{comparison.adaptive_minus_static_pp.toFixed(1)} pp; {comparison.adaptive_wins} adaptive wins, {comparison.static_wins} static wins, {comparison.ties} ties (n={comparison.ties + comparison.adaptive_wins + comparison.static_wins})</td>
            </tr>;
          })}</tbody>
        </table></div>
        <p className="activity-note">Stage 2: {number.format(data.stage2_adaptive.total_sessions)} / {number.format(data.stage2_adaptive.expected_sessions)} sessions; density 3/3 has {data.stage2_adaptive.partial_level_3_sessions} partial trials and is excluded from matched claims. Stage 3: {number.format(data.stage3_static.total_sessions)} / {number.format(data.stage3_static.expected_sessions)} sessions. Differences are descriptive; adaptation updates depend on run order.</p>
      </section>
      <section className="study-block">
        <div className="block-heading"><div><p className="eyebrow">MedAgentBench baseline</p><h3>FHIR tool-use evaluation</h3></div>
          <p>Single-agent baseline across 30 tasks, three from each of ten task types, using the official refsol grader.</p></div>
        <div className="metric-grid">
          <article className="metric orange"><span>Correct</span><strong>{med.correct} / {med.tasks}</strong><small>official grader result</small></article>
          <article className="metric"><span>Invalid action</span><strong>{med.invalid_action} / {med.tasks}</strong><small>tool/action format failures</small></article>
          <article className="metric"><span>Completed, incorrect</span><strong>{med.completed_incorrect}</strong><small>validly terminated, failed grading</small></article>
          <article className="metric blue"><span>Task types</span><strong>{med.task_types.length}</strong><small>3 tasks sampled per type</small></article>
        </div>
        <p className="activity-note">Interpretation: the baseline exercises the FHIR interaction path, but it did not solve any task. Output-format compliance is the first improvement target; this score is not evidence of clinical capability.</p>
      </section>
      <section className="study-block integrity-block"><div className="block-heading"><div><p className="eyebrow">Combined interpretation</p><h3>What the evidence says—and what to improve next</h3></div>
        <p>The paired replay baseline, density ablation and clinical tool-use baseline answer different questions. Keep their outcome measures separate.</p></div>
        <ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        <h4>Practical next steps</h4>
        <ul>
          <li><strong>MSCoRe recovery:</strong> validate task answer schemas and checkpoint eligibility, enforce the post-checkpoint call budget, then repeat a preregistered matched recovery study with human-audited examples.</li>
          <li><strong>Density comparison:</strong> finish the adaptive 3/3 condition before making a complete four-level comparison; change the learning reward only if correctness is directly measured.</li>
          <li><strong>MedAgentBench:</strong> constrain and validate GET/POST/FINISH formatting, verify each action against official examples, then run a small format-validation set before scaling.</li>
          <li><strong>Evaluation quality:</strong> add blinded human ratings for explanation quality and report them separately from automatic correctness, consensus and adoption.</li>
        </ul>
      </section>
    </section>
  );
}
