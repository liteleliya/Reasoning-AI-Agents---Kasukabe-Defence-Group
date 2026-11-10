import type { EventRecord } from "../types";

let seq = 0;
export const resetSeq = () => {
  seq = 0;
};

export const ev = (author: string, tag: EventRecord["tag"], reply_to: number | null = null,
  prediction = "Y", extra: Partial<EventRecord> = {}): EventRecord => ({
  seq: seq++, session_id: "s", author, kind: "message", tag, reply_to, prediction,
  explanation: "because", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {}, ...extra,
});

export const RID = "s::replay-1";
const step = (author: string, tag: EventRecord["tag"], branch: string, prediction: string, fork: number,
  tokens = 0, explanation = "because") =>
  ev(author, tag, null, prediction, {
    kind: "rollback_step", counterfactual: true, explanation, tokens: { in: tokens, out: 0 },
    meta: { replay_id: RID, branch, fork_seq: fork, fork_reply_to: fork === 6 ? 4 : 6, tested: fork === 6 },
  });

/** The fixture's recovered session: stall at #8, replay of #6 at #9-#16. Adoption and TERM follow. */
export function recovered(endMeta: Record<string, unknown> = {}, withEnd = true): EventRecord[] {
  seq = 0;
  const log = [
    ev("A", "INIT", null, "X"), ev("B", "INIT"), ev("C", "INIT"),
    ev("A", "REFUTE", 1, "X"), ev("B", "REFUTE", 3), ev("C", "RATIFY", 4),
    ev("A", "REFUTE", 4, "X", { explanation: "Plan X is safe. The limit is soft." }),
    ev("B", "REFUTE", 6), ev("C", "RATIFY", 7),
    ev("A", null, 6, "", { kind: "rollback_start", counterfactual: true, tokens: { in: 20, out: 10 },
      explanation: "what if", meta: { replay_id: RID, target_seq: 6, challenger_seq: 7 } }),
    step("A", "REFUTE", "original", "X", 6, 0, "Plan X is safe. The limit is soft."),
    step("B", "REFUTE", "original", "Y", 7, 7), step("C", "REFUTE", "original", "Y", 8, 7),
    step("A", "REVISE", "replacement", "Y", 6, 0, "Plan X is safe. The four-minute limit is binding."),
    step("B", "RATIFY", "replacement", "Y", 7, 5), step("C", "RATIFY", "replacement", "Y", 8, 5),
  ];
  if (withEnd) {
    log.push(ev("A", null, null, "", { kind: "rollback_end", counterfactual: true, meta: {
      replay_id: RID, status: "completed", distance_original: 1 / 3, distance_replacement: 0,
      distance_recorded: 1 / 3, credit_delta: -1 / 3, branch_tokens: { original: 14, replacement: 10 },
      ...endMeta } }));
  }
  return log;
}

export const adopted = () =>
  ev("A", "REVISE", 7, "Y", { meta: { adopted_counterfactual: true, replay_id: RID } });

export const term = (meta: Record<string, unknown> = {}, explanation = "consensus") =>
  ev("system", "TERM", null, "", { explanation, meta });
