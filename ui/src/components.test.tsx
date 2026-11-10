import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EventInspector } from "./EventInspector";
import { EventList } from "./EventList";
import { Graph } from "./Graph";
import { rosterOf } from "./layout";
import { SessionHeader } from "./SessionHeader";
import { StatePanel } from "./StatePanel";
import type { EventRecord, SessionInfo, Snapshot } from "./types";

let seq = 0;
const ev = (author: string, tag: EventRecord["tag"], reply_to: number | null = null,
  extra: Partial<EventRecord> = {}): EventRecord => ({
  seq: seq++, session_id: "s", author, kind: "message", tag, reply_to, prediction: "Y",
  explanation: "because", counterfactual: false, tokens: { in: 0, out: 0 }, meta: {}, ...extra,
});

seq = 0;
const log = [
  ev("A", "INIT"), ev("B", "INIT"), ev("C", "INIT"),
  ev("A", "REFUTE", 1),
  ev("A", null, 3, { kind: "rollback_start", counterfactual: true, prediction: "", explanation: "what if",
    meta: { replay_id: "s::replay-1" } }),
  ev("B", "RATIFY", null, { kind: "rollback_step", counterfactual: true,
    meta: { replay_id: "s::replay-1", branch: "replacement" } }),
  ev("A", null, null, { kind: "rollback_end", counterfactual: true,
    meta: { replay_id: "s::replay-1", status: "completed", credit_delta: -1 / 3 } }),
  ev("system", "TERM", null, { explanation: "impasse", prediction: "" }),
];
const count = (html: string, needle: string) => html.split(needle).length - 1;

describe("Graph", () => {
  const html = (cursor: number) =>
    renderToStaticMarkup(<Graph events={log} roster={rosterOf(log)} cursor={cursor} />);

  it("keeps every lane, and fades the events after the cursor instead of removing them", () => {
    const early = html(1);
    for (const agent of ["A", "B", "C"]) expect(early).toContain(`>${agent}</text>`);
    expect(count(early, 'class="node future"')).toBe(2); // events 2 and 3 are still to come
    expect(count(early, 'role="button" tabindex="0" aria-label="Event')).toBe(4);
    expect(count(html(3), 'class="node future"')).toBe(0);
  });

  it("writes each tag out and gives different tags different shapes", () => {
    const out = html(3);
    expect(out).toContain(">INIT</text>");
    expect(out).toContain(">REFUTE</text>");
    const shapes = [...out.matchAll(/<path d="([^"]+)" fill="#[0-9A-Fa-f]{6}" class="shape"/g)].map((m) => m[1]);
    expect(new Set(shapes).size).toBe(2); // INIT and REFUTE
  });

  it("marks the replay and the end of the session and names them", () => {
    const out = html(7);
    expect(out).toContain("replay of #3");
    expect(out).toContain("TERM · impasse");
    expect(out).toContain('aria-label="Event 3, A REFUTE, replies to 1"');
  });
});

describe("EventInspector", () => {
  it("shows the selected event with a link to its reply target", () => {
    const out = renderToStaticMarkup(<EventInspector events={log} cursor={3} onSelectSeq={() => {}} />);
    expect(out).toContain("Event 3");
    expect(out).toContain("#1 · B INIT");
    expect(out).toContain("REFUTE");
  });

  it("says when the selected event is a replay step and shows its facts", () => {
    const out = renderToStaticMarkup(<EventInspector events={log} cursor={6} onSelectSeq={() => {}} />);
    expect(out).toContain("replay step, not a real turn");
    expect(out).toContain("credit delta");
    expect(out).toContain("-0.333");
  });

  it("asks for a selection when the cursor is on nothing", () => {
    const out = renderToStaticMarkup(<EventInspector events={[]} cursor={0} onSelectSeq={() => {}} />);
    expect(out).toContain("Select an event");
  });
});

describe("EventList", () => {
  it("lists every event, marks the current one and sets replay steps apart", () => {
    const out = renderToStaticMarkup(<EventList events={log} cursor={3} onSelectSeq={() => {}} />);
    expect(count(out, "<button")).toBe(log.length);
    expect(count(out, 'aria-current="true"')).toBe(1);
    expect(count(out, "indent")).toBe(3); // start, step and end of the replay
    expect(out).toContain("TERM · impasse");
  });
});

const info = (extra: Partial<SessionInfo> = {}): SessionInfo => ({
  session_id: "s", seq: 7, agents: ["A", "B", "C"], terminated: true, stop_reason: "consensus",
  case_id: "c", label: "Law complex #2534", condition: "cf2", seed: 0, source: "J3",
  enabled_agents: 2, n_agents: 3, correct: null, ...extra,
});
const snap = (at: number): Snapshot => ({
  session_id: "s", seq: at, agents: ["A", "B"], predictions: { A: "X", B: "Y" }, terminated: false,
  stop_reason: null, open_rollback: null,
  tokens: { in: 1, out: 1, rollback_in: 0, rollback_out: 0, total: 2 },
  intelligibility: { label: "failed", revises: 0, pairs: [] },
});

describe("StatePanel", () => {
  it("shows the board as in progress before TERM even though the session ended in consensus", () => {
    const out = renderToStaticMarkup(<StatePanel snap={snap(3)} session={info()} termSeq={7} />);
    expect(out).toContain("in progress");
    expect(out).toContain("Board at seq 3");
    expect(out).toContain("Whole session");
    expect(out).toContain("consensus"); // the final outcome, kept apart from the live board
  });

  it("keeps the final correctness separate and says when it is unavailable", () => {
    const unknown = renderToStaticMarkup(<StatePanel snap={snap(3)} session={info()} termSeq={7} />);
    const wrong = renderToStaticMarkup(
      <StatePanel snap={snap(3)} session={info({ correct: false })} termSeq={7} />,
    );
    expect(unknown).toContain("Unavailable");
    expect(wrong).toContain(">wrong<");
  });

  it("explains itself while the snapshot loads", () => {
    const out = renderToStaticMarkup(<StatePanel snap={null} session={info()} termSeq={7} />);
    expect(out).toContain("Loading the board state");
  });
});

describe("SessionHeader", () => {
  const tabs = [info({ session_id: "s0", enabled_agents: 0 }), info()];
  const html = renderToStaticMarkup(
    <SessionHeader sessionId="s" info={info()} tabs={tabs} status="archived" events={8}
      stopDetail="consensus" onSelect={() => {}} />,
  );

  it("offers the same case under each condition as tabs", () => {
    expect(html).toContain('role="tablist"');
    expect(count(html, 'role="tab"')).toBe(2);
    expect(html).toContain("0 of 3 enabled");
  });

  it("shows the stream status and keeps the raw id behind a details row", () => {
    expect(html).toContain("Recorded");
    expect(html).toContain("<details");
    expect(html).toContain("<code>s</code>");
    expect(html).toContain("source J3");
  });
});
