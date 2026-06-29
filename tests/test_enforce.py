"""Enforcement-matcher tests — the wedge, exercised end-to-end from policy dicts.
These use the runtime JSON shape (what COMPILE emits), stdlib-only path."""

from precept import enforce

# NB: word-boundary regex, not a naive substring — "npm install" as a substring
# also matches "pnpm install". COMPILE must synthesize boundary-aware matchers.
_NPM = r"\bnpm install"

PNPM = {
    "id": "p1", "lesson_id": "use-pnpm", "enforcement_tier": "hard",
    "hook_event": "PreToolUse", "check_kind": "single_call", "decision": "deny",
    "message": "Use pnpm, not npm.",
    "match": {"tool": "Bash", "conditions": [{"field": "command", "op": "regex", "value": _NPM}]},
}

REWRITE = {
    "id": "p2", "lesson_id": "rw", "enforcement_tier": "hard",
    "hook_event": "PreToolUse", "check_kind": "single_call", "decision": "rewrite",
    "message": "rewriting npm -> pnpm", "rewrite_to": {"command": "pnpm install"},
    "match": {"tool": "Bash", "conditions": [{"field": "command", "op": "regex", "value": _NPM}]},
}

TESTS_BEFORE_DONE = {
    "id": "p3", "lesson_id": "tests-first", "enforcement_tier": "hard",
    "hook_event": "Stop", "check_kind": "trajectory",
    "message": "Run the tests before claiming it works.",
    "trajectory": {
        "requires": {"tool": "Bash", "conditions": [{"field": "command", "op": "regex", "value": "pytest|npm test"}]},
    },
}

_CLAIM = [{"message": {"role": "assistant", "content": [{"type": "text", "text": "All done, it works!"}]}}]
_TESTS_RAN = [
    {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}},
    {"message": {"role": "assistant", "content": [{"type": "text", "text": "All done, it works!"}]}},
]


def test_pretooluse_denies_matching_call():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install left-pad"}}, [PNPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pretooluse_allows_non_matching_call():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "pnpm install"}}, [PNPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_pretooluse_allows_when_no_policies():
    out = enforce.evaluate_pretooluse({"tool_name": "Bash", "tool_input": {"command": "anything"}}, [])
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_deny_wins_over_rewrite_precedence():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install x"}}, [REWRITE, PNPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_rewrite_applies_updated_input():
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install x"}}, [REWRITE]
    )
    assert out["hookSpecificOutput"]["updatedInput"] == {"command": "pnpm install"}


def test_stop_blocks_success_claim_without_tests():
    # requirement unmet -> a 'claim' question is asked; the AI verdict says the
    # agent IS claiming completion (ok=false) -> block.
    out = enforce.evaluate_stop_entries(
        _CLAIM, [TESTS_BEFORE_DONE],
        verdict_fn=lambda q, c: {"p3": {"ok": False, "reason": "claiming done, no tests"}},
    )
    assert out.get("decision") == "block"


def test_stop_allows_when_tests_ran():
    # tests ran -> requirement satisfied -> no question -> fast-path allow, no
    # verdict_fn needed (also proves the deterministic free-skip).
    assert enforce.evaluate_stop_entries(_TESTS_RAN, [TESTS_BEFORE_DONE]) == {}


def test_stop_allows_when_no_claim():
    # same unmet requirement, but the AI verdict says NOT claiming complete -> allow.
    assert enforce.evaluate_stop_entries(
        _CLAIM, [TESTS_BEFORE_DONE], verdict_fn=lambda q, c: {"p3": {"ok": True}}
    ) == {}


def test_stop_fails_open_when_verdict_none():
    # verdict call fails / returns nothing -> FAIL OPEN, never wedge the session.
    assert enforce.evaluate_stop_entries(
        _CLAIM, [TESTS_BEFORE_DONE], verdict_fn=lambda q, c: None
    ) == {}


# A second, independent trajectory rule whose `requires` is ALSO unmet on _CLAIM,
# so two questions are generated this turn (must still be ONE verdict call).
LINT_BEFORE_DONE = {
    "id": "p4", "lesson_id": "lint-first", "enforcement_tier": "hard",
    "hook_event": "Stop", "check_kind": "trajectory",
    "message": "Run the linter before claiming it works.",
    "trajectory": {
        "requires": {"tool": "Bash", "conditions": [{"field": "command", "op": "regex", "value": "ruff|eslint"}]},
    },
}


