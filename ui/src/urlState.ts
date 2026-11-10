/** What the address bar remembers: the selected session and, when paused, the sequence number. */
export interface ViewUrl {
  session: string | null;
  seq: number | null;
}

export function parseSearch(search: string): ViewUrl {
  const params = new URLSearchParams(search);
  const seq = params.get("seq");
  return {
    session: params.get("session") || null,
    seq: seq !== null && /^\d+$/.test(seq) ? Number(seq) : null,
  };
}

/** The query string for the view; session ids go through URLSearchParams so "#" stays inside. */
export function buildSearch(session: string | null, seq: number | null): string {
  if (!session) return "";
  const params = new URLSearchParams({ session });
  if (seq !== null) params.set("seq", String(seq));
  return `?${params}`;
}
