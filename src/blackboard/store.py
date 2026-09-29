"""Append-only SQLite event log with a write lock (A2)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from blackboard.state import BoardState
from protocol.schema import Event, EventDraft, Tokens
from protocol.validator import validate

Listener = Callable[[Event], None]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    session_id     TEXT    NOT NULL,
    seq            INTEGER NOT NULL,
    author         TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    tag            TEXT,
    reply_to       INTEGER,
    prediction     TEXT    NOT NULL,
    explanation    TEXT    NOT NULL,
    counterfactual INTEGER NOT NULL,
    tokens_in      INTEGER NOT NULL,
    tokens_out     INTEGER NOT NULL,
    meta           TEXT    NOT NULL,
    PRIMARY KEY (session_id, seq)
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""

_COLUMNS = (
    "session_id, seq, author, kind, tag, reply_to, prediction, explanation, "
    "counterfactual, tokens_in, tokens_out, meta"
)


class EventStore:
    """One SQLite file (or ":memory:") holding the event log of any number of sessions.

    Writes are validated against the session history and serialised by a lock, so `seq` is
    contiguous per session even with concurrent writers. State at any seq is rebuilt from the log.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._states: dict[str, BoardState] = {}
        self._listeners: list[Listener] = []

    # --- writes ---------------------------------------------------------------------------

    def append_sync(self, draft: EventDraft) -> Event:
        """Validate, assign the next seq and persist. Raises ProtocolError if off-protocol."""
        with self._lock:
            state = self.state(draft.session_id)
            warnings = validate(draft, state.events)
            if warnings:
                draft = draft.model_copy(
                    update={"meta": {**draft.meta, "warnings": list(warnings)}}
                )
            event = Event.from_draft(draft, state.seq + 1)
            self._conn.execute(
                f"INSERT INTO events ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                _to_row(event),
            )
            self._states[event.session_id] = state.apply(event)
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)
        return event

    async def append(self, draft: EventDraft) -> Event:
        return await asyncio.to_thread(self.append_sync, draft)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Call `listener(event)` after every append. Returns an unsubscribe function."""
        with self._lock:
            self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # --- reads ----------------------------------------------------------------------------

    def events(self, session_id: str, upto: int | None = None) -> list[Event]:
        """Events of a session in seq order, optionally only those with seq <= upto."""
        sql = f"SELECT {_COLUMNS} FROM events WHERE session_id = ?"
        args: list[object] = [session_id]
        if upto is not None:
            sql += " AND seq <= ?"
            args.append(upto)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY seq", args).fetchall()
        return [_from_row(r) for r in rows]

    def snapshot(self, session_id: str, at_seq: int | None = None) -> BoardState:
        """Board state rebuilt from the log as it was after event `at_seq` (default: latest)."""
        return BoardState.replay(session_id, self.events(session_id, at_seq))

    def state(self, session_id: str) -> BoardState:
        """Current state (cached; identical to `snapshot(session_id)`)."""
        with self._lock:
            if session_id not in self._states:
                self._states[session_id] = self.snapshot(session_id)
            return self._states[session_id]

    def sessions(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT session_id FROM events ORDER BY 1")
            return [r[0] for r in rows.fetchall()]

    def fork(self, session_id: str, upto: int) -> EventStore:
        """An independent in-memory store holding a copy of events 0..upto (for the sandbox)."""
        copy = EventStore()
        with copy._lock:
            for event in self.events(session_id, upto):
                copy._conn.execute(
                    f"INSERT INTO events ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    _to_row(event),
                )
        return copy

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _to_row(e: Event) -> tuple[object, ...]:
    return (
        e.session_id,
        e.seq,
        e.author,
        e.kind.value,
        e.tag.value if e.tag else None,
        e.reply_to,
        e.prediction,
        e.explanation,
        int(e.counterfactual),
        e.tokens.in_,
        e.tokens.out,
        json.dumps(e.meta, sort_keys=True),
    )


def _from_row(r: tuple) -> Event:
    return Event(
        session_id=r[0],
        seq=r[1],
        author=r[2],
        kind=r[3],
        tag=r[4],
        reply_to=r[5],
        prediction=r[6],
        explanation=r[7],
        counterfactual=bool(r[8]),
        tokens=Tokens(in_=r[9], out=r[10]),
        meta=json.loads(r[11]),
    )
