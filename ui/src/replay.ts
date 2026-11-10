import { isRealMessage, type Rollback } from "./layout";
import type { EventRecord } from "./types";

export type Field = "tag" | "prediction" | "explanation";
export type VerdictKind = "helped" | "unchanged" | "worse" | "incomplete" | "failed" | "open";

export interface Sentence {
  text: string;
  changed: boolean; // not in the other message's explanation
}

export interface PairedRow {
  key: string; // agent and turn, e.g. "B#0"
  author: string;
  original?: EventRecord;
  replacement?: EventRecord;
  differs: boolean;
}

export type Adoption =
  | { kind: "adopted"; event: EventRecord }
  | { kind: "not_adopted"; reason: string }
  | { kind: "pending" };

export interface ReplayView {
  replayId: string | null;
  legacy: boolean;
  status: string;
  verdict: { kind: VerdictKind; text: string };
  target: EventRecord | undefined;
  challengerSeq: number | null;
  tested: { original?: EventRecord; replacement?: EventRecord };
  changed: Field[];
  sentences: { original: Sentence[]; replacement: Sentence[] };
  rows: PairedRow[];
  baselineLabel: string;
  distances: { original: number | null; replacement: number | null; recorded: number | null };
  delta: number | null;
  tokens: { candidate: number; original: number; replacement: number; total: number };
  adoption: Adoption;
}

const EPSILON = 1e-9;

export const fmtDistance = (d: number | null) => (d === null ? "—" : d.toFixed(2));

/** Signed difference, rounded only for display; negative means the replacement helped. */
export function fmtDelta(d: number | null): string {
  if (d === null) return "—";
  if (d === 0) return "0.00";
  return `${d < 0 ? "−" : "+"}${Math.abs(d).toFixed(2)}`;
}

/** Which of tag, prediction and explanation differ between the two tested messages. */
export function changedFields(a?: EventRecord, b?: EventRecord): Field[] {
  if (!a || !b) return [];
  const fields: Field[] = [];
  if (a.tag !== b.tag) fields.push("tag");
  if (a.prediction.trim() !== b.prediction.trim()) fields.push("prediction");
  if (a.explanation.trim() !== b.explanation.trim()) fields.push("explanation");
  return fields;
}

const split = (text: string) =>
  text.split(/(?<=[.!?。！？])\s*/).map((s) => s.trim()).filter(Boolean);
const norm = (s: string) => s.toLowerCase();

/** The sentences of `text`, each flagged if the other explanation does not contain it. */
export function sentences(text: string, other: string): Sentence[] {
  const theirs = new Set(split(other).map(norm));
  return split(text).map((s) => ({ text: s, changed: !theirs.has(norm(s)) }));
}

/** Line the two branches up by responding agent and turn; a side is missing if it got no further. */
export function pairBranches(original: EventRecord[], replacement: EventRecord[]): PairedRow[] {
  const keyed = (events: EventRecord[]) => {
    const seen = new Map<string, number>();
    return events.map((e) => {
      const n = seen.get(e.author) ?? 0;
      seen.set(e.author, n + 1);
      return [`${e.author}#${n}`, e] as const;
    });
  };
  const a = new Map(keyed(original));
  const b = new Map(keyed(replacement));
  return [...new Set([...a.keys(), ...b.keys()])].map((key) => {
    const [o, r] = [a.get(key), b.get(key)];
    return {
      key,
      author: (o ?? r)!.author,
      original: o,
      replacement: r,
      differs: !o || !r || o.tag !== r.tag || o.prediction !== r.prediction,
    };
  });
}

const OUTCOME_TEXT: Record<string, string> = {
  not_helpful: "the replacement did not lower disagreement",
  incomplete: "the comparison was incomplete",
  candidate_failed: "no usable replacement was obtained",
  stale_target: "no live message was left to answer",
  reply_rejected: "the board refused the reply",
  no_reply: "the policy posted no reply",
  no_author: "no agent could write a replacement",
};
// why nothing was adopted when the stop record does not say, by how the comparison came out
const NOT_ADOPTED: Partial<Record<VerdictKind, string>> = {
  unchanged: OUTCOME_TEXT.not_helpful,
  worse: OUTCOME_TEXT.not_helpful,
  incomplete: OUTCOME_TEXT.incomplete,
  failed: OUTCOME_TEXT.candidate_failed,
};
const SKIP_TEXT: Record<string, string> = {
  roster_incomplete: "not every agent had opened and replied",
  no_disagreement: "the agents already agreed",
  no_full_window: "the debate had not yet gone a full window without progress",
  no_challenged_reply: "no reply had been challenged with REFUTE or REJECT",
  not_enabled: "the challenged agent could not replay",
  budget_exhausted: "the recovery budget was spent",
  recovery_disabled: "recovery was switched off for this run",
};

