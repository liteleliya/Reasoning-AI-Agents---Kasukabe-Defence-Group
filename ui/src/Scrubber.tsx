import { useEffect, useState } from "react";
import type { EventRecord } from "./types";

const PLAY_MS = 450; // fixed in the first release

interface Props {
  events: EventRecord[];
  cursor: number; // seq currently shown
  live: boolean; // following new events
  firstChallenge: number | null; // seq of the first REFUTE or REJECT
  termSeq: number | null; // seq of TERM; null while the session is still running
  onChange: (seq: number, live: boolean) => void;
}

/** History controls (C4): step, play, jump and follow live; the board is rebuilt up to the seq. */
export function Scrubber({ events, cursor, live, firstChallenge, termSeq, onChange }: Props) {
  const last = events.length ? events[events.length - 1].seq : 0;
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    if (cursor >= last) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => onChange(cursor + 1, false), PLAY_MS);
    return () => clearTimeout(id);
  }, [playing, cursor, last, onChange]);

  const jump = (seq: number | null) => {
    if (seq === null) return;
    setPlaying(false);
    onChange(seq, false);
  };
  const current = events.find((e) => e.seq === cursor);
  const disabled = !events.length;

  return (
    <div className="scrubber">
      <button onClick={() => jump(Math.max(0, cursor - 1))} disabled={disabled || cursor <= 0}>
        ◀ Previous
      </button>
      <button
        onClick={() => {
          if (cursor >= last) onChange(0, false);
          setPlaying((p) => !p);
        }}
        disabled={disabled}
      >
        {playing ? "Pause" : "Play"}
      </button>
      <button onClick={() => jump(Math.min(last, cursor + 1))} disabled={disabled || cursor >= last}>
        Next ▶
      </button>
      <button onClick={() => jump(firstChallenge)} disabled={firstChallenge === null}>
        First challenge
      </button>
      <button onClick={() => jump(termSeq)} disabled={termSeq === null}>
        Termination
      </button>
      <input
        type="range"
        min={0}
        max={last}
        value={cursor}
        disabled={disabled}
        onChange={(e) => {
          setPlaying(false);
          const seq = Number(e.target.value);
          onChange(seq, termSeq === null && seq === last);
        }}
        aria-label="Event sequence number"
      />
      <span className="seq" aria-live="polite">
        seq {cursor} / {last}
        {current && ` · ${current.author} ${current.tag ?? current.kind}`}
      </span>
      {termSeq === null && (
        <button
          className={live ? "live on" : "live"}
          aria-pressed={live}
          onClick={() => (live ? onChange(cursor, false) : onChange(last, true))}
        >
          Live
        </button>
      )}
    </div>
  );
}
