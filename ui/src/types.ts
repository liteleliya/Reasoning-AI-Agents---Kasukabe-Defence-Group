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
