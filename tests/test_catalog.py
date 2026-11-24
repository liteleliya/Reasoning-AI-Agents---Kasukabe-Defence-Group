"""The session list needs to know which case, condition and seed a session belongs to."""

from pathlib import Path

import pytest

from server.catalog import describe_session, load_metrics_index

LAW = "Data2/Law/Single-choice/complex#2534"


def test_a_trial_key_names_its_case_condition_and_seed() -> None:
    d = describe_session(f"j3_prelim_hot-cf2|mscore|{LAW}|1")
    assert (d["case_id"], d["condition"], d["seed"]) == (LAW, "j3_prelim_hot-cf2", 1)
    assert d["label"] == "Law complex #2534"
    assert d["source"] == "" and d["correct"] is None and d["enabled_agents"] is None


def test_a_retry_suffix_does_not_change_the_case() -> None:
    d = describe_session(f"j3_prelim_hot-cf0|mscore|{LAW}|0~r1")
    assert (d["case_id"], d["seed"]) == (LAW, 0)


def test_fixture_sessions_are_arms_of_one_case() -> None:
    off = describe_session("toy-recovery-xy-off")
    on = describe_session("toy-recovery-xy-on")
    assert (off["case_id"], off["condition"]) == ("toy-recovery-xy", "off")
    assert (on["case_id"], on["condition"]) == ("toy-recovery-xy", "on")
    assert off["label"] == "toy-recovery-xy" and off["seed"] is None


def test_an_unrecognised_id_is_its_own_case() -> None:
    d = describe_session("demo-impasse", source="demo")
    assert (d["case_id"], d["label"], d["condition"], d["seed"]) == (
        "demo-impasse",
        "demo-impasse",
        None,
        None,
    )
    assert d["source"] == "demo"


def test_run_metrics_fill_in_what_the_id_cannot_say() -> None:
    row = {
        "instance_id": LAW,
        "config": "j3_prelim_hot-cf2",
        "seed": "0",
        "n_agents": "3",
        "n_counterfactual": "2",
        "correct": "False",
        "model": "qwen",
    }
    d = describe_session("anything", row, source="J3")
    assert (d["case_id"], d["condition"], d["seed"]) == (LAW, "j3_prelim_hot-cf2", 0)
    assert (d["enabled_agents"], d["n_agents"], d["correct"], d["source"]) == (2, 3, False, "J3")
    assert describe_session("x", {**row, "correct": ""})["correct"] is None
    assert describe_session("x", {**row, "correct": "True"})["correct"] is True


def test_the_metrics_index_is_keyed_by_session_id(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    path.write_text("session_id,instance_id,correct\ns1,q1,True\ns2,q2,\n")
    index = load_metrics_index(path)
    assert set(index) == {"s1", "s2"} and index["s1"]["instance_id"] == "q1"
    with pytest.raises(FileNotFoundError):
        load_metrics_index(tmp_path / "missing.csv")


def test_the_metrics_index_reads_utf8_content(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    path.write_text(
        "session_id,instance_id,answer\n"
        "s1,q1,设计紧急情况下的安全辅助系统\n",
        encoding="utf-8",
    )

    index = load_metrics_index(path)
    assert index["s1"]["answer"] == "设计紧急情况下的安全辅助系统"


def test_the_metrics_index_accepts_a_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    path.write_text(
        "\ufeffsession_id,instance_id,correct\ns1,q1,True\n",
        encoding="utf-8",
    )

    index = load_metrics_index(path)
    assert index["s1"]["instance_id"] == "q1"
