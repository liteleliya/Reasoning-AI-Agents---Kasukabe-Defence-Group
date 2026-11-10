import { describe, expect, it } from "vitest";
import { layout, rollbacks, rosterOf, upTo } from "./layout";
import type { EventRecord } from "./types";

let seq = 0;
const ev = (author: string, tag: EventRecord["tag"], reply_to: number | null = null,
  extra: Partial<EventRecord> = {}): EventRecord => ({
  seq: seq++, session_id: "s", author, kind: "message", tag, reply_to, prediction: "p",
  explanation: "e", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {}, ...extra,
});

describe("layout", () => {
  seq = 0;
  const events = [
    ev("b", "INIT"),
    ev("a", "INIT"),
    ev("a", "REFUTE", 0),
    ev("a", null, 2, { kind: "rollback_start", counterfactual: true }),
    ev("b", "RATIFY", null, { kind: "rollback_step", counterfactual: true }),
    ev("b", "REVISE", 2),
    ev("system", "TERM"),
  ];

  it("puts agents in sorted lanes and only real messages on the timeline", () => {
    const l = layout(events);
    expect(l.lanes).toEqual(["a", "b"]);
    expect(l.nodes.map((n) => [n.event.seq, n.col, n.lane])).toEqual([
      [0, 0, 1], [1, 1, 0], [2, 2, 0], [5, 3, 1],
    ]);
  });

  it("draws reply_to edges and places rollbacks between columns", () => {
    const l = layout(events);
    expect(l.edges.map((e) => [e.from.event.seq, e.to.event.seq])).toEqual([[2, 0], [5, 2]]);
    expect(l.rollbacks.map((r) => [r.start.seq, r.col])).toEqual([[3, 2.5]]);
  });

  it("filters to a point in the log", () => {
    expect(upTo(events, 2).map((e) => e.seq)).toEqual([0, 1, 2]);
  });
});

describe("rollbacks", () => {
  it("pairs replayed steps with the real continuation and reads the credit delta", () => {
    seq = 0;
    const events = [
      ev("a", "INIT"),
      ev("b", "INIT"),
      ev("a", "REFUTE", 1),
      ev("b", "REFUTE", 2),
      ev("a", null, 2, { kind: "rollback_start", counterfactual: true }),
      ev("a", "REVISE", 1, { kind: "rollback_step", counterfactual: true,
        tokens: { in: 10, out: 2 } }),
      ev("b", "RATIFY", null, { kind: "rollback_step", counterfactual: true,
        tokens: { in: 5, out: 1 } }),
      ev("a", null, null, { kind: "rollback_end", counterfactual: true,
        meta: { credit_delta: -0.5 } }),
      ev("a", "REFUTE", 3),
    ];
    const [rb] = rollbacks(events);
    expect(rb.target?.seq).toBe(2);
    expect(rb.steps.map((e) => e.tag)).toEqual(["REVISE", "RATIFY"]);
    expect(rb.real.map((e) => e.seq)).toEqual([2, 3]);
    expect(rb.creditDelta).toBe(-0.5);
    expect(rb.tokens).toBe(18);
  });

  it("leaves an unfinished rollback open", () => {
    seq = 0;
    const events = [
      ev("a", "INIT"),
      ev("a", null, 0, { kind: "rollback_start", counterfactual: true }),
    ];
    const [rb] = rollbacks(events);
    expect(rb.end).toBeUndefined();
    expect(rb.real.map((e) => e.seq)).toEqual([0]);
  });
});


