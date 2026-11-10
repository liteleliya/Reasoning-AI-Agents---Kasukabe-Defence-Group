import type { EventRecord, Snapshot } from "./types";

/** Events kept in order from seq 0, plus events that arrived ahead of a missing one. */
export interface Buffered {
  events: EventRecord[];
  pending: EventRecord[];
}

/**
 * Add `incoming` to the log: drop duplicates and hold anything after a gap until the gap is
 * filled (from the WebSocket or from a REST read), so the log never skips or repeats a seq.
 * `gap` is the first missing seq while events are being held, else null.
 */
export function accept(state: Buffered, incoming: EventRecord[]): Buffered & { gap: number | null } {
  const events = [...state.events];
  const held = new Map<number, EventRecord>();
  for (const e of [...state.pending, ...incoming]) {
    if (e.seq >= events.length) held.set(e.seq, e);
  }
  let next = held.get(events.length);
  while (next) {
    events.push(next);
    held.delete(next.seq);
    next = held.get(events.length);
  }
  const pending = [...held.values()].sort((a, b) => a.seq - b.seq);
  return { events, pending, gap: pending.length ? events.length : null };
}

/** The seq to resume from after a reconnect: one past the last contiguous event. */
export function nextSeq(state: Buffered): number {
  return state.events.length;
}

/** A snapshot may be shown only if it answers the request that is current now. */
export function isCurrentSnapshot(snap: Snapshot, sessionId: string, seq: number): boolean {
  return snap.session_id === sessionId && snap.seq === seq;
}
