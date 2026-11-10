import { describe, expect, it } from "vitest";
import {
  conditionLabel, conditionOptions, filterSessions, outcomeOf, siblings,
} from "./sessions";
import type { SessionInfo } from "./types";

const LAW = "Data2/Law/Single-choice/complex#2534";
const s = (id: string, extra: Partial<SessionInfo> = {}): SessionInfo => ({
  session_id: id, seq: 5, agents: ["a", "b"], terminated: true, stop_reason: "consensus",
  case_id: id, label: id, condition: null, seed: null, source: "", enabled_agents: null,
  n_agents: null, correct: null, ...extra,
});
const j3 = (n: number, reason: string | null = "impasse", seed = 0) =>
  s(`cf${n}|mscore|${LAW}|${seed}`, {
    case_id: LAW, label: "Law complex #2534", condition: `j3-cf${n}`, seed,
    enabled_agents: n, n_agents: 3, stop_reason: reason, terminated: reason !== null,
  });

describe("outcomeOf", () => {
  it("is live until the session terminates", () => {
    expect(outcomeOf(j3(1, null))).toBe("live");
    expect(outcomeOf(j3(1, "consensus"))).toBe("consensus");
    expect(outcomeOf(s("x", { terminated: true, stop_reason: null }))).toBe("terminated");
  });
});

describe("filterSessions", () => {
  const all = [j3(0), j3(1, "consensus"), j3(2), s("toy-on", { label: "toy", condition: "on" })];

  it("searches the case id, the display label, the condition and the raw id", () => {
    const ids = (q: string) => filterSessions(all, { query: q, outcome: "", condition: "" }).length;
    expect(ids("2534")).toBe(3); // case id
    expect(ids("law complex")).toBe(3); // display label, any case
    expect(ids("j3-cf1")).toBe(1); // condition
    expect(ids("CF2|MSCORE")).toBe(1); // raw id, ignoring case
    expect(ids("nothing like it")).toBe(0);
  });

  it("filters by outcome and by condition and combines the filters", () => {
    const f = (outcome: string, condition: string) =>
      filterSessions(all, { query: "", outcome, condition }).map((x) => x.session_id);
    expect(f("consensus", "")).toEqual([all[1].session_id, all[3].session_id]);
    expect(f("impasse", "j3-cf2")).toEqual([all[2].session_id]);
    expect(f("cap", "")).toEqual([]);
  });
});

describe("siblings", () => {
  it("lists the same case and seed across conditions, fewest replay agents first", () => {
    const list = [j3(3), j3(0), j3(1, "consensus", 1), j3(2), s("other")];
    expect(siblings(list, j3(2)).map((x) => x.enabled_agents)).toEqual([0, 2, 3]);
  });

  it("is just the session itself when nothing else matches", () => {
    const only = s("solo");
    expect(siblings([only], only)).toEqual([only]);
  });
});

describe("labels", () => {
  it("shows how many agents were enabled when the run recorded it", () => {
    expect(conditionLabel(j3(2))).toBe("2 of 3 enabled");
    expect(conditionLabel(s("x", { condition: "on" }))).toBe("on");
    expect(conditionLabel(s("x"))).toBe("—");
  });

  it("offers each distinct condition once", () => {
    expect(conditionOptions([j3(1), j3(1, "consensus", 1), j3(0)])).toEqual(["j3-cf0", "j3-cf1"]);
  });
});
