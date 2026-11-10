import { answerShape } from "./taskBrief";
import type { CaseBrief as Brief } from "./types";

export type BriefStatus = "idle" | "loading" | "ready" | "unavailable" | "error";

interface Props {
  caseId: string | null;
  brief: Brief | null;
  status: BriefStatus;
}

/** The task and its labelled evidence, collapsed by default; older archives show the item id. */
export function CaseBrief({ caseId, brief, status }: Props) {
  if (!caseId) return null;
  let body;
  if (status === "ready" && brief) {
    body = (
      <>
        <p className="question">{brief.question}</p>
        {brief.context && <p>{brief.context}</p>}
        <ol className="evidence" aria-label="Evidence">
          {brief.evidence.map((e) => (
            <li key={e.id}>
              <strong>{e.id}</strong> {e.text}
            </li>
          ))}
        </ol>
        <p className="muted">Agents state:</p>
        <ul className="shape">
          {answerShape(brief).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </>
    );
  } else if (status === "loading" || status === "idle") {
    body = <p className="muted">Loading task…</p>;
  } else if (status === "error") {
    body = <p className="error" role="alert">Could not load the task.</p>;
  } else {
    body = (
      <p className="muted">
        No public prompt is stored for this archive. Item <code>{caseId}</code>.
      </p>
    );
  }
  return (
    <details className="case-brief">
      <summary>Task and evidence</summary>
      {body}
    </details>
  );
}
