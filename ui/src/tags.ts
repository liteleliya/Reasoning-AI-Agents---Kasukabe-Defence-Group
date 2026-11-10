import * as d3 from "d3";
import type { Tag } from "./types";

// Okabe-Ito palette: distinguishable with common colour-vision deficiencies.
export const TAG_COLOURS: Record<Tag, string> = {
  INIT: "#999999",
  RATIFY: "#009E73",
  REVISE: "#0072B2",
  REFUTE: "#E69F00",
  REJECT: "#D55E00",
  TERM: "#444444",
};

export const TAG_MEANING: Record<Tag, string> = {
  INIT: "opening prediction and explanation",
  RATIFY: "prediction matches and explanation agrees",
  REVISE: "learned from the message and now agrees",
  REFUTE: "partial agreement; replies with corrective information",
  REJECT: "prediction differs and explanation disagrees",
  TERM: "session ended",
};

export const TAG_SHORT: Record<Tag, string> = {
  INIT: "IN",
  RATIFY: "RA",
  REVISE: "RV",
  REFUTE: "RF",
  REJECT: "RJ",
  TERM: "TE",
};

// A shape per tag as well as a colour, so a grayscale screenshot still tells tags apart.
export const TAG_SHAPE: Record<Tag, string> = {
  INIT: "circle",
  RATIFY: "square",
  REVISE: "triangle",
  REFUTE: "diamond",
  REJECT: "cross",
  TERM: "star",
};

const SYMBOLS: Record<string, d3.SymbolType> = {
  circle: d3.symbolCircle,
  square: d3.symbolSquare,
  triangle: d3.symbolTriangle,
  diamond: d3.symbolDiamond,
  cross: d3.symbolCross,
  star: d3.symbolStar,
};

/** The SVG path of a tag's shape, centred on the origin; `size` is its area in px². */
export function tagSymbol(tag: Tag, size: number): string {
  return d3.symbol().type(SYMBOLS[TAG_SHAPE[tag]]).size(size)() ?? "";
}
