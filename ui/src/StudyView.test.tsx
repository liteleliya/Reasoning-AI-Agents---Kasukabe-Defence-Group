import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StudyView } from "./StudyView";
import type { StudyReport } from "./types";

const report: StudyReport = {
  activity: { prefixes: 4, checkpoints: 2, trials: 12, tags: { ratify: 6, refute: 9, revise: 3, reject: 4 },
    rollbacks: 2, replay_outcomes: { reply_accepted: 1, not_helpful: 1 }, replay_attempts: 2, replay_accepted: 1 },
  provenance: { model: "qwen2.5:3b-instruct", persona_set: "dissenter", temperature: 1,
    n_agents: 3, seeds: [0, 1], analysis_source: "saved" },
  outcomes: [
    { arm: "standard", trials: 4, eligible: 2, consensus: 2, correct_consensus: 1, wrong_consensus: 1,
      ungraded_consensus: 0, correct_recovery: 0, median_cost: 500, median_wall_s: 1 },
    { arm: "forward", trials: 4, eligible: 2, consensus: 2, correct_consensus: 1, wrong_consensus: 1,
      ungraded_consensus: 0, correct_recovery: 0, median_cost: 550, median_wall_s: 1 },
    { arm: "replay", trials: 4, eligible: 2, consensus: 3, correct_consensus: 2, wrong_consensus: 1,
      ungraded_consensus: 0, correct_recovery: 1, median_cost: 800, median_wall_s: 2 },
  ],
  funnel: [
    { stage: "eligible", count: 2 }, { stage: "attempted", count: 2 },
    { stage: "completed", count: 2 }, { stage: "helpful", count: 1 },
    { stage: "adopted", count: 1 }, { stage: "correct_recovery", count: 1 },
  ],
  comparisons: {
    replay_vs_standard: { arm: "replay", other: "standard", pairs: 2, cases: 1, wins: 1, losses: 0,
      ties: 1, small: true, rate_difference: 0.5, ci: [0, 1],
      differences: { intervention_tokens: { n: 2, mean: 300, ci: [100, 500] } } },
  },
  examples: { successful_recovery: ["s-r"], declined_branch: [], wrong_consensus: ["s-s"] },
  integrity: { grading: { rubric: 0, automatic: 12, missing: 0 },
    authored_answers: { total: 2, unresolved: 0 }, allowance: { limit: 6, violations: [] } },
  units: [{ case_id: "case:route", label: "Route", domain: "logistics", seed: 0, checkpoint: "opened",
    arms: {
      standard: { session_id: "s-s", stop_reason: "impasse", correct: false, recovery_outcome: "no_reply", tokens: 500 },
      forward: { session_id: "s-f", stop_reason: "impasse", correct: false, recovery_outcome: "no_reply", tokens: 550 },
      replay: { session_id: "s-r", stop_reason: "consensus", correct: true, recovery_outcome: "reply_accepted", tokens: 800 },
    } }],
  note: "Correctness uses the rubric first.",
};

describe("StudyView", () => {
  const html = renderToStaticMarkup(<StudyView report={report} onOpen={() => {}} />);

  it("keeps the three intervention arms and the checkpoint denominator visible", () => {
    expect(html).toContain("Ordinary continuation");
    expect(html).toContain("Forward rethink");
    expect(html).toContain("Counterfactual replay");
    expect(html).toContain("1 / 2");
  });

  it("shows evidence quality rather than hiding the grading and allowance context", () => {
    expect(html).toContain("Evidence quality");
    expect(html).toContain("Every recorded arm stayed within the 6-call");
    expect(html).toContain("0 rubric · 12 automatic · 0 missing");
  });

  it("renders every saved arm as a button that can open its trace", () => {
    expect((html.match(/class="case-cell"/g) ?? []).length).toBe(3);
    expect(html).toContain("reply accepted");
  });
});
