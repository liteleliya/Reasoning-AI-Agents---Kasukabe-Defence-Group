import { describe, expect, it } from "vitest";
import { accept, isCurrentSnapshot, nextSeq } from "./stream";
import type { EventRecord, Snapshot } from "./types";

const ev = (seq: number): EventRecord => ({
  seq, session_id: "s", author: "a", kind: "message", tag: "INIT", reply_to: null,
  prediction: "p", explanation: "e", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {},
});
const empty = { events: [] as EventRecord[], pending: [] as EventRecord[] };
const seqs = (events: EventRecord[]) => events.map((e) => e.seq);

describe("accept", () => {
  it("appends contiguous events", () => {
    const r = accept(empty, [ev(0), ev(1), ev(2)]);
    expect(seqs(r.events)).toEqual([0, 1, 2]);
    expect(r.gap).toBeNull();
    expect(nextSeq(r)).toBe(3);
  });

  it("drops duplicates, such as a backlog replayed after a reconnect", () => {
    const first = accept(empty, [ev(0), ev(1)]);
    const again = accept(first, [ev(1), ev(2), ev(0)]);
    expect(seqs(again.events)).toEqual([0, 1, 2]);
  });

  it("holds events after a gap and reports the first missing seq", () => {
    const r = accept(accept(empty, [ev(0)]), [ev(3), ev(2)]);
    expect(seqs(r.events)).toEqual([0]);
    expect(seqs(r.pending)).toEqual([2, 3]);
    expect(r.gap).toBe(1);
    expect(nextSeq(r)).toBe(1); // a reconnect resumes at the gap, not after the held events
  });

  it("releases held events once the gap is backfilled", () => {
    const held = accept(accept(empty, [ev(0)]), [ev(3), ev(2)]);
    const filled = accept(held, [ev(1)]);
    expect(seqs(filled.events)).toEqual([0, 1, 2, 3]);
    expect(filled.pending).toEqual([]);
    expect(filled.gap).toBeNull();
  });

  it("does not mutate its input", () => {
    const state = accept(empty, [ev(0)]);
    accept(state, [ev(1)]);
    expect(seqs(state.events)).toEqual([0]);
  });
});

describe("isCurrentSnapshot", () => {
  const snap = { session_id: "s1", seq: 4 } as Snapshot;
  it("accepts only the snapshot of the current session and sequence", () => {
    expect(isCurrentSnapshot(snap, "s1", 4)).toBe(true);
    expect(isCurrentSnapshot(snap, "s2", 4)).toBe(false); // a late reply for the old session
    expect(isCurrentSnapshot(snap, "s1", 5)).toBe(false); // a late reply for an older cursor
  });
});
