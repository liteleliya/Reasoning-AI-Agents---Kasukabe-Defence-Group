"""Blackboard core: append-only SQLite event log, snapshots at any seq, write lock (A2)."""

from blackboard.state import BoardState
from blackboard.store import EventStore

__all__ = ["BoardState", "EventStore"]
