import { describe, expect, it } from "vitest";
import { rollbacks, upTo } from "./layout";
import {
  changedFields, fmtDelta, fmtDistance, noReplayNote, pairBranches, replayView, sentences,
} from "./replay";
import type { EventRecord } from "./types";

let seq = 0;
const ev = (author: string, tag: EventRecord["tag"], reply_to: number | null = null,
  prediction = "Y", extra: Partial<EventRecord> = {}): EventRecord => ({
  seq: seq++, session_id: "s", author, kind: "message", tag, reply_to, prediction,
  explanation: "because", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {}, ...extra,
});
const RID = "s::replay-1";
const step = (author: string, tag: EventRecord["tag"], branch: string, prediction: string, fork: number,
  tokens = 0, explanation = "because") =>
  ev(author, tag, null, prediction, {
    kind: "rollback_step", counterfactual: true, explanation, tokens: { in: tokens, out: 0 },
    meta: { replay_id: RID, branch, fork_seq: fork, fork_reply_to: fork === 6 ? 4 : 6, tested: fork === 6 },
  });

/** The fixture's recovered session: stall at #8, replay of #6, adoption at #17, TERM at #18. */
function recovered(endMeta: Record<string, unknown> = {}, withEnd = true): EventRecord[] {
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
const adopted = () => ev("A", "REVISE", 7, "Y", { meta: { adopted_counterfactual: true, replay_id: RID } });
const term = (meta: Record<string, unknown> = {}, explanation = "consensus") =>
  ev("system", "TERM", null, "", { explanation, meta });
const view = (events: EventRecord[]) => replayView(rollbacks(events)[0], events);

describe("formatting", () => {
  it("rounds only for display and signs the delta", () => {
    expect(fmtDistance(1 / 3)).toBe("0.33");
    expect(fmtDistance(0)).toBe("0.00");
    expect(fmtDistance(null)).toBe("—");
    expect(fmtDelta(-1 / 3)).toBe("−0.33");
    expect(fmtDelta(0)).toBe("0.00");
    expect(fmtDelta(0.5)).toBe("+0.50");
    expect(fmtDelta(null)).toBe("—");
  });
});

describe("what changed", () => {
  it("names the fields that differ between the two tested messages", () => {
    const [a, b] = [recovered()[10], recovered()[13]];
    expect(changedFields(a, b)).toEqual(["tag", "prediction", "explanation"]);
    expect(changedFields(a, a)).toEqual([]);
    expect(changedFields(undefined, b)).toEqual([]);
  });

  it("flags the sentences of an explanation that the other one lacks", () => {
    const mark = (text: string, other: string) => sentences(text, other).map((s) => [s.text, s.changed]);
    expect(mark("Plan X is safe. The limit is soft.", "Plan X is safe. The limit is binding.")).toEqual([
      ["Plan X is safe.", false],
      ["The limit is soft.", true],
    ]);
    expect(mark("Same.", "Same.")).toEqual([["Same.", false]]);
    expect(mark("", "x")).toEqual([]);
  });
});

describe("pairBranches", () => {
  it("lines the branches up by agent and turn", () => {
    const rb = rollbacks(recovered())[0];
    const rows = pairBranches(rb.branches.original, rb.branches.replacement);
    expect(rows.map((r) => [r.author, r.original?.tag, r.replacement?.tag, r.differs])).toEqual([
      ["A", "REFUTE", "REVISE", true],
      ["B", "REFUTE", "RATIFY", true],
      ["C", "REFUTE", "RATIFY", true],
    ]);
  });

  it("leaves a side empty when only one branch got that far", () => {
    const rb = rollbacks(recovered())[0];
    const rows = pairBranches(rb.branches.original, rb.branches.replacement.slice(0, 2));
    expect(rows[2].original?.author).toBe("C");
    expect(rows[2].replacement).toBeUndefined();
  });
});

describe("replayView", () => {
  it("reads a completed replay: distances, signed delta, split tokens and the real links", () => {
    const events = [...recovered(), adopted(), term({ recovery: { replay_id: RID, outcome: "reply_accepted" } })];
    const v = view(events);
    expect(v.status).toBe("completed");
    expect(v.verdict.kind).toBe("helped");
    expect([v.target?.seq, v.challengerSeq, v.legacy]).toEqual([6, 7, false]);
    expect(v.distances).toEqual({ original: 1 / 3, replacement: 0, recorded: 1 / 3 });
    expect(v.delta).toBeCloseTo(-1 / 3);
    expect(v.tokens).toEqual({ candidate: 30, original: 14, replacement: 10, total: 54 });
    expect(v.rows).toHaveLength(3);
    expect(v.baselineLabel).toBe("Simulated continuation of the original reply");
    expect(v.changed).toEqual(["tag", "prediction", "explanation"]);
    expect(v.adoption).toMatchObject({ kind: "adopted" });
    expect(v.adoption.kind === "adopted" && v.adoption.event.seq).toBe(17);
  });

  it("hides a later adoption while the cursor is before it", () => {
    const events = [...recovered(), adopted(), term()];
    expect(view(upTo(events, 16)).adoption.kind).toBe("pending");
    expect(view(upTo(events, 17)).adoption.kind).toBe("adopted");
  });

  it("says why a helpful replay was not adopted once the session has ended", () => {
    const v = view([...recovered(), term({ recovery: { replay_id: RID, outcome: "stale_target" } }, "impasse")]);
    expect(v.adoption).toEqual({ kind: "not_adopted", reason: "no live message was left to answer" });
  });

  it("calls a replacement that left disagreement alone unchanged, and a worse one worse", () => {
    expect(view(recovered({ credit_delta: 0, distance_replacement: 1 / 3 })).verdict.kind).toBe("unchanged");
    expect(view(recovered({ credit_delta: 1 / 3, distance_replacement: 2 / 3 })).verdict.kind).toBe("worse");
  });

  it("shows an incomplete comparison without a delta and with its reason", () => {
    const v = view(recovered({ status: "incomplete", reason: "C: passed", credit_delta: null,
      distance_original: null, distance_replacement: null }));
    expect(v.verdict.kind).toBe("incomplete");
    expect(v.verdict.text).toContain("C: passed");
    expect(v.delta).toBeNull();
    expect(fmtDelta(v.delta)).toBe("—");
  });

  it("renders the steps seen so far while the replay is still open", () => {
    const v = view(upTo(recovered(), 13));
    expect(v.status).toBe("open");
    expect(v.verdict.kind).toBe("open");
    expect(v.delta).toBeNull();
    expect(v.rows.map((r) => r.author)).toEqual(["A", "B", "C"]);
    expect(v.rows[0].replacement).toBeDefined();
    expect(v.rows[1].replacement).toBeUndefined();
  });

  it("records a candidate that could not be obtained", () => {
    seq = 0;
    const log = [
      ev("A", "INIT", null, "X"), ev("B", "INIT"), ev("A", "REFUTE", 1, "X"), ev("B", "REFUTE", 2),
      ev("A", null, 2, "", { kind: "rollback_start", counterfactual: true,
        meta: { replay_id: RID, challenger_seq: 3 } }),
      ev("A", null, null, "", { kind: "rollback_end", counterfactual: true,
        meta: { replay_id: RID, status: "candidate_failed", reason: "no JSON object found" } }),
    ];
    const v = view(log);
    expect(v.verdict.kind).toBe("failed");
    expect(v.verdict.text).toContain("no JSON object found");
    expect(v.rows).toEqual([]);
  });

  it("labels the old kind of trace as the recorded continuation, up to the rollback start", () => {
    seq = 0;
    const log = [
      ev("a", "INIT", null, "x"), ev("b", "INIT", null, "y"),
      ev("a", "REFUTE", 1, "x"), ev("b", "REFUTE", 2, "y"),
      ev("a", null, 2, "", { kind: "rollback_start", counterfactual: true, explanation: "what if" }),
      ev("a", "REVISE", null, "y", { kind: "rollback_step", counterfactual: true }),
      ev("b", "RATIFY", null, "y", { kind: "rollback_step", counterfactual: true }),
      ev("a", null, null, "", { kind: "rollback_end", counterfactual: true,
        meta: { credit_delta: -0.5, distance_real: 0.5, distance_replay: 0 } }),
      ev("a", "REFUTE", 3, "x"),
    ];
    const v = view(log);
    expect(v.legacy).toBe(true);
    expect(v.baselineLabel).toBe("Recorded continuation");
    expect(v.rows.map((r) => r.original?.seq)).toEqual([2, 3]); // nothing after the rollback start
    expect(v.distances).toEqual({ original: null, replacement: 0, recorded: 0.5 });
    expect(v.delta).toBe(-0.5);
    expect(v.verdict.kind).toBe("helped");
  });
});

describe("noReplayNote", () => {
  it("waits until the session ends before saying nothing was replayed", () => {
    seq = 0;
    expect(noReplayNote([ev("A", "INIT")])).toBe("No replay has been recorded yet.");
  });

  it("explains why from the stop record when it has one", () => {
    expect(noReplayNote([term({ recovery: { eligible: true, skip_reason: "not_enabled" } }, "impasse")])).toBe(
      "No replay was run: the challenged agent could not replay.",
    );
    expect(noReplayNote([term({}, "consensus")])).toBe("No replay was needed: the session reached consensus.");
  });

  it("says the reason is unavailable for an archive without replay diagnostics", () => {
    expect(noReplayNote([term({}, "impasse")])).toBe(
      "No replay was recorded. Reason unavailable: this archive has no replay diagnostics.",
    );
  });
});