const metaText = (e: EventRecord | undefined, key: string) => {
  const v = e?.meta[key];
  return typeof v === "string" ? v : "";
};
const metaNum = (e: EventRecord | undefined, key: string) => {
  const v = e?.meta[key];
  return typeof v === "number" ? v : null;
};
const spent = (events: EventRecord[]) => events.reduce((n, e) => n + e.tokens.in + e.tokens.out, 0);

function verdictOf(rb: Rollback): ReplayView["verdict"] {
  const reason = metaText(rb.end, "reason");
  if (!rb.end) {
    return { kind: "open", text: "Replaying… the comparison is not finished, so no delta is shown yet." };
  }
  if (rb.status === "candidate_failed") {
    return { kind: "failed", text: `No usable replacement: ${reason || "reason not recorded"}.` };
  }
  if (rb.status === "incomplete" || rb.creditDelta === null) {
    return { kind: "incomplete", text: `Comparison incomplete: ${reason || "reason not recorded"}. No delta is shown.` };
  }
  if (rb.creditDelta < -EPSILON) {
    return { kind: "helped", text: "The replacement lowered disagreement in the sandbox." };
  }
  if (rb.creditDelta > EPSILON) {
    return { kind: "worse", text: "The replacement raised disagreement in the sandbox." };
  }
  return { kind: "unchanged", text: "The replacement left disagreement unchanged in the sandbox." };
}

/** Whether a real reply came out of the replay, judged only from events up to the cursor. */
function adoptionOf(rb: Rollback, events: EventRecord[], kind: VerdictKind): Adoption {
  const adopted = events.find(
    (e) =>
      isRealMessage(e) &&
      e.meta.adopted_counterfactual === true &&
      (rb.replayId ? e.meta.replay_id === rb.replayId : e.seq > rb.start.seq),
  );
  if (adopted) return { kind: "adopted", event: adopted };
  const term = events.find((e) => e.kind === "message" && e.tag === "TERM");
  if (!term) return { kind: "pending" };
  const recovery = term.meta.recovery as { replay_id?: string; outcome?: string } | undefined;
  if (recovery?.outcome && (!rb.replayId || recovery.replay_id === rb.replayId)) {
    return { kind: "not_adopted", reason: OUTCOME_TEXT[recovery.outcome] ?? recovery.outcome };
  }
  const reason = NOT_ADOPTED[kind] ?? "no adopted reply is on record";
  return { kind: "not_adopted", reason };
}

/**
 * Everything the replay panel shows for one replay, from the events up to the cursor. Newer logs
 * compare the two simulated branches; older ones compare the replay with the recorded
 * continuation, up to the rollback start.
 */
export function replayView(rb: Rollback, events: EventRecord[]): ReplayView {
  const verdict = verdictOf(rb);
  const original = rb.legacy
    ? rb.real.filter((e) => e.seq < rb.start.seq)
    : rb.branches.original;
  const n = (key: string) => metaNum(rb.end, key);
  const distances = rb.legacy
    ? { original: null, replacement: n("distance_replay"), recorded: n("distance_real") }
    : {
        original: n("distance_original"),
        replacement: n("distance_replacement"),
        recorded: n("distance_recorded"),
      };
  const tested = {
    original: rb.legacy ? rb.target : rb.branches.original[0],
    replacement: rb.branches.replacement[0],
  };
  const tokens = {
    candidate: rb.start.tokens.in + rb.start.tokens.out,
    original: rb.legacy ? 0 : spent(rb.branches.original),
    replacement: spent(rb.branches.replacement),
    total: 0,
  };
  tokens.total = tokens.candidate + tokens.original + tokens.replacement;
  const [o, r] = [tested.original?.explanation ?? "", tested.replacement?.explanation ?? ""];
  return {
    replayId: rb.replayId,
    legacy: rb.legacy,
    status: rb.status,
    verdict,
    target: rb.target,
    challengerSeq: rb.challengerSeq,
    tested,
    changed: changedFields(tested.original, tested.replacement),
    sentences: { original: sentences(o, r), replacement: sentences(r, o) },
    rows: pairBranches(original, rb.branches.replacement),
    baselineLabel: rb.legacy ? "Recorded continuation" : "Simulated continuation of the original reply",
    distances,
    delta: rb.creditDelta,
    tokens,
    adoption: adoptionOf(rb, events, verdict.kind),
  };
}

/** What to say when the log holds no replay at all. */
export function noReplayNote(events: EventRecord[]): string {
  const term = events.find((e) => e.kind === "message" && e.tag === "TERM");
  if (!term) return "No replay has been recorded yet.";
  const recovery = term.meta.recovery as { skip_reason?: string } | undefined;
  if (recovery?.skip_reason) {
    return `No replay was run: ${SKIP_TEXT[recovery.skip_reason] ?? recovery.skip_reason}.`;
  }
  if (term.explanation === "consensus") return "No replay was needed: the session reached consensus.";
  return "No replay was recorded. Reason unavailable: this archive has no replay diagnostics.";
}
