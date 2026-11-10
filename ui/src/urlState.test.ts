import { describe, expect, it } from "vitest";
import { buildSearch, parseSearch } from "./urlState";

const ID = "j3_prelim_hot-cf2|mscore|Data2/Law/Single-choice/complex#2534|0";

describe("url state", () => {
  it("round-trips an id with slash, pipe and hash characters", () => {
    const search = buildSearch(ID, 3);
    expect(search.startsWith("?")).toBe(true);
    expect(search).not.toContain("#");
    expect(parseSearch(search)).toEqual({ session: ID, seq: 3 });
  });

  it("leaves the sequence out when following the live end", () => {
    expect(buildSearch(ID, null)).not.toContain("seq");
    expect(parseSearch(buildSearch(ID, null))).toEqual({ session: ID, seq: null });
  });

  it("reads an empty or odd query as nothing selected", () => {
    expect(parseSearch("")).toEqual({ session: null, seq: null });
    expect(parseSearch("?session=")).toEqual({ session: null, seq: null });
    expect(parseSearch("?session=a&seq=abc").seq).toBeNull();
    expect(parseSearch("?session=a&seq=-2").seq).toBeNull();
    expect(parseSearch("?session=a&seq=1.5").seq).toBeNull();
  });

  it("builds an empty query when nothing is selected", () => {
    expect(buildSearch(null, null)).toBe("");
  });
});
