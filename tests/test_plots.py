"""D5: aggregation and figure rendering from a metrics CSV."""

import math
import random
from pathlib import Path

import pytest

from bench.metrics import COLUMNS, MetricsWriter
from bench.plots import aggregate, bootstrap_mean, render, wilson


def synthetic_rows(n_per_cell: int = 30, seed: int = 0) -> list[dict]:
    """Made-up trials where more counterfactual agents converge more often."""
    rng = random.Random(seed)
    rows = []
    for bench in ("mscore-law", "mscore-finance"):
        for k in range(4):
            share = k / 3
            for i in range(n_per_cell):
                converged = rng.random() < 0.35 + 0.15 * k
                stop = "consensus" if converged else rng.choice(["impasse", "cap"])
                label = rng.choices(
                    ["ultra_strong", "strong", "failed"], [0.2 + 0.1 * k, 0.2, 0.6 - 0.1 * k]
                )[0]
                rollback = int(rng.gauss(400 * k, 60)) if k else 0
                row = dict.fromkeys(COLUMNS, "")
                row.update(
                    trial_key=f"cf{k}|{bench}|q{i}|0",
                    config=f"cf{k}",
                    benchmark=bench,
                    instance_id=f"q{i}",
                    seed=0,
                    n_agents=3,
                    n_counterfactual=k,
                    cf_share=round(share, 4),
                    stop_reason=stop,
                    converged=converged,
                    intelligibility=label,
                    total_tokens=int(rng.gauss(3000, 400)) + rollback,
                    rollback_tokens_in=rollback,
                    rollback_tokens_out=0,
                )
                rows.append(row)
    return rows


def test_wilson_and_bootstrap() -> None:
    lo, hi = wilson(8, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.49, 0.943)
    assert all(math.isnan(v) for v in wilson(0, 0))  # empty cell
    assert bootstrap_mean([5.0] * 10) == (5.0, 5.0)
    lo, hi = bootstrap_mean([1.0, 2.0, 3.0, 4.0])
    assert 1.0 <= lo < 2.5 < hi <= 4.0


def test_aggregate_cells(tmp_path: Path) -> None:
    rows = synthetic_rows()
    cells = aggregate([{k: str(v) for k, v in r.items()} for r in rows])
    assert len(cells) == 8 and all(c.n == 30 for c in cells)
    c = cells[0]
    assert c.consensus + c.impasse + c.cap == pytest.approx(1)
    assert c.ultra_strong + c.strong + c.failed == pytest.approx(1)
    assert c.converged_lo <= c.converged <= c.converged_hi
    assert cells[0].rollback_tokens_mean == 0


def test_render_writes_all_figures(tmp_path: Path) -> None:
    csv_path = tmp_path / "metrics.csv"
    w = MetricsWriter(csv_path)
    for r in synthetic_rows(10):
        w.write(r)
    written = render(csv_path, tmp_path / "fig")
    names = sorted(p.name for p in written)
    assert "summary.csv" in names and "h1_convergence.png" in names and "h3_tokens.pdf" in names
    assert len(names) == 13
    assert all(p.stat().st_size > 0 for p in written)


def test_render_refuses_empty_csv(tmp_path: Path) -> None:
    MetricsWriter(tmp_path / "m.csv")
    with pytest.raises(ValueError, match="no finished trials"):
        render(tmp_path / "m.csv", tmp_path / "fig")
