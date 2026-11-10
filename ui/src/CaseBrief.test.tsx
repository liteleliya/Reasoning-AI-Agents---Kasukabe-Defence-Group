import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CaseBrief } from "./CaseBrief";
import { answerShape, briefUrl, hasBrief } from "./taskBrief";
import type { CaseBrief as Brief } from "./types";

const brief: Brief = {
  id: "restore-p1", split: "dev", version: 1, domain: "operations",
  question: "How should service be restored under policy P1?",
  context: "Policy P1 allows up to four minutes of downtime.",
  evidence: [
    { id: "E1", text: "Plan A needs six minutes." },
    { id: "E2", text: "Plan B needs two minutes." },
  ],
  decisions: ["A", "B"],
  fields: [
    { name: "downtime", kind: "duration", unit: "s", values: [], decisive: true, description: "" },
    { name: "lag_check", kind: "enum", unit: "", values: ["before", "none"], decisive: true, description: "" },
  ],
};

describe("case brief data", () => {
  it("only authored case ids have a public record", () => {
    expect(hasBrief("case:restore-p1")).toBe(true);
    expect(hasBrief("Data2/Law/Single-choice/complex#2534")).toBe(false);
    expect(hasBrief("toy-recovery-xy")).toBe(false);
  });

  it("keeps the id value inside the query string", () => {
    expect(briefUrl("case:restore-p1")).toBe("/api/case?case_id=case%3Arestore-p1");
  });

  it("describes the answer shape from the public vocabulary", () => {
    expect(answerShape(brief)).toEqual([
      "decision: A | B",
      "downtime (duration)",
      "lag_check: before | none",
    ]);
  });
});

describe("CaseBrief", () => {
  const html = (status: Parameters<typeof CaseBrief>[0]["status"], b: Brief | null = brief) =>
    renderToStaticMarkup(<CaseBrief caseId="case:restore-p1" brief={b} status={status} />);

  it("shows the question, context and each labelled evidence excerpt", () => {
    const out = html("ready");
    expect(out).toContain("How should service be restored under policy P1?");
    expect(out).toContain("four minutes of downtime");
    expect(out).toContain("<strong>E1</strong>");
    expect(out).toContain("Plan B needs two minutes.");
    expect(out).toContain("decision: A | B");
  });

  it("is collapsed until opened", () => {
    expect(html("ready")).toMatch(/<details class="case-brief"(?! open)/);
  });

  it("falls back to the stored item id when no public record exists", () => {
    const out = html("unavailable", null);
    expect(out).toContain("No public prompt is stored for this archive");
    expect(out).toContain("case:restore-p1");
  });

  it("says when it is loading or failed", () => {
    expect(html("loading", null)).toContain("Loading task");
    expect(html("error", null)).toContain("Could not load the task");
  });

  it("renders nothing for an empty case id", () => {
    expect(renderToStaticMarkup(<CaseBrief caseId={null} brief={null} status="idle" />)).toBe("");
  });
});
