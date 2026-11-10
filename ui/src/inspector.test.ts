import { describe, expect, it } from "vitest";
import { describeEvent, eventRow, firstChallenge, terminationSeq } from "./inspector";
import type { EventRecord } from "./types";

let seq = 0;
const ev = (author: string, tag: EventRecord["tag"], reply_to: number | null = null,
  extra: Partial<EventRecord> = {}): EventRecord => ({
  seq: seq++, session_id: "s", author, kind: "message", tag, reply_to, prediction: "X",
  explanation: "because", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {}, ...extra,
});

seq = 0;
const log = [
  ev("a", "INIT"),
  ev("b", "INIT"),
  ev("a", "RATIFY", 1),
  ev("b", "REFUTE", 2, { tokens: { in: 40, out: 12 } }),
  ev("a", null, 3, { kind: "rollback_start", counterfactual: true }),
  ev("b", "REJECT", 3, { kind: "rollback_step", counterfactual: true, meta: { branch: "original" } }),
  ev("a", null, null, { kind: "rollback_end", counterfactual: true }),
  ev("system", "TERM", null, { explanation: "impasse" }),
];

describe("describeEvent", () => {
  it("finds the reply target and adds up the token cost", () => {
    const d = describeEvent(log[3], log);
    expect(d.replyTarget?.seq).toBe(2);
    expect(d.tokenCost).toBe(52);
    expect(d.real).toBe(true);
  });

  it("has no reply target for an opening message and marks sandbox events as not real", () => {
    expect(describeEvent(log[0], log).replyTarget).toBeUndefined();
    expect(describeEvent(log[5], log).real).toBe(false);
    expect(describeEvent(log[7], log).real).toBe(true); // TERM is a real, system-written event
  });

  it("does not link a reply target that is not in the log yet", () => {
    expect(describeEvent(log[3], log.slice(0, 2)).replyTarget).toBeUndefined();
  });
});

describe("jumps", () => {
  it("finds the first real REFUTE or REJECT and ignores sandbox ones", () => {
    expect(firstChallenge(log)).toBe(3);
    expect(firstChallenge(log.slice(0, 3))).toBeNull();
    expect(firstChallenge(log.slice(4, 6))).toBeNull(); // a REJECT inside a replay does not count
  });

  it("finds the TERM event", () => {
    expect(terminationSeq(log)).toBe(7);
    expect(terminationSeq(log.slice(0, 7))).toBeNull();
  });
});

describe("eventRow", () => {
  it("labels real messages by author, tag and reply target", () => {
    expect(eventRow(log[3])).toEqual({
      text: "b REFUTE → 2 · X", indent: false, replay: false,
    });
  });

  it("labels sandbox events as replay steps and indents them", () => {
    expect(eventRow(log[4])).toEqual({ text: "replay starts (a)", indent: true, replay: true });
    expect(eventRow(log[5])).toEqual({ text: "original · b REJECT · X", indent: true, replay: true });
    expect(eventRow(log[6])).toEqual({ text: "replay ends", indent: true, replay: true });
  });

  it("labels TERM with its reason", () => {
    expect(eventRow(log[7])).toEqual({ text: "TERM · impasse", indent: false, replay: false });
  });
});
