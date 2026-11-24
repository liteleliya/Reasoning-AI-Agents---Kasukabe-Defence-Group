export type Tag = "INIT" | "RATIFY" | "REFUTE" | "REVISE" | "REJECT" | "TERM";
export type Kind = "message" | "rollback_start" | "rollback_step" | "rollback_end";

/** One row of the event log, as sent by the server (spec section 2, "Event record"). */
export interface EventRecord {
  seq: number;
  session_id: string;
  author: string;
  kind: Kind;
  tag: Tag | null;
  reply_to: number | null;
  prediction: string;
  explanation: string;
  counterfactual: boolean;
  tokens: { in: number; out: number };
  meta: Record<string, unknown>;
}

export interface SessionInfo {
  session_id: string;
  seq: number;
  agents: string[];
  terminated: boolean;
  stop_reason: string | null;
  /** What the server could tell about the session; null where the archive does not say. */
  case_id: string;
  label: string;
  condition: string | null;
  seed: number | null;
  source: string;
  enabled_agents: number | null;
  n_agents: number | null;
  correct: boolean | null;
}

/** The public record of an authored case; the grading record is never sent to the viewer. */
export interface CaseBrief {
  id: string;
  split: string;
  version: number;
  domain: string;
  question: string;
  context: string;
  evidence: { id: string; text: string }[];
  decisions: string[];
  fields: { name: string; kind: string; unit: string; values: string[]; decisive: boolean; description: string }[];
}

export interface Snapshot {
  session_id: string;
  seq: number;
  agents: string[];
  predictions: Record<string, string>;
  terminated: boolean;
  stop_reason: string | null;
  open_rollback: number | null;
  tokens: { in: number; out: number; rollback_in: number; rollback_out: number; total: number };
  intelligibility: {
    label: "ultra_strong" | "strong" | "failed";
    revises: number;
    pairs: { sender: string; receiver: string; tags: Tag[]; one_way: boolean }[];
  };
}

/** The run summary computed by the server (src/bench/summary.py); a null count was not recorded. */
export interface RunSummary {
  run: {
    label: string;
    kind: "historical" | "controlled" | "model" | null;
    model: string;
    trials: number;
    cases: number;
    conditions: number;
    seeds: number[];
  };
  totals: { trials: number; consensus: number; correct_consensus: number; recorded_replays: number };
  conditions: {
    condition: string;
    enabled_agents: number | null;
    n_agents: number | null;
    trials: number;
    consensus: number;
    correct_consensus: number;
    wrong_consensus: number;
    ungraded_consensus: number;
    eligible: number | null;
    median_tokens: number | null;
  }[];
  recovery: { stage: string; label: string; count: number | null }[];
  examples: {
    kind: string;
    title: string;
    session_id: string;
    case_id: string;
    label: string;
    condition: string;
    outcome: string;
  }[];
}

export type StudyArm = "standard" | "forward" | "replay";

export interface StudyReport {
  activity: {
    prefixes: number;
    checkpoints: number;
    trials: number;
    tags: Record<"ratify" | "refute" | "revise" | "reject", number>;
    rollbacks: number;
    replay_outcomes: Record<string, number>;
    replay_attempts: number;
    replay_accepted: number;
  };
  provenance: {
    model: string;
    persona_set: string;
    temperature: number | null;
    n_agents: number | null;
    seeds: number[];
    analysis_source: string;
  };
  outcomes: {
    arm: StudyArm;
    trials: number;
    eligible: number;
    consensus: number;
    correct_consensus: number;
    wrong_consensus: number;
    ungraded_consensus: number;
    correct_recovery: number;
    median_cost: number | null;
    median_wall_s: number | null;
  }[];
  funnel: { stage: string; count: number }[];
  comparisons: Record<
    string,
    {
      arm: string;
      other: string;
      pairs: number;
      cases: number;
      wins: number;
      losses: number;
      ties: number;
      small: boolean;
      rate_difference: number | null;
      ci: [number, number] | null;
      differences: Record<string, { n: number; mean: number | null; ci: [number, number] | null }>;
    }
  >;
  examples: Record<string, string[]>;
  integrity: {
    grading: { rubric: number; automatic: number; missing: number };
    authored_answers: { total: number; unresolved: number };
    allowance: { limit: number | null; violations: { trial_key: string; calls: number }[] };
  };
  units: {
    case_id: string;
    label: string;
    domain: string;
    seed: number;
    checkpoint: "opened" | "none";
    arms: Partial<
      Record<
        StudyArm,
        {
          session_id: string;
          stop_reason: string;
          correct: boolean | null;
          recovery_outcome: string;
          tokens: number | null;
        }
      >
    >;
  }[];
  note: string;
}
