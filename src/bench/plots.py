"""Plot scripts (D5): H1-H3 against the share of counterfactual agents, from the metrics CSV.

Run with `uv run python -m bench.plots results/metrics.csv --out results/figures`.
Writes PNG + PDF per figure and `summary.csv` (the table view of every plotted number).
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from bench.metrics import read_metrics

# Reference categorical palette, light mode, fixed order (validated: first three slots pass).
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"

STOP_REASONS = ("consensus", "impasse", "cap")
CLASSES = ("ultra_strong", "strong", "failed")
CLASS_NAMES = {"ultra_strong": "Ultra-Strong", "strong": "Strong", "failed": "Not intelligible"}


@dataclass
class Cell:
    """Aggregates for one (benchmark, cf_share) cell; every plotted number lives here."""

    benchmark: str
    cf_share: float
    n: int
    converged: float
    converged_lo: float
    converged_hi: float
    ultra_strong: float
    ultra_strong_lo: float
    ultra_strong_hi: float
    strong: float
    failed: float
    tokens_mean: float
    tokens_lo: float
    tokens_hi: float
    rollback_tokens_mean: float
    real_tokens_mean: float
    consensus: float
    impasse: float
    cap: float


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean(values: Sequence[float], reps: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap interval for the mean (seeded, so figures are reproducible)."""
    if not values:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(reps))
    return (means[int(0.025 * reps)], means[int(0.975 * reps) - 1])


def aggregate(rows: list[dict[str, str]]) -> list[Cell]:
    groups: dict[tuple[str, float], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        groups[(r["benchmark"], float(r["cf_share"]))].append(r)
    cells = []
    for (bench, share), rs in sorted(groups.items()):
        n = len(rs)
        conv = sum(r["converged"] == "True" for r in rs)
        classes = {c: sum(r["intelligibility"] == c for r in rs) for c in CLASSES}
        stops = {s: sum(r["stop_reason"] == s for r in rs) for s in STOP_REASONS}
        tokens = [float(r["total_tokens"]) for r in rs]
        rollback = [float(r["rollback_tokens_in"]) + float(r["rollback_tokens_out"]) for r in rs]
        cells.append(
            Cell(
                benchmark=bench,
                cf_share=share,
                n=n,
                converged=conv / n,
                converged_lo=wilson(conv, n)[0],
                converged_hi=wilson(conv, n)[1],
                ultra_strong=classes["ultra_strong"] / n,
                ultra_strong_lo=wilson(classes["ultra_strong"], n)[0],
                ultra_strong_hi=wilson(classes["ultra_strong"], n)[1],
                strong=classes["strong"] / n,
                failed=classes["failed"] / n,
                tokens_mean=sum(tokens) / n,
                tokens_lo=bootstrap_mean(tokens)[0],
                tokens_hi=bootstrap_mean(tokens)[1],
                rollback_tokens_mean=sum(rollback) / n,
                real_tokens_mean=(sum(tokens) - sum(rollback)) / n,
                consensus=stops["consensus"] / n,
                impasse=stops["impasse"] / n,
                cap=stops["cap"] / n,
            )
        )
    return cells


# --- drawing ------------------------------------------------------------------------------


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_2,
            "axes.titlecolor": TEXT,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": TEXT_2,
            "ytick.color": TEXT_2,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "font.size": 9,
            "legend.frameon": False,
            "legend.fontsize": 8.5,
            "savefig.dpi": 200,
        }
    )


def _panels(cells: list[Cell], title: str):
    benches = sorted({c.benchmark for c in cells})
    fig, axes = plt.subplots(
        1, len(benches), figsize=(3.4 * len(benches) + 0.6, 3.1), sharey=True, squeeze=False
    )
    fig.suptitle(title, x=0.02, ha="left", fontsize=11, fontweight="bold", color=TEXT)
    return fig, [
        (b, ax, [c for c in cells if c.benchmark == b])
        for b, ax in zip(benches, axes[0], strict=True)
    ]


def _share_axis(ax, cs: list[Cell]) -> list[float]:
    xs = [c.cf_share for c in cs]
    ax.set_xticks(xs, [f"{round(x * 100)}%" for x in xs])
    ax.set_xlim(-0.15, 1.15)
    ax.set_xlabel("Counterfactual-enabled agents")
    return xs


def _point_ci(ax, cs, mean, lo, hi, fmt) -> None:
    xs = _share_axis(ax, cs)
    ys = [getattr(c, mean) for c in cs]
    err = [
        [y - getattr(c, lo) for c, y in zip(cs, ys, strict=True)],
        [getattr(c, hi) - y for c, y in zip(cs, ys, strict=True)],
    ]
    ax.plot(xs, ys, color=SERIES[0], linewidth=2, zorder=2)
    ax.errorbar(
        xs, ys, yerr=err, fmt="none", ecolor=SERIES[0], elinewidth=1.25, capsize=3, zorder=2
    )
    ax.scatter(xs, ys, s=40, color=SERIES[0], edgecolor=SURFACE, linewidth=2, zorder=3)
    for x, y, c in zip(xs, ys, cs, strict=True):
        ax.annotate(
            fmt(y), (x, y), textcoords="offset points", xytext=(8, -12), fontsize=8, color=TEXT
        )
        ax.annotate(
            f"n={c.n}",
            (x, 0),
            xycoords=("data", "axes fraction"),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=7,
            color=TEXT_2,
        )


