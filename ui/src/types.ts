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
