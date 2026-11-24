"""Run the server: `uv run python -m server --db board.sqlite [--demo]`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path

import uvicorn

from bench.summary import KINDS
from blackboard import EventStore
from server.app import create_app
from server.catalog import load_metrics_index
from server.demo import run_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite event log (default: results/board.sqlite)")
    parser.add_argument(
        "--run-dir",
        help="paired run folder; supplies board.sqlite, metrics.csv and saved analysis automatically",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--metrics", help="the run's metrics.csv, to show outcomes in the session list"
    )
    parser.add_argument("--source", default="", help="label for the run shown in the session list")
    parser.add_argument(
        "--kind",
        choices=KINDS,
        help="what the run is evidence of, shown in the results view",
    )
    parser.add_argument("--demo", action="store_true", help="stream mock sessions into the board")
    parser.add_argument("--delay", type=float, default=0.8, help="seconds between demo moves")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else None
    shard_dirs = sorted(run_dir.glob("shard-*") if run_dir else [])
    artifact_dir = run_dir
    # Sharded bench output keeps each board and its metrics together. The common local study
    # currently has one shard; select it automatically so `--run-dir` opens the matching archive.
    if run_dir and not (run_dir / "metrics.csv").exists() and len(shard_dirs) == 1:
        artifact_dir = shard_dirs[0]
    db = Path(args.db) if args.db else (artifact_dir / "board.sqlite" if run_dir else Path("results/board.sqlite"))
    metrics_path = Path(args.metrics) if args.metrics else (artifact_dir / "metrics.csv" if run_dir else None)
    metrics = load_metrics_index(metrics_path) if metrics_path else None
    store = EventStore(db)
    app = create_app(
        store,
        metrics=metrics,
        source=args.source or (run_dir.name if run_dir else ""),
        kind=args.kind,
        run_dir=run_dir,
    )

    if args.demo:

        @contextlib.asynccontextmanager
        async def lifespan(_app):
            task = asyncio.create_task(run_demo(store, args.delay))
            yield
            task.cancel()

        app.router.lifespan_context = lifespan

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
