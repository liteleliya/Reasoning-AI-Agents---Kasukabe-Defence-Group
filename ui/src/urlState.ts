/** What the address bar remembers: the selected session and, when paused, the sequence number. */
export type View = "explore" | "results";

export interface ViewUrl {
  session: string | null;
  seq: number | null;
  view: View;
}

export function parseSearch(search: string): ViewUrl {
  const params = new URLSearchParams(search);
  const seq = params.get("seq");
  return {
    session: params.get("session") || null,
    seq: seq !== null && /^\d+$/.test(seq) ? Number(seq) : null,
    view: params.get("view") === "results" ? "results" : "explore",
  };
}

/** The query string for the view; session ids go through URLSearchParams so "#" stays inside. */
export function buildSearch(session: string | null, seq: number | null, view: View = "explore"): string {
  const params = new URLSearchParams();
  if (view === "results") params.set("view", "results");
  if (session) params.set("session", session);
  if (session && seq !== null) params.set("seq", String(seq));
  const query = params.toString();
  return query ? `?${query}` : "";
}