def test_multiple_questions_go_through_one_consolidated_call():
    # BACKLOG #4/#5 core invariant: when N gate questions need asking this turn, the
    # model is consulted EXACTLY ONCE (a single consolidated verdict), not per-rule.
    calls: list[list[dict]] = []

    def counting_vf(questions, context):
        calls.append(questions)
        return {q["id"]: {"ok": True} for q in questions}

    out = enforce.evaluate_stop_entries(
        _CLAIM, [TESTS_BEFORE_DONE, LINT_BEFORE_DONE], verdict_fn=counting_vf
    )
    assert out == {}  # both verdicts ok -> allow
    assert len(calls) == 1  # ONE call, not one per rule
    assert {q["id"] for q in calls[0]} == {"p3", "p4"}  # both questions in that one call


def test_consolidated_call_blocks_on_first_violation_in_order():
    # Two unmet trajectory rules in one call; the first (trajectory order) that the
    # verdict fails is the one whose message is surfaced.
    calls: list = []

    def vf(questions, context):
        calls.append(questions)
        return {"p3": {"ok": True}, "p4": {"ok": False, "reason": "no lint"}}

    out = enforce.evaluate_stop_entries(
        _CLAIM, [TESTS_BEFORE_DONE, LINT_BEFORE_DONE], verdict_fn=vf
    )
    assert out.get("decision") == "block"
    assert "lint" in out["reason"].lower()
    assert len(calls) == 1  # still exactly one consolidated call


def test_deterministic_stop_path_imports_no_judge_or_anthropic():
    # The fast (all-deterministic) path must NEVER touch the model layer: with the
    # requirement met, no question is generated, so neither `judge` nor `anthropic`
    # is imported and the real `_consolidated_judge` bridge is never reached.
    import sys

    for mod in ("precept.judge", "anthropic"):
        sys.modules.pop(mod, None)
    # No verdict_fn -> would fall back to the real lazy judge IF a question existed.
    out = enforce.evaluate_stop_entries(_TESTS_RAN, [TESTS_BEFORE_DONE])
    assert out == {}
    assert "precept.judge" not in sys.modules
    assert "anthropic" not in sys.modules


# --- Scope-aware enforcement (item C) ---------------------------------------
import os

_REPO_ROOT = os.path.realpath("/work/myrepo") if os.name != "nt" else "C:\\work\\myrepo"
REPO_NPM = {
    **PNPM, "id": "repo-npm", "scope": "repo", "scope_value": _REPO_ROOT,
}


def _bash(command, cwd=None):
    ev = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        ev["cwd"] = cwd
    return ev


def test_repo_scoped_policy_fires_inside_repo():
    out = enforce.evaluate_pretooluse(
        _bash("npm install x", cwd=os.path.join(_REPO_ROOT, "src")), [REPO_NPM]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_repo_scoped_policy_skipped_outside_repo():
    out = enforce.evaluate_pretooluse(_bash("npm install x", cwd="/some/other/dir"), [REPO_NPM])
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_repo_scope_skipped_when_cwd_missing():
    # Inverted fail-open: a repo rule with no cwd can't be placed in its repo -> skip.
    out = enforce.evaluate_pretooluse(_bash("npm install x"), [REPO_NPM])
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_global_policy_fires_with_or_without_cwd():
    assert enforce.evaluate_pretooluse(_bash("npm install x", cwd="/anywhere"), [PNPM])[
        "hookSpecificOutput"]["permissionDecision"] == "deny"
    assert enforce.evaluate_pretooluse(_bash("npm install x"), [PNPM])[
        "hookSpecificOutput"]["permissionDecision"] == "deny"


REPO_TRAJ = {**TESTS_BEFORE_DONE, "id": "repo-traj", "scope": "repo", "scope_value": _REPO_ROOT}


def test_stop_scope_filter_skips_repo_rule_outside_repo():
    # Out of scope -> the rule is filtered before any question -> allow (and no verdict_fn).
    assert enforce.evaluate_stop_entries(
        _CLAIM, [REPO_TRAJ], verdict_fn=lambda q, c: {"repo-traj": {"ok": False}}, cwd="/elsewhere"
    ) == {}


def test_stop_scope_filter_fires_repo_rule_inside_repo():
    out = enforce.evaluate_stop_entries(
        _CLAIM, [REPO_TRAJ], verdict_fn=lambda q, c: {"repo-traj": {"ok": False, "reason": "no tests"}},
        cwd=os.path.join(_REPO_ROOT, "pkg"),
    )
    assert out.get("decision") == "block"
