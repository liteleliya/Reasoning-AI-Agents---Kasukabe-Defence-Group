"""Counterfactual sandbox and credit assignment.

Replays an altered past message in isolation and returns a credit delta (B4); counterfactual
agents use it to decide how to act next (B6).
"""

from counterfactual.credit import CounterfactualAgent, CreditLog, replay_target
from counterfactual.sandbox import Alternative, ReplayResult, replay

__all__ = [
    "Alternative",
    "CounterfactualAgent",
    "CreditLog",
    "ReplayResult",
    "replay",
    "replay_target",
]
