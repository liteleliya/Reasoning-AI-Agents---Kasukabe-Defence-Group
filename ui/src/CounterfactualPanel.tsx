import { useMemo } from "react";
import { rollbacks } from "./layout";
import {
  fmtDelta, fmtDistance, noReplayNote, replayView, type PairedRow, type ReplayView, type Sentence,
} from "./replay";
import { TAG_COLOURS } from "./tags";
import type { EventRecord } from "./types";

interface Props {
  events: EventRecord[]; // only what the cursor has reached, so later outcomes stay hidden
  cursor: number;
  onSelectSeq: (seq: number) => void;
}

const seqLabel = (seq: number) => `#${seq}`;

function Chip({ e, changed }: { e: EventRecord; changed?: boolean }) {
  const chip = (
    <span className="chip" style={{ background: TAG_COLOURS[e.tag ?? "INIT"] }}>{e.tag}</span>
  );
  return changed ? <mark>{chip}</mark> : chip;
}

function Explanation({ parts }: { parts: Sentence[] }) {
  return (
    <p className="why">
      {parts.map((s, i) => (
        <span key={i}>{s.changed ? <mark>{s.text}</mark> : s.text} </span>
      ))}
    </p>
  );
}

function Tested({ v }: { v: ReplayView }) {
  const { original, replacement } = v.tested;
  if (!original && !replacement) return null;
  const sides = [
    { title: "Original reply", e: original, parts: v.sentences.original },
    { title: "Replacement", e: replacement, parts: v.sentences.replacement },
  ];
  return (
    <div className="cf-tested">
      {sides.map(({ title, e, parts }) => (
        <div key={title}>
          <h4>{title}</h4>
          {e ? (
            <>
              <Chip e={e} changed={v.changed.includes("tag")} />{" "}
              <span className="what">
                {v.changed.includes("prediction") ? <mark>{e.prediction}</mark> : e.prediction}
              </span>
              <Explanation parts={parts} />
            </>
          ) : (
            <p className="muted">not available</p>
          )}
        </div>
      ))}
    </div>
  );
}

function Cell({ e, cursor, onSelectSeq }: { e?: EventRecord; cursor: number; onSelectSeq: (n: number) => void }) {
  if (!e) return <span className="cell empty muted">not reached</span>;
  const fork = typeof e.meta.fork_seq === "number" ? e.meta.fork_seq : null;
  return (
    <button
      className="cell"
      aria-current={e.seq === cursor ? "true" : undefined}
      onClick={() => onSelectSeq(e.seq)}
    >
      <Chip e={e} /> <span className="what">{e.prediction}</span>
      {fork !== null && <span className="fork muted">{`fork ${fork}`}</span>}
      <span className="why">{e.explanation}</span>
    </button>
  );
}

function Rows({ rows, cursor, onSelectSeq }: { rows: PairedRow[]; cursor: number; onSelectSeq: (n: number) => void }) {
  return (
    <ol className="cf-rows">
      {rows.map((r) => (
        <li key={r.key} className={r.differs ? "cf-row differs" : "cf-row"}>
          <span className="who">{r.author}</span>
          <Cell e={r.original} cursor={cursor} onSelectSeq={onSelectSeq} />
          <Cell e={r.replacement} cursor={cursor} onSelectSeq={onSelectSeq} />
        </li>
      ))}
    </ol>
  );
}

function Adoption({ v, onSelectSeq }: { v: ReplayView; onSelectSeq: (n: number) => void }) {
  const a = v.adoption;
  if (a.kind === "adopted") {
    return (
      <p className="adoption">
        <strong>{`Adopted as ${seqLabel(a.event.seq)}`}</strong>{" "}
        <button className="link" onClick={() => onSelectSeq(a.event.seq)}>
          {`${a.event.author} ${a.event.tag} → ${a.event.reply_to}`}
        </button>
        {" — the board changes only at this reply"}
      </p>
    );
  }
  if (a.kind === "not_adopted") return <p className="adoption">{`Not adopted: ${a.reason}`}</p>;
  return <p className="adoption muted">Adoption: not yet known at this point.</p>;
}

function Replay({ v, rb, cursor, onSelectSeq }: Props2) {
  const complete = v.delta !== null;
  const [from, to] = v.legacy
    ? [v.distances.recorded, v.distances.replacement]
    : [v.distances.original, v.distances.replacement];
  return (
    <article className={`cf-card ${v.verdict.kind}`} aria-label={`Replay of message ${rb.start.reply_to}`}>
      <header>
        <strong>{`${rb.start.author} replays`}</strong>
        {v.target && (
          <button className="link" onClick={() => onSelectSeq(v.target!.seq)}>{seqLabel(v.target.seq)}</button>
        )}
        {v.challengerSeq !== null && (
          <>
            <span className="muted">challenged by</span>
            <button className="link" onClick={() => onSelectSeq(v.challengerSeq!)}>
              {seqLabel(v.challengerSeq)}
            </button>
          </>
        )}
        <span className={`verdict-chip ${v.verdict.kind}`}>{v.status}</span>
        {v.replayId && <span className="muted replay-id">{v.replayId}</span>}
      </header>
      <Tested v={v} />
      {v.rows.length > 0 && (
        <>
          <div className="cf-heads">
            <span />
            <h4>{v.baselineLabel}</h4>
            <h4>Replacement continuation</h4>
          </div>
          <Rows rows={v.rows} cursor={cursor} onSelectSeq={onSelectSeq} />
        </>
      )}
      <dl className="cf-summary">
        <dt>Disagreement</dt>
        <dd>{`${fmtDistance(complete ? from : null)} → ${fmtDistance(complete ? to : null)}`}</dd>
        <dt>Change</dt>
        <dd className={v.delta !== null && v.delta < 0 ? "delta good" : "delta"}>{fmtDelta(v.delta)}</dd>
        <dt>Tokens</dt>
        <dd>
          {`${v.tokens.total.toLocaleString()} total (candidate ${v.tokens.candidate} · original ${v.tokens.original} · replacement ${v.tokens.replacement})`}
        </dd>
        {!v.legacy && (
          <>
            <dt>Recorded log</dt>
            <dd>{`${fmtDistance(v.distances.recorded)} (reference only, from the recorded log)`}</dd>
          </>
        )}
      </dl>
      <p className={`verdict ${v.verdict.kind}`}>{v.verdict.text}</p>
      <p className="muted caption">
        Disagreement is the share of agents outside the largest group; lower disagreement means closer
        agreement, in the sandbox only. The real board does not change.
      </p>
      <Adoption v={v} onSelectSeq={onSelectSeq} />
    </article>
  );
}

interface Props2 {
  v: ReplayView;
  rb: ReturnType<typeof rollbacks>[number];
  cursor: number;
  onSelectSeq: (n: number) => void;
}

/** Each replay the cursor has reached: the two variants, both simulated continuations, the result. */
export function CounterfactualPanel({ events, cursor, onSelectSeq }: Props) {
  const groups = useMemo(() => rollbacks(events), [events]);
  return (
    <section className="cf">
      <h3>Counterfactual replays</h3>
      {groups.length === 0 && <p className="muted">{noReplayNote(events)}</p>}
      {groups.map((rb) => (
        <Replay key={rb.start.seq} v={replayView(rb, events)} rb={rb} cursor={cursor} onSelectSeq={onSelectSeq} />
      ))}
    </section>
  );
}
