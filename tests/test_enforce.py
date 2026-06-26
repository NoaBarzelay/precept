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
        "claim_pattern": r"(?i)\b(it works|all set|done|passing|fixed)\b",
    },
}


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


def _transcript(tmp_path, lines):
    import json
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines))
    return str(p)


def test_stop_blocks_success_claim_without_tests(tmp_path):
    tp = _transcript(tmp_path, [
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "All done, it works!"}]}},
    ])
    out = enforce.evaluate_stop({"transcript_path": tp}, [TESTS_BEFORE_DONE])
    assert out.get("decision") == "block"


def test_stop_allows_when_tests_ran(tmp_path):
    tp = _transcript(tmp_path, [
        {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "All done, it works!"}]}},
    ])
    out = enforce.evaluate_stop({"transcript_path": tp}, [TESTS_BEFORE_DONE])
    assert out == {}  # allowed
