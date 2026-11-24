"""Persisted strategy learning is deterministic, isolated by condition, and idempotent."""

from counterfactual.policy import STRATEGIES, PolicyMemory


def test_policy_explores_each_strategy_then_reuses_rewarded_strategy(tmp_path) -> None:
    memory = PolicyMemory(tmp_path / "policy.json")
    condition = "density-cf1"
    first = []
    for idx in range(3):
        strategy = memory.choose(condition)
        first.append(strategy)
        memory.update(condition, strategy, 0, f"warmup-{idx}")
    assert first == list(STRATEGIES)
    # New observations carry the stronger reduction reward for one tactic.
    memory.update(condition, first[0], -0.8, "trial-1:4")
    memory.update(condition, first[1], 0.0, "trial-2:4")
    memory.update(condition, first[2], 0.0, "trial-3:4")
    assert memory.choose(condition) == first[0]


def test_policy_persists_condition_isolation_and_duplicate_protection(tmp_path) -> None:
    path = tmp_path / "policy.json"
    memory = PolicyMemory(path)
    assert memory.update("cf1", STRATEGIES[0], -0.25, "trial-1:7")
    assert not memory.update("cf1", STRATEGIES[0], -0.25, "trial-1:7")
    restored = PolicyMemory(path)
    snapshot = restored.snapshot()
    assert snapshot["conditions"]["cf1"][STRATEGIES[0]] == {"n": 1, "reward_sum": 0.25}
    assert "cf1" not in snapshot["conditions"].get("cf2", {})
    assert restored.choose("cf2") == STRATEGIES[0]
