import { describeEvent, metaFacts } from "./inspector";
import { TAG_COLOURS } from "./tags";
import type { EventRecord } from "./types";

interface Props {
  events: EventRecord[];
  cursor: number;
  onSelectSeq: (seq: number) => void;
}

/** Everything recorded about the selected event; its reply target opens the earlier event. */
export function EventInspector({ events, cursor, onSelectSeq }: Props) {
  const e = events.find((x) => x.seq === cursor);
  if (!e) {
    return <section className="inspector muted">Select an event on the timeline or in the list.</section>;
  }
  const { replyTarget, tokenCost, real } = describeEvent(e, events);
  const facts = metaFacts(e);
  return (
    <section className={real ? "inspector" : "inspector replay"} aria-label="Selected event">
      <h3>
        Event {e.seq}
        {!real && <span className="replay-note"> · replay step, not a real turn</span>}
      </h3>
      <dl>
        <dt>Agent</dt>
        <dd>{e.author}</dd>
        <dt>Tag</dt>
        <dd>
          {e.tag ? (
            <span className="chip" style={{ background: TAG_COLOURS[e.tag] }}>{e.tag}</span>
          ) : (
            e.kind
          )}
          {e.kind !== "message" && e.tag && <span className="muted"> {e.kind}</span>}
        </dd>
        {e.reply_to !== null && (
          <>
            <dt>Replies to</dt>
            <dd>
              {replyTarget ? (
                <button className="link" onClick={() => onSelectSeq(replyTarget.seq)}>
                  #{replyTarget.seq} · {replyTarget.author} {replyTarget.tag ?? replyTarget.kind}
                </button>
              ) : (
                <span className="muted">#{e.reply_to} (not in the log yet)</span>
              )}
            </dd>
          </>
        )}
        {e.prediction && (
          <>
            <dt>Prediction</dt>
            <dd>{e.prediction}</dd>
          </>
        )}
        {e.explanation && (
          <>
            <dt>Explanation</dt>
            <dd className="explanation">{e.explanation}</dd>
          </>
        )}
        <dt>Tokens</dt>
        <dd>
          {e.tokens.in} in / {e.tokens.out} out ({tokenCost})
        </dd>
        {facts.map(([key, value]) => (
          <div key={key} className="fact">
            <dt>{key.replaceAll("_", " ")}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
