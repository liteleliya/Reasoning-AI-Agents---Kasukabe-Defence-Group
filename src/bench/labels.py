"""Short names for benchmark cases, shared by the server and the run summary."""

from __future__ import annotations


def case_label(case_id: str) -> str:
    """A short readable name: `Data2/Law/Single-choice/complex#2534` becomes `Law complex #2534`."""
    if case_id.startswith("case:"):
        return f"Case {case_id.removeprefix('case:')}"
    left, hash_, number = case_id.partition("#")
    parts = left.split("/")
    if not hash_ or len(parts) < 3:
        return case_id
    return f"{parts[1]} {parts[-1]} #{number}"
