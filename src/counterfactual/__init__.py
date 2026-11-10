"""Counterfactual sandbox and credit assignment.

Replays an altered past message in isolation and returns a credit delta (B4); counterfactual
agents use it to decide how to act next (B6).
"""

from counterfactual.branches import BranchRun, PairResult, replay_pair
from counterfactual.credit import (
    Candidate,
    CounterfactualAgent,
    CreditLog,
    ReplayAttempt,
    attempt_replay,
    generate_candidate,
    replay_target,
)
from counterfactual.sandbox import Alternative, ReplayResult, replay

__all__ = [
    "Alternative",
    "BranchRun",
    "Candidate",
    "CounterfactualAgent",
    "CreditLog",
    "PairResult",
    "ReplayAttempt",
    "ReplayResult",
    "attempt_replay",
    "generate_candidate",
    "replay",
    "replay_pair",
    "replay_target",
]
