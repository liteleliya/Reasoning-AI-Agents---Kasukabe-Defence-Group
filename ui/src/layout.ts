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
