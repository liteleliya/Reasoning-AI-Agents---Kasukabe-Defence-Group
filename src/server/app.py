"""FastAPI app: REST reads of the log and a WebSocket that streams events live (C1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from blackboard import BoardState, EventStore
from protocol import Event, classify

UI_DIST = Path(__file__).resolve().parents[2] / "ui" / "dist"


def state_summary(state: BoardState) -> dict[str, Any]:
    report = classify(state.events)
    return {
        "session_id": state.session_id,
        "seq": state.seq,
        "agents": state.agents,
        "predictions": state.predictions,
        "terminated": state.terminated,
        "stop_reason": state.stop_reason,
        "open_rollback": state.open_rollback,
        "tokens": {
            "in": state.tokens_in,
            "out": state.tokens_out,
            "rollback_in": state.rollback_tokens_in,
            "rollback_out": state.rollback_tokens_out,
            "total": state.total_tokens,
        },
        "intelligibility": {
            "label": report.label.value,
            "revises": report.revises,
            "pairs": [
                {
                    "sender": p.sender,
                    "receiver": p.receiver,
                    "tags": list(p.tags),
                    "one_way": p.one_way,
                }
                for p in report.pairs
            ],
        },
    }


def create_app(store: EventStore, serve_ui: bool = True) -> FastAPI:
    app = FastAPI(title="Intelligible Blackboard")
    app.state.store = store

    def known(session_id: str) -> None:
        if store.state(session_id).seq < 0:
            raise HTTPException(404, f"no session {session_id!r}")

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        out = []
        for sid in store.sessions():
            s = store.state(sid)
            out.append(
                {
                    "session_id": sid,
                    "seq": s.seq,
                    "agents": s.agents,
                    "terminated": s.terminated,
                    "stop_reason": s.stop_reason,
                }
            )
        return out

    @app.get("/api/sessions/{session_id}/events")
    def events(session_id: str, upto: int | None = Query(None, ge=0)) -> list[dict[str, Any]]:
        known(session_id)
        return [e.to_record() for e in store.events(session_id, upto)]

    @app.get("/api/sessions/{session_id}/snapshot")
    def snapshot(session_id: str, at: int | None = Query(None, ge=0)) -> dict[str, Any]:
        known(session_id)
        return state_summary(store.snapshot(session_id, at))

    @app.websocket("/ws")
    async def stream(ws: WebSocket, session_id: str | None = None, from_seq: int = 0) -> None:
        """Send stored events (seq >= from_seq), then every new event as it is appended.

        Frames: {"type": "event", "event": <record>}. Without session_id, all sessions stream.
        """
        await ws.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event] = asyncio.Queue()

        def on_event(e: Event) -> None:
            if session_id is None or e.session_id == session_id:
                loop.call_soon_threadsafe(queue.put_nowait, e)

        unsubscribe = store.subscribe(on_event)  # subscribe first so nothing is missed
        sent: dict[str, int] = {}
        try:
            for sid in [session_id] if session_id else store.sessions():
                for e in store.events(sid):
                    if e.seq >= from_seq:
                        await ws.send_json({"type": "event", "event": e.to_record()})
                        sent[sid] = e.seq
            await ws.send_json({"type": "synced"})
            while True:
                e = await queue.get()
                if e.seq <= sent.get(e.session_id, -1) or e.seq < from_seq:
                    continue  # already sent in the backlog
                await ws.send_json({"type": "event", "event": e.to_record()})
                sent[e.session_id] = e.seq
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    if serve_ui and UI_DIST.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    return app
