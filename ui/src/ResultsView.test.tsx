import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ResultsView } from "./ResultsView";
import j3 from "./testing/j3-results.json";
import type { RunSummary } from "./types";

const summary = j3 as RunSummary;
const show = (props: Partial<Parameters<typeof ResultsView>[0]> = {}) =>
  renderToStaticMarkup(
    <ResultsView summary={summary} status="ready" error={null} onOpen={() => {}} {...props} />,
  );
const count = (html: string, needle: string) => html.split(needle).length - 1;

describe("the J3 results", () => {
  const html = show();

  it("labels the run as a historical pilot", () => {
    expect(html).toContain("J3");
    expect(html).toContain("qwen2.5:7b-instruct");
    expect(html).toContain("Historical pilot");
    expect(html).toContain("120 trials");
    expect(html).toContain("4 conditions");
  });

  it("reports 117 of 120 consensus, 93 correct and no replays", () => {
    expect(html).toContain("117 of 120 trials reached consensus");
    expect(html).toContain("93 of those were correct");
    expect(html).toContain("0 replays logged");
  });

  it("keeps the 0 to 3 enabled conditions in order, with each count in its own column", () => {
    const labels = [...html.matchAll(/(\d) of 3 enabled/g)].map((m) => m[1]);
    expect(labels.slice(0, 4)).toEqual(["0", "1", "2", "3"]);
    for (const header of ["Consensus", "Correct", "Wrong", "No verdict", "Eligible"]) {
      expect(html).toContain(`>${header}</th>`);
    }
    expect(html).toContain("<td>29</td>");
    expect(html).toContain("<td>30</td>");
    expect(html).toContain("<td>24</td>");
    expect(html).toContain("Median tokens per trial (all model calls)");
    expect(html).toContain("3,122"); // 3121.5, rounded for display only
  });

  it("says unavailable for the eligible counts the export did not record", () => {
    expect(count(html, "Unavailable")).toBeGreaterThanOrEqual(4 + 5);
  });

  it("shows which recovery stages are known and which are not", () => {
    expect(html).toContain("Replays logged on the board");
    expect(html).toContain("did not export the recovery stages");
  });

  it("offers examples that open their session", () => {
    expect(summary.examples.length).toBeGreaterThan(0);
    expect(count(html, 'class="example"')).toBe(summary.examples.length);
    expect(html).toContain(summary.examples[0].title);
    expect(html).toContain(summary.examples[0].label);
  });
});

describe("other states", () => {
  it("says it is loading", () => {
    expect(show({ summary: null, status: "loading" })).toContain("Loading results");
  });

  it("explains how to get results when the server has none", () => {
    const html = show({ summary: null, status: "unavailable" });
    expect(html).toContain("No results for this run");
    expect(html).toContain("--metrics");
  });

  it("shows an error", () => {
    expect(show({ summary: null, status: "error", error: "500 /api/results" })).toContain("500 /api/results");
  });

  it("does not guess the kind of a run that did not say", () => {
    const html = show({ summary: { ...summary, run: { ...summary.run, kind: null } } });
    expect(html).toContain("Source not stated");
    expect(html).not.toContain("Historical pilot");
  });

  it("counts recovery stages and links the recovered ones to a trace", () => {
    const recovered: RunSummary = {
      ...summary,
      recovery: [
        { stage: "recorded", label: "Replays logged on the board", count: 4 },
        { stage: "eligible", label: "Eligible checkpoints", count: 10 },
        { stage: "recovered", label: "Correct recovery", count: 2 },
      ],
      examples: [
        { kind: "recovery", title: "Recovered after a replay", session_id: "s", case_id: "c",
          label: "Law #1", condition: "replay", outcome: "consensus" },
      ],
    };
    const html = show({ summary: recovered });
    expect(html).not.toContain("did not export the recovery stages");
    expect(html).toContain("Open a trace");
  });
});