def _stacked(ax, cs, parts, names, fmt=lambda v: f"{v:.0%}", share: bool = True) -> None:
    xs = _share_axis(ax, cs)
    bottom = [0.0] * len(cs)
    for i, part in enumerate(parts):
        vals = [getattr(c, part) for c in cs]
        ax.bar(
            xs,
            vals,
            width=0.22,
            bottom=bottom,
            color=SERIES[i],
            edgecolor=SURFACE,
            linewidth=2,
            label=names[i],
        )
        for x, b, v in zip(xs, bottom, vals, strict=True):
            if (v >= 0.08) if share else v > 0:
                ax.text(
                    x,
                    b + v / 2,
                    fmt(v),
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=TEXT,
                    fontweight="bold",
                )
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
    if share:
        ax.set_ylim(0, 1.0)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")


def figure_h1(cells: list[Cell]):
    fig, panels = _panels(cells, "H1 · Sessions reaching consensus within the cap")
    for bench, ax, cs in panels:
        _point_ci(ax, cs, "converged", "converged_lo", "converged_hi", lambda v: f"{v:.0%}")
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Converged (95% Wilson CI)")
    return fig


def figure_h2(cells: list[Cell]):
    fig, panels = _panels(cells, "H2 · Sessions ending Ultra-Strong")
    for bench, ax, cs in panels:
        _point_ci(
            ax, cs, "ultra_strong", "ultra_strong_lo", "ultra_strong_hi", lambda v: f"{v:.0%}"
        )
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Ultra-Strong (95% Wilson CI)")
    return fig


def figure_h3(cells: list[Cell]):
    fig, panels = _panels(cells, "H3 · Tokens per instance, rollback tokens included")
    for bench, ax, cs in panels:
        _point_ci(ax, cs, "tokens_mean", "tokens_lo", "tokens_hi", lambda v: f"{v:,.0f}")
        ax.set_ylim(bottom=0)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Mean total tokens (95% bootstrap CI)")
    return fig


def figure_token_split(cells: list[Cell]):
    fig, panels = _panels(cells, "H3 · Where the tokens go: discussion vs counterfactual replays")
    for bench, ax, cs in panels:
        _stacked(
            ax,
            cs,
            ["real_tokens_mean", "rollback_tokens_mean"],
            ["Discussion", "Rollback replays"],
            fmt=lambda v: f"{v:,.0f}",
            share=False,
        )
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Mean tokens per instance")
    panels[-1][1].legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return fig


def figure_stops(cells: list[Cell]):
    fig, panels = _panels(cells, "How sessions stopped")
    for bench, ax, cs in panels:
        _stacked(ax, cs, STOP_REASONS, [s.capitalize() for s in STOP_REASONS])
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Share of sessions")
    panels[-1][1].legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return fig


def figure_intelligibility(cells: list[Cell]):
    fig, panels = _panels(cells, "Intelligibility class of each session")
    for bench, ax, cs in panels:
        _stacked(ax, cs, CLASSES, [CLASS_NAMES[c] for c in CLASSES])
        ax.set_title(bench, loc="left")
    panels[0][1].set_ylabel("Share of sessions")
    panels[-1][1].legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return fig


FIGURES = {
    "h1_convergence": figure_h1,
    "h2_ultra_strong": figure_h2,
    "h3_tokens": figure_h3,
    "h3_token_split": figure_token_split,
    "stop_reasons": figure_stops,
    "intelligibility_mix": figure_intelligibility,
}


def render(metrics_csv: str | Path, out_dir: str | Path) -> list[Path]:
    """Write every figure (PNG + PDF) and summary.csv; returns the written paths."""
    _style()
    rows = read_metrics(metrics_csv)
    if not rows:
        raise ValueError(f"{metrics_csv} has no finished trials")
    cells = aggregate(rows)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, make in FIGURES.items():
        fig = make(cells)
        fig.tight_layout()
        for ext in ("png", "pdf"):
            path = out / f"{name}.{ext}"
            fig.savefig(path)
            written.append(path)
        plt.close(fig)
    summary = out / "summary.csv"
    with summary.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(cells[0])))
        w.writeheader()
        for c in cells:
            w.writerow(
                {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(c).items()}
            )
    written.append(summary)
    return written


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("metrics", help="per-trial metrics CSV (bench.metrics)")
    p.add_argument("--out", default="results/figures")
    a = p.parse_args(argv)
    for path in render(a.metrics, a.out):
        print(path)


if __name__ == "__main__":
    main()
