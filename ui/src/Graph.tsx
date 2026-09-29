import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import { layout, type Node } from "./layout";
import { TAG_COLOURS, TAG_SHORT } from "./tags";
import type { EventRecord } from "./types";

const COL = 64;
const LANE = 72;
const LEFT = 88;
const TOP = 36;
const R = 11;

interface Props {
  events: EventRecord[];
  highlightSeq?: number | null;
  onSelect?: (e: EventRecord) => void;
}

/** Messages as nodes in one lane per agent, reply_to as arrows, coloured by tag (C2). */
export function Graph({ events, highlightSeq, onSelect }: Props) {
  const { lanes, nodes, edges, rollbacks } = useMemo(() => layout(events), [events]);
  const svgRef = useRef<SVGSVGElement>(null);
  const [transform, setTransform] = useState(d3.zoomIdentity);
  const [hover, setHover] = useState<Node | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .clickDistance(4) // small jitter between mousedown and mouseup is still a click
      .filter((ev) => !ev.button && !ev.ctrlKey && !(ev.target as Element).closest(".node"))
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

  if (!nodes.length) return <div className="empty">No messages yet.</div>;

  return (
    <div className="graph">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Message graph: agents as rows, replies as arrows"
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
            <g key={start.seq} className="rollback-marker">
              <line x1={x(col)} x2={x(col)} y1={TOP - 24} y2={height - 20} />
              <text x={x(col) + 4} y={TOP - 14}>rollback by {start.author}</text>
            </g>
          ))}
          {edges.map(({ from, to }) => (
            <path key={from.event.seq} d={arc(from, to)} className="edge"
              stroke={TAG_COLOURS[from.event.tag ?? "INIT"]} markerEnd="url(#arrow)" />
          ))}
          {nodes.map((n) => (
            <g
              key={n.event.seq}
              transform={`translate(${x(n.col)},${y(n.lane)})`}
              className={n.event.seq === highlightSeq ? "node selected" : "node"}
              onMouseEnter={() => setHover(n)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(n.event)}
            >
              <circle r={R} fill={TAG_COLOURS[n.event.tag ?? "INIT"]} />
              <text y={R + 14} textAnchor="middle" className="node-seq">{n.event.seq}</text>
              <text y={4} textAnchor="middle" className="node-tag">
                {n.event.tag ? TAG_SHORT[n.event.tag] : ""}
              </text>
            </g>
          ))}
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
