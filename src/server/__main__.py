"""Run the server: `uv run python -m server --db board.sqlite [--demo]`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib

import uvicorn

from blackboard import EventStore
from server.app import create_app
from server.demo import run_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="results/board.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo", action="store_true", help="stream mock sessions into the board")
    parser.add_argument("--delay", type=float, default=0.8, help="seconds between demo moves")
    args = parser.parse_args()

    store = EventStore(args.db)
    app = create_app(store)

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
