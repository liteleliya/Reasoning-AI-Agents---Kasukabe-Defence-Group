"""Held-out and development item lists for the study (roadmap section 06).

Items are ranked by a hash of their stable id, so the pick does not depend on file order and a
new item rarely displaces a chosen one. Domains are taken round-robin so no domain dominates.
The lists are written to `data/cases/splits.json` and reused as written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from bench.cases import DEFAULT_ROOT, load_cases
from bench.mscore import Instance, load_file, load_ids, select_files

MIN_REFERENCE, MAX_REFERENCE, MIN_QUESTION = 40, 2500, 8

KINDS = ("authored", "choice", "open")

# The open pool: the automotive Easy stages. "Supply Chain" is left out because the source file
# is not valid JSON, and the larger files are ~30 MB each, so other domains are added on demand.
OPEN_FILES = tuple(
    f"Automotive Value Chain/Easy/{stage}"
    for stage in ("Design", "Manufacture", "Qulaity Inspection", "Recycling", "Sales")
)


@dataclass(frozen=True)
class Pick:
    heldout: list[str]
    dev: list[str]


@dataclass(frozen=True)
class Splits:
    choice: Pick
    open: Pick
    authored: dict[str, list[str]]
    seed: int

    @classmethod
    def load(cls, path: str | Path) -> Splits:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(Pick(**raw["choice"]), Pick(**raw["open"]), raw["authored"], raw["seed"])

    def to_json(self) -> dict:
        return {
            "seed": self.seed,
            "choice": {"heldout": self.choice.heldout, "dev": self.choice.dev},
            "open": {"heldout": self.open.heldout, "dev": self.open.dev},
            "authored": self.authored,
        }


def _rank(item: Instance, seed: int) -> str:
    return hashlib.sha256(f"{seed}|{item.id}".encode()).hexdigest()


def screen_open(item: Instance) -> bool:
    """Cheap pre-screen for open items; a person still reads the survivors for evidence."""
    return (
        MIN_REFERENCE <= len(item.reference) <= MAX_REFERENCE and len(item.question) >= MIN_QUESTION
    )


def choose(
    pool: Sequence[Instance],
    heldout: int,
    dev: int,
    seed: int,
    keep: Callable[[Instance], bool] = lambda _: True,
    group: Callable[[Instance], str] = lambda i: i.domain,
) -> Pick:
    """`heldout` then `dev` ids, drawn round-robin over `group` (domain by default)."""
    by_domain: dict[str, list[Instance]] = defaultdict(list)
    for item in sorted((i for i in pool if keep(i)), key=lambda i: _rank(i, seed)):
        by_domain[group(item)].append(item)
    order: list[str] = []
    queues = [by_domain[d] for d in sorted(by_domain)]
    while any(queues) and len(order) < heldout + dev:
        for queue in queues:
            if queue and len(order) < heldout + dev:
                order.append(queue.pop(0).id)
    if len(order) < heldout + dev:
        raise ValueError(f"needs {heldout + dev} usable items, the pool has {len(order)}")
    return Pick(order[:heldout], order[heldout:])


def choice_pool() -> list[Instance]:
    files = select_files(formats=["single_choice"], difficulties=["simple", "complex"])
    return [item for f in files for item in load_file(f.path)]


def open_pool() -> list[Instance]:
    return [item for path in OPEN_FILES for item in load_file(path)]


def study_instances(
    split: str,
    kinds: Sequence[str] = KINDS,
    ids: Sequence[str] | None = None,
    root: str | Path = DEFAULT_ROOT,
) -> list[Instance]:
    """The instances of one split: authored cases (optionally only `ids`) and listed dataset items.

    Reads only local files, so a run needs no network once the dataset files are cached.
    """
    if split not in ("dev", "heldout"):
        raise ValueError(f"split must be dev or heldout, got {split!r}")
    book, splits = load_cases(root), Splits.load(Path(root) / "splits.json")
    out: list[Instance] = []
    for kind in kinds:
        if kind == "authored":
            wanted = list(ids) if ids is not None else splits.authored[split]
            unknown = [i for i in wanted if i not in book.public]
            if unknown:
                raise ValueError(f"unknown case id {unknown[0]!r}")
            out += [book.instance(i) for i in wanted]
        elif kind in ("choice", "open"):
            out += load_ids(getattr(getattr(splits, kind), split))
        else:
            raise ValueError(f"unknown kind {kind!r}")
    return out


def manifest_info(split: str, kinds: Sequence[str], root: str | Path = DEFAULT_ROOT) -> dict:
    """What a run.json records so a result can be tied to the exact case files."""
    splits_file = Path(root) / "splits.json"
    return {
        "version": load_cases(root).version,
        "splits_sha256": hashlib.sha256(splits_file.read_bytes()).hexdigest()[:12],
        "split": split,
        "kinds": list(kinds),
    }


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Write the held-out and development item lists.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=DEFAULT_ROOT / "splits.json")
    a = p.parse_args(argv)
    book = load_cases()
    splits = Splits(
        choice=choose(choice_pool(), 8, 3, a.seed, group=lambda i: f"{i.domain}/{i.difficulty}"),
        open=choose(open_pool(), 8, 5, a.seed, keep=screen_open, group=lambda i: i.stage),
        authored={s: [c.id for c in book.split(s)] for s in ("heldout", "dev")},
        seed=a.seed,
    )
    a.out.write_text(json.dumps(splits.to_json(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
