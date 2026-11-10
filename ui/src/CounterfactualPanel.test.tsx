import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CounterfactualPanel } from "./CounterfactualPanel";
import { upTo } from "./layout";
import { adopted, ev, recovered, resetSeq, term } from "./testing/recoveredLog";
import type { EventRecord } from "./types";

const full = () => [...recovered(), adopted(), term({ recovery: { replay_id: "s::replay-1", outcome: "reply_accepted" } })];
const panel = (events: EventRecord[], cursor = events[events.length - 1].seq) =>
  renderToStaticMarkup(
    <CounterfactualPanel events={upTo(events, cursor)} cursor={cursor} onSelectSeq={() => {}} />,
  );
const count = (html: string, needle: string) => html.split(needle).length - 1;

describe("a completed replay", () => {
  const html = panel(full());

  it("names the replayed message and its challenger as links to real events", () => {
    expect(html).toContain("A replays");
    expect(html).toContain(">#6<");
    expect(html).toContain("challenged by");
    expect(html).toContain(">#7<");
  });

  it("shows the original and the replacement and marks what changed", () => {
    expect(html).toContain("Original reply");
    expect(html).toContain("Replacement");
    expect(count(html, "<mark")).toBeGreaterThanOrEqual(3); // tag, prediction and a sentence
    expect(html).toContain("The four-minute limit is binding.");
  });

  it("puts the two simulated continuations side by side, labelled, with fork numbers", () => {
    expect(html).toContain("Simulated continuation of the original reply");
    expect(html).toContain("Replacement continuation");
    expect(html).toContain("fork 7");
    expect(html).toContain("fork 8");
    expect(count(html, '<li class="cf-row')).toBe(3);
  });

  it("gives the distances, the signed delta, the costs and the caveat", () => {
    expect(html).toContain("0.33 → 0.00");
    expect(html).toContain("−0.33");
    expect(html).toContain("lower disagreement means closer agreement");
    expect(html).toContain("The replacement lowered disagreement in the sandbox.");
    expect(html).toContain("54"); // candidate plus both branches
    expect(html).toContain("recorded log");
  });

  it("links to the adopted real reply and says the board moves only there", () => {
    expect(html).toContain("Adopted as #17");
    expect(html).toContain("the board changes only at this reply");
  });
});

describe("while scrubbing", () => {
  it("hides the adoption before its event and shows it at that event", () => {
    const events = full();
    expect(panel(events, 16)).toContain("not yet known");
    expect(panel(events, 16)).not.toContain("Adopted as");
    expect(panel(events, 17)).toContain("Adopted as #17");
  });

  it("renders an open replay with the steps so far and no delta", () => {
    const html = panel(recovered(), 13);
    expect(html).toContain("Replaying");
    expect(html).toContain("— → —");
    expect(html).not.toContain("−0.33");
    expect(count(html, '<li class="cf-row')).toBe(3);
  });

  it("marks the row the cursor is on", () => {
    expect(count(panel(full(), 14), 'aria-current="true"')).toBe(1);
    expect(count(panel(full(), 5), 'aria-current="true"')).toBe(0);
  });
});

describe("other outcomes", () => {
  it("shows an incomplete comparison with its reason and no delta", () => {
    const html = panel(
      recovered({ status: "incomplete", reason: "C: passed", credit_delta: null,
        distance_original: null, distance_replacement: null }),
    );
    expect(html).toContain("Comparison incomplete: C: passed");
    expect(html).toContain("— → —");
  });

  it("says nothing was adopted and why", () => {
    const events = [...recovered(), term({ recovery: { replay_id: "s::replay-1", outcome: "stale_target" } }, "impasse")];
    expect(panel(events)).toContain("Not adopted: no live message was left to answer");
  });

  it("labels an older trace's baseline as the recorded continuation", () => {
    resetSeq();
    const log = [
      ev("a", "INIT", null, "x"), ev("b", "INIT", null, "y"), ev("a", "REFUTE", 1, "x"),
      ev("b", "REFUTE", 2, "y"),
      ev("a", null, 2, "", { kind: "rollback_start", counterfactual: true }),
      ev("a", "REVISE", null, "y", { kind: "rollback_step", counterfactual: true }),
      ev("a", null, null, "", { kind: "rollback_end", counterfactual: true,
        meta: { credit_delta: -0.5, distance_real: 0.5, distance_replay: 0 } }),
    ];
    const html = panel(log);
    expect(html).toContain("Recorded continuation");
    expect(html).toContain("0.50 → 0.00");
  });
});

describe("no replay", () => {
  it("waits, then says the reason is unavailable for an archive without diagnostics", () => {
    resetSeq();
    const log = [ev("a", "INIT"), ev("b", "INIT")];
    expect(panel(log)).toContain("No replay has been recorded yet.");
    const ended = [...log, term({}, "impasse")];
    expect(panel(ended)).toContain("Reason unavailable");
  });
});
