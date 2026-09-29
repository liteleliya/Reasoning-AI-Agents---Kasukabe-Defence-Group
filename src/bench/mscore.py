"""MSCoRe ingestor (D1): download, parse and sample instances from HF `032564yn/MSCoRe`.

The HF repo is a tree of JSON files without extensions, not a `datasets` config, so files are
fetched directly with httpx and cached under `data/mscore/`. Instance ids are `<file path>#<index>`,
stable across runs, so sample-id lists (task T9) can be shared.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx

REPO_URL = "https://huggingface.co/datasets/032564yn/MSCoRe/resolve/main/"
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "data" / "mscore"

OPEN_QA, SINGLE, MULTI, JUDGMENT = "open_qa", "single_choice", "multi_choice", "judgment"


@dataclass(frozen=True)
class SourceFile:
    path: str
    domain: str
    format: str
    difficulty: str  # simple | medium | complex | unspecified
    stage: str


def _open(path: str, domain: str, difficulty: str, stage: str) -> SourceFile:
    return SourceFile(path, domain, OPEN_QA, difficulty, stage)


_AUTO = "Automotive Value Chain"
_ECOM = "Electronic Commerce Value Chain"
_PHARMA = "Pharmaceytical Value Chain"  # sic, as named in the HF repo
_ENERGY = "Automotive-Energy Chain"

# Paths exactly as in the HF repo (typos included). Software Engineering (ordering) is left out.
MANIFEST: tuple[SourceFile, ...] = (
    *(
        _open(f"{_AUTO}/{lvl}/{stage}", "automotive", diff, stage)
        for lvl, diff, stages in [
            (
                "Easy",
                "simple",
                [
                    "Design",
                    "Manufacture",
                    "Qulaity Inspection",
                    "Recycling",
                    "Sales",
                    "Supply Chain",
                ],
            ),
            (
                "Medium",
                "medium",
                ["Design", "Manufacture", "Quality Inspection", "Recycle", "Sales", "Supply Chain"],
            ),
            (
                "Hard",
                "complex",
                [
                    "Design",
                    "Manufacture",
                    "Quality Inspection",
                    "Recycling",
                    "Sales",
                    "Supply Chain",
                ],
            ),
        ]
        for stage in stages
    ),
    *(
        _open(f"{_ENERGY}/{stage}", "automotive_energy", "unspecified", stage)
        for stage in [
            "Automotive Design",
            "Automotive Manufature",
            "Automotive Sales",
            "Electricity  Generation",
            "Electricity Storage",
            "Electricity Usage",
        ]
    ),
    *(
        _open(f"{_ECOM}/Easy/{stage}", "ecommerce", "simple", stage)
        for stage in [
            "Platform Operations",
            "Product Procurement",
            "User Experience",
            "Warehousing and Logistics",
        ]
    ),
    _open(f"{_ECOM}/Hard/Full-Chain-task", "ecommerce", "complex", "Full-Chain-task"),
    *(
        _open(f"{_PHARMA}/Easy/{stage}", "pharmaceutical", "simple", stage)
        for stage in [
            "Drug Development",
            "Drug Supply Chain",
            "Manufacturing",
            "Material Procurement",
            "Sales and Distribution",
        ]
    ),
    _open(f"{_PHARMA}/Medium/Multi-stage-task", "pharmaceutical", "medium", "Multi-stage-task"),
    _open(f"{_PHARMA}/Hard/Full-Chain-task", "pharmaceutical", "complex", "Full-Chain-task"),
    *(
        SourceFile(f"Data2/{dom}/{kind}/{lvl}", dom.lower(), fmt, diff, kind)
        for dom, simple in [("Finance", "easy"), ("Law", "simple")]
        for kind, fmt in [("Single-choice", SINGLE), ("Multi-choice", MULTI)]
        for lvl, diff in [(simple, "simple"), ("complex", "complex")]
    ),
    SourceFile("Data2/Construction/simple/data.json", "construction", JUDGMENT, "simple", ""),
    SourceFile("Data2/Construction/complex/data.json", "construction", JUDGMENT, "complex", ""),
)
_BY_PATH = {f.path: f for f in MANIFEST}


@dataclass(frozen=True)
class Instance:
    id: str
    domain: str
    format: str
    difficulty: str
    stage: str
    question: str
    reference: str  # open QA: reference answer; choice: "A" or "A|B|C"; judgment: 是 / 否
    context: str = ""
    options: tuple[tuple[str, str], ...] = ()

    def prompt_text(self) -> str:
        """The question as shown to agents, with context and lettered options if any."""
        parts = [self.question]
        if self.context:
            parts.append(self.context)
        parts += [f"{k}. {v}" for k, v in self.options]
        return "\n".join(parts)


def download(path: str, cache_dir: Path = DEFAULT_CACHE) -> Path:
    """Fetch one repo file into the cache (atomic rename) unless it is already there."""
    target = cache_dir / path
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    with httpx.stream("GET", REPO_URL + quote(path), follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(target)
    return target


def parse(source: SourceFile, records: Sequence[dict]) -> list[Instance]:
    out = []
    for i, r in enumerate(records):
        if source.format == OPEN_QA:
            question, reference, context = r["instruction"], r["output"], r.get("input", "")
            options: tuple[tuple[str, str], ...] = ()
        else:
            question, reference, context = r["question"], str(r["answer"]), ""
            options = tuple(sorted(r.get("options", {}).items()))
        out.append(
            Instance(
                id=f"{source.path}#{i}",
                domain=source.domain,
                format=source.format,
                difficulty=source.difficulty,
                stage=source.stage,
                question=question.strip(),
                reference=reference.strip(),
                context=context.strip(),
                options=options,
            )
        )
    return out


@lru_cache(maxsize=8)
def load_file(path: str, cache_dir: Path = DEFAULT_CACHE) -> tuple[Instance, ...]:
    source = _BY_PATH[path]
    records = json.loads(download(path, cache_dir).read_text(encoding="utf-8"))
    return tuple(parse(source, records))


def select_files(
    domains: Iterable[str] | None = None,
    formats: Iterable[str] | None = None,
    difficulties: Iterable[str] | None = None,
) -> list[SourceFile]:
    d, f, lv = (set(x) if x else None for x in (domains, formats, difficulties))
    return [
        s
        for s in MANIFEST
        if (d is None or s.domain in d)
        and (f is None or s.format in f)
        and (lv is None or s.difficulty in lv)
    ]


def sample(
    n_per_group: int,
    seed: int,
    *,
    domains: Iterable[str] | None = None,
    formats: Iterable[str] | None = None,
    difficulties: Iterable[str] | None = None,
    cache_dir: Path = DEFAULT_CACHE,
) -> list[Instance]:
    """`n_per_group` instances per (domain, difficulty), spread over that group's files.

    Deterministic for a given seed and selection; the same seed always picks the same ids.
    """
    groups: dict[tuple[str, str], list[SourceFile]] = defaultdict(list)
    for s in select_files(domains, formats, difficulties):
        groups[(s.domain, s.difficulty)].append(s)
    picked: list[Instance] = []
    for key in sorted(groups):
        pool = [inst for s in groups[key] for inst in load_file(s.path, cache_dir)]
        rng = random.Random(f"{seed}|{key[0]}|{key[1]}")
        picked += rng.sample(pool, min(n_per_group, len(pool)))
    return picked


def load_ids(ids: Iterable[str], cache_dir: Path = DEFAULT_CACHE) -> list[Instance]:
    """Instances for explicit ids like `Data2/Law/Single-choice/simple#12` (e.g. T9's list)."""
    out = []
    for iid in ids:
        path, _, index = iid.rpartition("#")
        out.append(load_file(path, cache_dir)[int(index)])
    return out


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Sample MSCoRe instances into a JSONL file.")
    p.add_argument("--n", type=int, default=5, help="instances per (domain, difficulty)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--domains", nargs="*")
    p.add_argument("--formats", nargs="*")
    p.add_argument("--difficulties", nargs="*")
    p.add_argument("--out", default="results/mscore_sample.jsonl")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    a = p.parse_args(argv)
    items = sample(
        a.n,
        a.seed,
        domains=a.domains,
        formats=a.formats,
        difficulties=a.difficulties,
        cache_dir=a.cache_dir,
    )
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for inst in items:
            f.write(json.dumps(asdict(inst), ensure_ascii=False) + "\n")
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for inst in items:
        counts[(inst.domain, inst.difficulty)] += 1
    for (dom, diff), c in sorted(counts.items()):
        print(f"{dom:<18} {diff:<12} {c}")
    print(f"wrote {len(items)} instances to {a.out}")


if __name__ == "__main__":
    main()
