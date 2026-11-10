import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import { layout, type Node } from "./layout";
import { TAG_COLOURS, tagSymbol } from "./tags";
import type { EventRecord } from "./types";

const COL = 64;
const LANE = 72;
const LEFT = 88;
const TOP = 36;
const R = 11;
const SHAPE_AREA = 300;

interface Props {
  events: EventRecord[]; // the whole log, so columns stay put while the cursor moves
  roster: string[];
  cursor: number;
  onSelect?: (e: EventRecord) => void;
}

/**
 * Messages as shapes in one lane per agent, reply_to as arrows. Events after the cursor stay in
 * place but fade, so scrubbing never moves the columns. Each tag has a shape, a colour and a
 * written label, and TERM and replay starts are marked on the timeline.
 */
export function Graph({ events, roster, cursor, onSelect }: Props) {
  const { lanes, nodes, edges, rollbacks, term } = useMemo(
    () => layout(events, roster),
    [events, roster],
  );
  const svgRef = useRef<SVGSVGElement>(null);
  const [transform, setTransform] = useState(d3.zoomIdentity);
  const [hover, setHover] = useState<Node | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .clickDistance(4) // small jitter between mousedown and mouseup is still a click
      .filter((ev) => !ev.button && !ev.ctrlKey && !(ev.target as Element).closest(".node, .marker"))
      .on("zoom", (ev) => setTransform(ev.transform));
    d3.select(svgRef.current).call(zoom);
    return () => {
      d3.select(svgRef.current).on(".zoom", null);
    };
  }, []);

  const x = (col: number) => LEFT + col * COL;
  const y = (lane: number) => TOP + lane * LANE;
  const height = TOP + Math.max(lanes.length, 1) * LANE;
  const width = Math.max(x(nodes.length) + COL, 480);
  const later = (e: EventRecord) => e.seq > cursor;

  const arc = (from: Node, to: Node) => {
    const [x1, y1, x2, y2] = [x(from.col), y(from.lane), x(to.col), y(to.lane)];
    const bend = y1 === y2 ? -28 : 0; // same lane: arc above the row
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2 + bend;
    const dx = x2 - mx;
    const dy = y2 - my;
    const len = Math.hypot(dx, dy) || 1;
    const endX = x2 - (dx / len) * (R + 3);
    const endY = y2 - (dy / len) * (R + 3);
    return `M${x1},${y1} Q${mx},${my} ${endX},${endY}`;
  };
  const pressed = (select: () => void) => (ev: React.KeyboardEvent) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      select();
    }
  };

  if (!nodes.length) return <div className="empty">No messages yet.</div>;

  return (
    <div className="graph">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label="Message timeline: agents as rows, replies as arrows"
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
            markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="var(--edge)" />
          </marker>
        </defs>
        <g transform={transform.toString()}>
          {lanes.map((agent, i) => (
            <g key={agent}>
              <line x1={LEFT - 20} x2={width} y1={y(i)} y2={y(i)} className="lane" />
              <text x={12} y={y(i) + 4} className="lane-label">{agent}</text>
            </g>
          ))}
          {rollbacks.map(({ start, col }) => (
            <g
              key={start.seq}
              className={later(start) ? "marker rollback-marker future" : "marker rollback-marker"}
              role="button"
              tabIndex={0}
              aria-label={`Replay of message ${start.reply_to} by ${start.author}`}
              onClick={() => onSelect?.(start)}
              onKeyDown={pressed(() => onSelect?.(start))}
            >
              <line x1={x(col)} x2={x(col)} y1={TOP - 24} y2={height - 20} />
              <text x={x(col) + 4} y={TOP - 14}>replay of #{start.reply_to}</text>
            </g>
          ))}
          {term && (
            <g
              className={later(term.event) ? "marker term-marker future" : "marker term-marker"}
              role="button"
              tabIndex={0}
              aria-label={`Session stopped: ${term.event.explanation}`}
              onClick={() => onSelect?.(term.event)}
              onKeyDown={pressed(() => onSelect?.(term.event))}
            >
              <line x1={x(term.col)} x2={x(term.col)} y1={TOP - 24} y2={height - 20} />
              <path d={tagSymbol("TERM", 90)} transform={`translate(${x(term.col)},${TOP - 30})`}
                fill={TAG_COLOURS.TERM} />
              <text x={x(term.col) + 8} y={TOP - 26}>TERM · {term.event.explanation}</text>
            </g>
          )}
          {edges.map(({ from, to }) => (
            <path key={from.event.seq} d={arc(from, to)}
              className={later(from.event) ? "edge future" : "edge"}
              stroke={TAG_COLOURS[from.event.tag ?? "INIT"]} markerEnd="url(#arrow)" />
          ))}
          {nodes.map((n) => {
            const e = n.event;
            const tag = e.tag ?? "INIT";
            const classes = ["node", e.seq === cursor ? "selected" : "", later(e) ? "future" : ""];
            return (
              <g
                key={e.seq}
                transform={`translate(${x(n.col)},${y(n.lane)})`}
                className={classes.filter(Boolean).join(" ")}
                role="button"
                tabIndex={0}
                aria-label={`Event ${e.seq}, ${e.author} ${tag}${e.reply_to === null ? "" : `, replies to ${e.reply_to}`}`}
                aria-pressed={e.seq === cursor}
                onMouseEnter={() => setHover(n)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(n)}
                onBlur={() => setHover(null)}
                onClick={() => onSelect?.(e)}
                onKeyDown={pressed(() => onSelect?.(e))}
              >
                <path d={tagSymbol(tag, SHAPE_AREA)} fill={TAG_COLOURS[tag]} className="shape" />
                <text y={R + 13} textAnchor="middle" className="node-tag-label">{tag}</text>
                <text y={R + 25} textAnchor="middle" className="node-seq">#{e.seq}</text>
              </g>
            );
          })}
        </g>
      </svg>
      {hover && (
        <div className="tooltip">
          <b>
            [{hover.event.seq}] {hover.event.author} {hover.event.tag}
            {hover.event.reply_to !== null && ` → ${hover.event.reply_to}`}
          </b>
          <div>Prediction: {hover.event.prediction}</div>
          <div>{hover.event.explanation}</div>
          <div className="muted">
            tokens {hover.event.tokens.in} in / {hover.event.tokens.out} out
          </div>
        </div>
      )}
    </div>
  );
}
