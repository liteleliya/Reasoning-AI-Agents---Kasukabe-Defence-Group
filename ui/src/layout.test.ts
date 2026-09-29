import { describe, expect, it } from "vitest";
import { layout, rollbacks, upTo } from "./layout";
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
