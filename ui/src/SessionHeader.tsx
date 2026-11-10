import { useState } from "react";
import type { StreamStatus } from "./api";
import { Legend } from "./Legend";
import { conditionLabel, outcomeOf } from "./sessions";
import type { SessionInfo } from "./types";

interface Props {
  sessionId: string;
  info: SessionInfo | undefined;
  tabs: SessionInfo[];
  status: StreamStatus;
  events: number;
  stopDetail: string | null;
  onSelect: (sessionId: string) => void;
}

const STATUS_TEXT: Record<StreamStatus, string> = {
  idle: "",
  loading: "Loading",
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting",
  archived: "Recorded",
  error: "Unavailable",
};

/** Title, the same case under each condition as tabs, stream status and the raw id on request. */
export function SessionHeader({ sessionId, info, tabs, status, events, stopDetail, onSelect }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error(`could not copy the session id: ${err}`);
    }
  };

  return (
    <header className="session-header">
      <div className="title-row">
        <h2>{info?.label ?? sessionId}</h2>
        <span className={`status ${status}`} role="status">
          <span className="dot" aria-hidden="true" />
          {STATUS_TEXT[status]}
        </span>
        <span className="muted">
          {events} events{stopDetail ? ` · stopped on ${stopDetail}` : ""}
        </span>
        <Legend />
      </div>
      {tabs.length > 1 && (
        <div className="tabs" role="tablist" aria-label="Conditions for this case and seed">
          {tabs.map((t) => (
            <button
              key={t.session_id}
              role="tab"
              aria-selected={t.session_id === sessionId}
              className={t.session_id === sessionId ? "tab active" : "tab"}
              onClick={() => onSelect(t.session_id)}
            >
              {conditionLabel(t)}
              <span className={`badge ${outcomeOf(t)}`}>{outcomeOf(t)}</span>
            </button>
          ))}
        </div>
      )}
      <details className="raw-id">
        <summary>Session details</summary>
        <code>{sessionId}</code>
        <button onClick={copy}>{copied ? "Copied" : "Copy id"}</button>
        {info?.source && <span className="muted"> · source {info.source}</span>}
      </details>
    </header>
  );
}
