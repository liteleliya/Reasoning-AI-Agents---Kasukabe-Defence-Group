import { TAG_COLOURS, TAG_MEANING } from "./tags";
import type { Tag } from "./types";

export function Legend() {
  const tags: Tag[] = ["INIT", "RATIFY", "REVISE", "REFUTE", "REJECT"];
  return (
    <ul className="legend">
      {tags.map((t) => (
        <li key={t} title={TAG_MEANING[t]}>
          <span className="swatch" style={{ background: TAG_COLOURS[t] }} />
          {t}
        </li>
      ))}
    </ul>
  );
}
