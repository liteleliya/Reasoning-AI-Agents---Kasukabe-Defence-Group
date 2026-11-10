import type { CaseBrief } from "./types";

/** Only authored cases have a public record; dataset items and fixtures fall back to their id. */
export function hasBrief(caseId: string): boolean {
  return caseId.startsWith("case:");
}

export function briefUrl(caseId: string): string {
  return `/api/case?${new URLSearchParams({ case_id: caseId })}`;
}

/** What the agents were asked to state, one line each, from the public vocabulary. */
export function answerShape(brief: CaseBrief): string[] {
  return [
    `decision: ${brief.decisions.join(" | ")}`,
    ...brief.fields.map((f) =>
      f.kind === "enum" ? `${f.name}: ${f.values.join(" | ")}` : `${f.name} (${f.kind})`,
    ),
  ];
}
