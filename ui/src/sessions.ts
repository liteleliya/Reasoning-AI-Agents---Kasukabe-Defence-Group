import type { SessionInfo } from "./types";

export interface Filters {
  query: string;
  outcome: string; // "" = any
  condition: string; // "" = any
}

/** How a session ended, or "live" while it is still running. */
export function outcomeOf(s: SessionInfo): string {
  return s.terminated ? (s.stop_reason ?? "terminated") : "live";
}

/** "2 of 3 enabled" when the run recorded the enabled-agent count, else the condition name. */
export function conditionLabel(s: SessionInfo): string {
  if (s.enabled_agents !== null && s.n_agents !== null) {
    return `${s.enabled_agents} of ${s.n_agents} enabled`;
  }
  return s.condition ?? "—";
}

export function filterSessions(sessions: SessionInfo[], f: Filters): SessionInfo[] {
  const q = f.query.trim().toLowerCase();
  return sessions.filter((s) => {
    if (f.outcome && outcomeOf(s) !== f.outcome) return false;
    if (f.condition && s.condition !== f.condition) return false;
    if (!q) return true;
    return [s.case_id, s.label, s.condition ?? "", s.session_id].some((text) =>
      text.toLowerCase().includes(q),
    );
  });
}

export function conditionOptions(sessions: SessionInfo[]): string[] {
  return [...new Set(sessions.map((s) => s.condition).filter((c): c is string => !!c))].sort();
}

/** The same case and seed under each condition, fewest enabled agents first; for the tabs. */
export function siblings(sessions: SessionInfo[], current: SessionInfo): SessionInfo[] {
  const same = sessions.filter((s) => s.case_id === current.case_id && s.seed === current.seed);
  if (!same.some((s) => s.session_id === current.session_id)) same.push(current);
  return same.sort(
    (a, b) =>
      (a.enabled_agents ?? 0) - (b.enabled_agents ?? 0) ||
      (a.condition ?? "").localeCompare(b.condition ?? ""),
  );
}
