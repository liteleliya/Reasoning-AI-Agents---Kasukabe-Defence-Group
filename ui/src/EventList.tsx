import { useEffect, useRef } from "react";
import { eventRow } from "./inspector";
import { TAG_COLOURS } from "./tags";
import type { EventRecord } from "./types";

interface Props {
  events: EventRecord[];
  cursor: number;
  onSelectSeq: (seq: number) => void;
}

/** Every event as a button: the keyboard and screen-reader way to do what clicking a node does. */
export function EventList({ events, cursor, onSelectSeq }: Props) {
  const active = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    active.current?.scrollIntoView?.({ block: "nearest" });
  }, [cursor]);

  return (
    <section className="event-list" aria-label="Events">
      <h3>Events</h3>
      <ol>
        {events.map((e) => {
          const row = eventRow(e);
          const classes = [row.indent && "indent", e.seq > cursor && "future"].filter(Boolean).join(" ");
          return (
            <li key={e.seq} className={classes}>
              <button
                ref={e.seq === cursor ? active : undefined}
                className={e.seq === cursor ? "active" : ""}
                aria-current={e.seq === cursor ? "true" : undefined}
                onClick={() => onSelectSeq(e.seq)}
              >
                <span className="seq">{e.seq}</span>
                {e.tag && (
                  <span className="chip" style={{ background: TAG_COLOURS[e.tag] }}>{e.tag}</span>
                )}
                <span className={row.replay ? "row-text replay" : "row-text"}>{row.text}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
