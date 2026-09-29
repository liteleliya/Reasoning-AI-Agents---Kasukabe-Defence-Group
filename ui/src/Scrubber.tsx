import { useEffect, useState } from "react";
import type { EventRecord } from "./types";

interface Props {
  events: EventRecord[];
  cursor: number; // seq currently shown
  live: boolean; // following new events
  onChange: (seq: number, live: boolean) => void;
}

/** History scrubber (C4): pick any seq; the board is rebuilt from the log up to it. */
export function Scrubber({ events, cursor, live, onChange }: Props) {
  const last = events.length ? events[events.length - 1].seq : 0;
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    if (cursor >= last) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => onChange(cursor + 1, false), 450);
    return () => clearTimeout(id);
  }, [playing, cursor, last, onChange]);

  const current = events.find((e) => e.seq === cursor);
  const disabled = !events.length;

  return (
    <div className="scrubber">
      <button onClick={() => onChange(Math.max(0, cursor - 1), false)} disabled={disabled}
        aria-label="Previous event">◀</button>
      <button
        onClick={() => {
          if (cursor >= last) onChange(0, false);
          setPlaying((p) => !p);
        }}
        disabled={disabled}
      >
        {playing ? "Pause" : "Replay"}
      </button>
      <button onClick={() => onChange(Math.min(last, cursor + 1), false)} disabled={disabled}
        aria-label="Next event">▶</button>
      <input
        type="range"
        min={0}
        max={last}
        value={cursor}
        disabled={disabled}
        onChange={(e) => {
          setPlaying(false);
          const seq = Number(e.target.value);
          onChange(seq, seq === last);
        }}
        aria-label="Event sequence number"
      />
      <span className="seq">
        seq {cursor} / {last}
        {current && ` · ${current.author} ${current.tag ?? current.kind}`}
      </span>
      <label className="follow">
        <input type="checkbox" checked={live} onChange={(e) => onChange(last, e.target.checked)} />
        follow live
      </label>
    </div>
  );
}
