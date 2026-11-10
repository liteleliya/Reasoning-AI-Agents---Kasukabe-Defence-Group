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
  term: { event: EventRecord; col: number } | null; // where the session was stopped
}

export const isRealMessage = (e: EventRecord) =>
  e.kind === "message" && !e.counterfactual && e.author !== "system";

/** Every agent that speaks anywhere in the log, sorted: the lanes of the whole session. */
export function rosterOf(events: EventRecord[]): string[] {
  return [...new Set(events.filter(isRealMessage).map((e) => e.author))].sort();
}

/**
 * Swimlane layout: agents as rows, real messages as columns, reply_to as edges. Pass the
 * session's full `roster` so lanes do not appear or move while the scrubber is partway through.
 */
export function layout(events: EventRecord[], roster: string[] = []): Layout {
  const messages = events.filter(isRealMessage);
  const lanes = [...new Set([...roster, ...messages.map((e) => e.author)])].sort();
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
  const termEvent = events.find((e) => e.kind === "message" && e.tag === "TERM");
  const term = termEvent
    ? { event: termEvent, col: messages.filter((m) => m.seq < termEvent.seq).length - 0.5 }
    : null;
  return { lanes, nodes, edges, rollbacks, term };
}

/** Events up to and including `seq` (the scrubber's view of the log). */
export const upTo = (events: EventRecord[], seq: number) => events.filter((e) => e.seq <= seq);

export interface Rollback {
  start: EventRecord;
  replayId: string | null; // null for logs written before replay ids existed
  target: EventRecord | undefined; // the real message being replayed differently
  challengerSeq: number | null; // the real message that challenged the target
  /** Replayed messages by branch. Older logs have one replayed path, kept as the replacement. */
  branches: { original: EventRecord[]; replacement: EventRecord[] };
  steps: EventRecord[]; // every replayed message, in log order
  end: EventRecord | undefined; // missing while the replay is still running
  status: string; // completed, incomplete or candidate_failed; open until the end event arrives
  legacy: boolean; // true when the log has no replay ids or branch labels
  real: EventRecord[]; // what really followed the target, same length as steps
  creditDelta: number | null; // null while open or when the comparison is incomplete
  tokens: number; // the candidate on the start event plus every replayed step
}

const text = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

/**
 * Group rollback_start/step/end events by replay id (older logs: by their order) and pair them
 * with the real continuation (C3). Steps are kept per branch, in fork-local order.
 */
export function rollbacks(events: EventRecord[]): Rollback[] {
  const out: Rollback[] = [];
  const byId = new Map<string, Rollback>();
  let current: Rollback | null = null;
  const bySeq = new Map(events.map((e) => [e.seq, e]));
  const owner = (e: EventRecord) => {
    const id = text(e.meta.replay_id);
    return (id && byId.get(id)) || current;
  };
  for (const e of events) {
    if (e.kind === "rollback_start") {
      const replayId = text(e.meta.replay_id);
      current = {
        start: e,
        replayId,
        target: e.reply_to === null ? undefined : bySeq.get(e.reply_to),
        challengerSeq: num(e.meta.challenger_seq),
        branches: { original: [], replacement: [] },
        steps: [],
        end: undefined,
        status: "open",
        legacy: replayId === null,
        real: [],
        creditDelta: null,
        tokens: e.tokens.in + e.tokens.out,
      };
      out.push(current);
      if (replayId) byId.set(replayId, current);
    } else if (e.kind === "rollback_step") {
      const rb = owner(e);
      if (!rb) continue;
      rb.steps.push(e);
      rb.tokens += e.tokens.in + e.tokens.out;
      (e.meta.branch === "original" ? rb.branches.original : rb.branches.replacement).push(e);
    } else if (e.kind === "rollback_end") {
      const rb = owner(e);
      if (!rb) continue;
      rb.end = e;
      rb.status = text(e.meta.status) ?? "completed";
      rb.creditDelta = num(e.meta.credit_delta);
      if (rb === current) current = null;
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
