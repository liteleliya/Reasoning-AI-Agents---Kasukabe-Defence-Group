"""FastAPI WebSocket server streaming blackboard events to the UI (C1)."""

from server.app import create_app, state_summary

__all__ = ["create_app", "state_summary"]
