"""Eval-harness tests. The golden-set assertions ARE the deterministic guarantee:
if a refactor regresses enforcement, these fail in CI."""

import pytest

from precept.evals import harness
from precept.evals.live import paired_delta


def test_golden_set_is_perfect_on_the_deterministic_subset():
    rep, rows = harness.run_golden()
    assert rep.n == 14
    assert rep.recall == 1.0, [r for r in rows if r["outcome"].startswith("FN")]
    assert rep.false_block_rate == 0.0, [r for r in rows if r["outcome"].startswith("FP")]
    assert rep.precision == 1.0 and rep.accuracy == 1.0


def test_harness_detects_a_missed_violation():
    # an empty policy set means the violation is NOT blocked -> a false negative
    case = {"id": "x", "kind": "pretooluse", "policies": [],
            "call": {"tool_name": "Bash", "tool_input": {"command": "npm install x"}}, "expect": "block"}
    rep, _ = harness.run([case])
    assert rep.fn == 1 and rep.recall == 0.0


def test_harness_detects_a_false_block():
    pol = {"id": "p", "lesson_id": "l", "enforcement_tier": "hard", "hook_event": "PreToolUse",
           "check_kind": "single_call", "decision": "deny", "message": "m",
           "match": {"tool": "Bash", "conditions": []}}  # matches ANY Bash call
    case = {"id": "x", "kind": "pretooluse", "policies": [pol],
            "call": {"tool_name": "Bash", "tool_input": {"command": "ls"}}, "expect": "allow"}
    rep, _ = harness.run([case])
    assert rep.fp == 1 and rep.false_block_rate == 1.0


def test_paired_delta_reports_mean_and_ci():
    out = paired_delta(without_vals=[0.7, 0.6, 0.7, 0.8], with_vals=[1.0, 1.0, 1.0, 1.0])
    assert out["n"] == 4
    assert 0.2 < out["mean_delta"] < 0.4  # ~0.3 improvement
    assert out["ci95_halfwidth"] >= 0.0


def test_paired_delta_rejects_mismatched_input():
    with pytest.raises(ValueError):
        paired_delta([0.7], [1.0, 1.0])
