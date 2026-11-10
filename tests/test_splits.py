"""Roadmap section 06: held-out and development item lists chosen by stable id."""

import json
from pathlib import Path

import pytest

from bench import mscore
from bench.mscore import Instance
from bench.splits import Splits, choose, screen_open

ROOT = Path(__file__).resolve().parents[1] / "data" / "cases"


def inst(
    i: int, domain: str = "law", reference: str = "x" * 200, question: str | None = None
) -> Instance:
    return Instance(
        id=f"file#{i}",
        domain=domain,
        format="open_qa",
        difficulty="simple",
        stage="s",
        question=question or f"What should be done about item number {i}?",
        reference=reference,
    )


def test_choice_depends_on_ids_not_on_pool_order() -> None:
    pool = [inst(i) for i in range(40)]
    a = choose(pool, heldout=8, dev=4, seed=0)
    b = choose(list(reversed(pool)), heldout=8, dev=4, seed=0)
    assert a == b
    assert len(a.heldout) == 8 and len(a.dev) == 4
    assert not set(a.heldout) & set(a.dev)


def test_other_seed_gives_other_items() -> None:
    pool = [inst(i) for i in range(40)]
    assert choose(pool, 8, 4, seed=0).heldout != choose(pool, 8, 4, seed=1).heldout


def test_new_items_rarely_move_chosen_ones() -> None:
    pool = [inst(i) for i in range(40)]
    before = set(choose(pool, 8, 4, seed=0).heldout)
    after = set(choose([*pool, inst(99)], 8, 4, seed=0).heldout)
    assert len(before & after) >= 7


def test_domains_are_balanced_round_robin() -> None:
    pool = [inst(i, "law") for i in range(30)] + [inst(100 + i, "finance") for i in range(30)]
    picked = choose(pool, heldout=8, dev=2, seed=0).heldout
    domains = [next(p.domain for p in pool if p.id == i) for i in picked]
    assert domains.count("law") == domains.count("finance") == 4


def test_too_small_a_pool_is_an_error() -> None:
    with pytest.raises(ValueError, match="needs 12"):
        choose([inst(i) for i in range(5)], 8, 4, seed=0)


def test_screen_rejects_items_without_a_gradeable_reference() -> None:
    assert screen_open(inst(1))
    assert not screen_open(inst(2, reference=""))
    assert not screen_open(inst(3, reference="short"))
    assert not screen_open(inst(4, question="?"))
    assert not screen_open(inst(5, reference="x" * 5000))


def test_screening_applies_before_choosing() -> None:
    pool = [inst(i, reference="" if i % 2 else "y" * 200) for i in range(40)]
    picked = choose(pool, 8, 4, seed=0, keep=screen_open)
    assert all(int(i.split("#")[1]) % 2 == 0 for i in picked.heldout + picked.dev)


def test_committed_split_file_matches_the_case_files() -> None:
    splits = Splits.load(ROOT / "splits.json")
    from bench.cases import load_cases

    book = load_cases(ROOT)
    assert sorted(splits.authored["heldout"]) == [c.id for c in book.split("heldout")]
    assert sorted(splits.authored["dev"]) == [c.id for c in book.split("dev")]
    assert len(splits.choice.heldout) == len(splits.open.heldout) == 8
    assert len(splits.choice.dev) + len(splits.open.dev) + len(splits.authored["dev"]) >= 12


def test_committed_ids_are_unique_and_resolvable_format() -> None:
    splits = Splits.load(ROOT / "splits.json")
    ids = [*splits.choice.heldout, *splits.choice.dev, *splits.open.heldout, *splits.open.dev]
    assert len(ids) == len(set(ids))
    assert all("#" in i for i in ids)
    json.loads((ROOT / "splits.json").read_text())
    assert mscore  # ids use the ingestor's stable `<path>#<index>` form
