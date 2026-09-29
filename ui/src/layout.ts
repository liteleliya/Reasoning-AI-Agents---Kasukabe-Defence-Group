import type { EventRecord } from "./types";

export interface Node {
  event: EventRecord;
  col: number; // position along the timeline (real messages only)
  lane: number; // one lane per agent
}

export interface Edge {
  from: Node; // the reply
  to: Node; // the message it replies to
}

export interface Layout {
  lanes: string[];
  nodes: Node[];
  edges: Edge[];
  rollbacks: { start: EventRecord; col: number }[];
}

export const isRealMessage = (e: EventRecord) =>
  e.kind === "message" && !e.counterfactual && e.author !== "system";

/** Swimlane layout: agents as rows, real messages as columns, reply_to as edges. */
export function layout(events: EventRecord[]): Layout {
  const messages = events.filter(isRealMessage);
  const lanes = [...new Set(messages.map((e) => e.author))].sort();
  const bySeq = new Map<number, Node>();
  const nodes = messages.map((event, col) => {
    const node = { event, col, lane: lanes.indexOf(event.author) };
    bySeq.set(event.seq, node);
    return node;
  });
  const edges: Edge[] = [];
  for (const node of nodes) {
    const target = node.event.reply_to === null ? undefined : bySeq.get(node.event.reply_to);
    if (target) edges.push({ from: node, to: target });
  }
  // a rollback is drawn just after the last real message before it
  const rollbacks = events
    .filter((e) => e.kind === "rollback_start")
    .map((start) => ({
      start,
      col: messages.filter((m) => m.seq < start.seq).length - 0.5,
    }));
  return { lanes, nodes, edges, rollbacks };
}

/** Events up to and including `seq` (the scrubber's view of the log). */
export const upTo = (events: EventRecord[], seq: number) => events.filter((e) => e.seq <= seq);

export interface Rollback {
  start: EventRecord;
  target: EventRecord | undefined; // the real message being replayed differently
  steps: EventRecord[]; // replayed messages (the altered one first)
  end: EventRecord | undefined; // missing while the replay is still running
  real: EventRecord[]; // what really followed the target, same length as steps
  creditDelta: number | null;
  tokens: number;
}

/** Group rollback_start/step/end events and pair them with the real continuation (C3). */
export function rollbacks(events: EventRecord[]): Rollback[] {
  const out: Rollback[] = [];
  let current: Rollback | null = null;
  const bySeq = new Map(events.map((e) => [e.seq, e]));
  for (const e of events) {
    if (e.kind === "rollback_start") {
      const target = e.reply_to === null ? undefined : bySeq.get(e.reply_to);
      current = { start: e, target, steps: [], end: undefined, real: [], creditDelta: null,
        tokens: 0 };
      out.push(current);
    } else if (current && e.kind === "rollback_step") {
      current.steps.push(e);
      current.tokens += e.tokens.in + e.tokens.out;
    } else if (current && e.kind === "rollback_end") {
      current.end = e;
      const delta = e.meta.credit_delta;
      current.creditDelta = typeof delta === "number" ? delta : null;
      current = null;
    }
  }
  for (const rb of out) {
    if (!rb.target) continue;
    const from = rb.target.seq;
    rb.real = [rb.target, ...events.filter((e) => isRealMessage(e) && e.seq > from)].slice(
      0,
      Math.max(rb.steps.length, 1),
    );
  }
  return out;
}
