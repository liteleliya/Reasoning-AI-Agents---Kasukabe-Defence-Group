import { describe, expect, it } from "vitest";
import { TAG_COLOURS, TAG_MEANING, TAG_SHAPE, TAG_SHORT, tagSymbol } from "./tags";
import type { Tag } from "./types";

const TAGS = Object.keys(TAG_COLOURS) as Tag[];

describe("tags", () => {
  it("describes every tag in every table", () => {
    for (const t of TAGS) {
      expect(TAG_MEANING[t]).toBeTruthy();
      expect(TAG_SHORT[t]).toBeTruthy();
      expect(TAG_SHAPE[t]).toBeTruthy();
    }
  });

  it("gives each tag its own shape, so meaning survives a grayscale screenshot", () => {
    expect(new Set(TAGS.map((t) => TAG_SHAPE[t])).size).toBe(TAGS.length);
    expect(new Set(TAGS.map((t) => tagSymbol(t, 300))).size).toBe(TAGS.length);
  });
});
