import { describe, expect, it } from "vitest";
import { eventsUrl, snapshotUrl } from "./api";

describe("snapshotUrl", () => {
  it("keeps slash, pipe and hash characters inside the session_id value", () => {
    const id = "j3_prelim_hot-cf2|mscore|law/complex#2534|0";
    const url = new URL(snapshotUrl(id, 3), "http://localhost");
    expect(url.pathname).toBe("/api/snapshot");
    expect(url.searchParams.get("session_id")).toBe(id);
    expect(url.searchParams.get("at")).toBe("3");
    expect(url.hash).toBe("");
  });
});

describe("eventsUrl", () => {
  it("passes the session id as a query value", () => {
    const id = "j3_prelim_hot-cf2|mscore|law/complex#2534|0";
    const url = new URL(eventsUrl(id), "http://localhost");
    expect(url.pathname).toBe("/api/events");
    expect(url.searchParams.get("session_id")).toBe(id);
    expect(url.hash).toBe("");
  });
});
