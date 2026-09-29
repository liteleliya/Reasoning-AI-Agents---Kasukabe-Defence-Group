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
