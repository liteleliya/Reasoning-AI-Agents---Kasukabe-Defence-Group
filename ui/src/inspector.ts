import { isRealMessage } from "./layout";
import type { EventRecord } from "./types";

export interface EventDetails {
  replyTarget: EventRecord | undefined; // the earlier event this one answers, if it is in the log
  tokenCost: number;
  real: boolean; // false for replay events, which never happened on the board
}

export function describeEvent(e: EventRecord, events: EventRecord[]): EventDetails {
  return {
    replyTarget:
      e.reply_to === null || e.kind !== "message"
        ? undefined
        : events.find((x) => x.seq === e.reply_to),
    tokenCost: e.tokens.in + e.tokens.out,
    real: !e.counterfactual,
  };
}

/** The first real REFUTE or REJECT; replay steps are not part of the debate. */
export function firstChallenge(events: EventRecord[]): number | null {
  const hit = events.find((e) => isRealMessage(e) && (e.tag === "REFUTE" || e.tag === "REJECT"));
  return hit ? hit.seq : null;
}

export function terminationSeq(events: EventRecord[]): number | null {
  const term = events.find((e) => e.kind === "message" && e.tag === "TERM");
  return term ? term.seq : null;
}

export interface Row {
  text: string;
  indent: boolean; // replay events sit under the debate
  replay: boolean;
}

/** One line for the event list: who did what, and whether it was real or a replay. */
export function eventRow(e: EventRecord): Row {
  switch (e.kind) {
    case "rollback_start":
      return { text: `replay starts (${e.author})`, indent: true, replay: true };
    case "rollback_end":
      return { text: "replay ends", indent: true, replay: true };
    case "rollback_step": {
      const branch = typeof e.meta.branch === "string" ? `${e.meta.branch} · ` : "";
      return { text: `${branch}${e.author} ${e.tag} · ${e.prediction}`, indent: true, replay: true };
    }
    default:
      if (e.tag === "TERM") return { text: `TERM · ${e.explanation}`, indent: false, replay: false };
      return {
        text: `${e.author} ${e.tag}${e.reply_to === null ? "" : ` → ${e.reply_to}`} · ${e.prediction}`,
        indent: false,
        replay: false,
      };
  }
}