describe("roster and termination", () => {
  seq = 0;
  const log = [
    ev("b", "INIT"),
    ev("a", "INIT"),
    ev("c", "INIT"),
    ev("a", "REFUTE", 1),
    ev("system", "TERM", null, { explanation: "impasse" }),
  ];

  it("lists every agent that speaks anywhere in the log, sorted", () => {
    expect(rosterOf(log)).toEqual(["a", "b", "c"]);
    expect(rosterOf([])).toEqual([]);
  });

  it("keeps a lane for an agent that has not spoken yet in the visible part", () => {
    const l = layout(upTo(log, 1), rosterOf(log));
    expect(l.lanes).toEqual(["a", "b", "c"]);
    expect(l.nodes.map((n) => n.lane)).toEqual([1, 0]);
  });

  it("marks TERM just after the last real message and keeps it off the timeline", () => {
    const l = layout(log);
    expect(l.nodes.map((n) => n.event.seq)).toEqual([0, 1, 2, 3]);
    expect(l.term?.event.seq).toBe(4);
    expect(l.term?.col).toBe(3.5);
    expect(layout(upTo(log, 3)).term).toBeNull();
  });
});

describe("rollbacks with replay ids", () => {
  const step = (branch: string, tag: EventRecord["tag"], id = "s::replay-1", tokens = 0) =>
    ev("b", tag, null, {
      kind: "rollback_step", counterfactual: true, tokens: { in: tokens, out: 0 },
      meta: { replay_id: id, branch, fork_seq: 6, tested: false },
    });

  it("groups steps by replay id and by branch, and reads status and challenger", () => {
    seq = 0;
    const events = [
      ev("a", "INIT"), ev("b", "INIT"), ev("a", "REFUTE", 1), ev("b", "REFUTE", 2),
      ev("a", null, 2, { kind: "rollback_start", counterfactual: true, tokens: { in: 7, out: 3 },
        meta: { replay_id: "s::replay-1", target_seq: 2, challenger_seq: 3 } }),
      step("original", "REFUTE", "s::replay-1", 4),
      step("original", "REFUTE", "s::replay-1", 4),
      step("replacement", "RATIFY", "s::replay-1", 4),
      ev("a", null, null, { kind: "rollback_end", counterfactual: true,
        meta: { replay_id: "s::replay-1", status: "completed", credit_delta: -1 / 3 } }),
    ];
    const [rb] = rollbacks(events);
    expect(rb.replayId).toBe("s::replay-1");
    expect(rb.legacy).toBe(false);
    expect(rb.challengerSeq).toBe(3);
    expect(rb.status).toBe("completed");
    expect(rb.branches.original.map((e) => e.tag)).toEqual(["REFUTE", "REFUTE"]);
    expect(rb.branches.replacement.map((e) => e.tag)).toEqual(["RATIFY"]);
    expect(rb.creditDelta).toBeCloseTo(-1 / 3);
    expect(rb.tokens).toBe(10 + 12); // the candidate on the start event plus the branch steps
  });

  it("reads an incomplete comparison as having no delta", () => {
    seq = 0;
    const events = [
      ev("a", "INIT"), ev("b", "INIT"), ev("a", "REFUTE", 1),
      ev("a", null, 2, { kind: "rollback_start", counterfactual: true, meta: { replay_id: "r" } }),
      ev("a", null, null, { kind: "rollback_end", counterfactual: true,
        meta: { replay_id: "r", status: "incomplete", credit_delta: null } }),
    ];
    const [rb] = rollbacks(events);
    expect(rb.status).toBe("incomplete");
    expect(rb.creditDelta).toBeNull();
  });

  it("falls back to start, step and end order for logs without replay ids", () => {
    seq = 0;
    const events = [
      ev("a", "INIT"), ev("b", "INIT"), ev("a", "REFUTE", 1),
      ev("a", null, 2, { kind: "rollback_start", counterfactual: true }),
      ev("a", "REVISE", 1, { kind: "rollback_step", counterfactual: true }),
      ev("a", null, null, { kind: "rollback_end", counterfactual: true }),
    ];
    const [rb] = rollbacks(events);
    expect(rb.replayId).toBeNull();
    expect(rb.legacy).toBe(true);
    expect(rb.branches.original).toEqual([]);
    expect(rb.branches.replacement.map((e) => e.tag)).toEqual(["REVISE"]);
    expect(rb.status).toBe("completed");
  });
});
