import { describe, expect, it } from "vitest";
import { layout, upTo } from "./layout";
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
