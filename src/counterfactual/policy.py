"""Small, auditable online memory for counterfactual explanation strategies.

The reward is only reduction in disagreement on a matched/local replay. It is not an answer
correctness signal. Policy state is isolated by experiment condition and persisted to JSON so a
resumed run retains its learning history.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from threading import RLock

STRATEGIES = ("cite_constraint", "reconcile_claims", "test_counterexample")


class PolicyMemory:
    """Deterministic UCB-style strategy selector with idempotent, crash-safe observations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            if self._data.get("schema") != 1:
                raise ValueError(f"unsupported policy memory schema in {self.path}")
        else:
            self._data = {"schema": 1, "conditions": {}, "observations": []}
            self._save()
        self._observed = {row["id"] for row in self._data["observations"]}

    def choose(self, condition: str) -> str:
        """Choose each strategy once first, then the strategy with highest UCB score."""
        with self._lock:
            stats = self._condition(condition)
            for strategy in STRATEGIES:
                if stats[strategy]["n"] == 0:
                    return strategy
            total = sum(stats[s]["n"] for s in STRATEGIES)
            return max(
                STRATEGIES,
                key=lambda s: (
                    stats[s]["reward_sum"] / stats[s]["n"]
                    + math.sqrt(2 * math.log(total) / stats[s]["n"]),
                    -STRATEGIES.index(s),
                ),
            )

    def update(
        self, condition: str, strategy: str, credit_delta: float, observation_id: str
    ) -> bool:
        """Record one replay reward; return False for an already-seen observation ID."""
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown counterfactual strategy {strategy!r}")
        if not math.isfinite(credit_delta):
            raise ValueError("credit_delta must be finite")
        with self._lock:
            if observation_id in self._observed:
                return False
            reward = max(0.0, min(1.0, -credit_delta))
            stats = self._condition(condition)[strategy]
            stats["n"] += 1
            stats["reward_sum"] = round(stats["reward_sum"] + reward, 8)
            self._data["observations"].append(
                {
                    "id": observation_id,
                    "condition": condition,
                    "strategy": strategy,
                    "credit_delta": round(credit_delta, 8),
                    "reward": round(reward, 8),
                }
            )
            self._observed.add(observation_id)
            self._save()
            return True

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def _condition(self, name: str) -> dict:
        return self._data["conditions"].setdefault(
            name,
            {strategy: {"n": 0, "reward_sum": 0.0} for strategy in STRATEGIES},
        )

    def _save(self) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)
