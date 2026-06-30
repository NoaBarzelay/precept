"""Context rules (item A): non-blocking PreToolUse reminders injected as additionalContext.

Two surfaces are covered: the enforce hot path (a matching ALLOW gains additionalContext; a
deny still wins; multiple matches concatenate) and the store/CLI CRUD round-trip."""

import json

import pytest

from precept import context_rules as cr
from precept import enforce
from precept.models import ContextRule

# A deny policy used to prove a block still wins over an also-matching context rule.
DENY_EDIT = {
    "id": "d1", "lesson_id": "no-edit-secrets", "enforcement_tier": "hard",
    "hook_event": "PreToolUse", "check_kind": "single_call", "decision": "deny",
    "message": "Do not edit secrets.",
    "match": {"tool": "Edit", "conditions": [
        {"field": "file_path", "op": "glob", "value": "*/secrets/*"}]},
}

EDIT_PY = {"tool_name": "Edit", "tool_input": {"file_path": "/work/src/app.py"}}


def _rule(rid, tool, text, path=None, op="glob"):
    return {"id": rid, "tool": tool, "path_pattern": path, "path_op": op, "text": text}


def _ctx(out):
    return out["hookSpecificOutput"].get("additionalContext")


def test_context_rule_on_edit_glob_injects_additional_context():
    rules = [_rule("c1", "Edit", "remember to update the changelog", path="*.py")]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _ctx(out) == "remember to update the changelog"


def test_non_matching_call_injects_nothing():
    # tool matches but the path glob doesn't -> no context, plain allow.
    rules = [_rule("c1", "Edit", "py only", path="*.md")]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "additionalContext" not in out["hookSpecificOutput"]


def test_wrong_tool_injects_nothing():
    rules = [_rule("c1", "Write", "write only", path="*.py")]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert "additionalContext" not in out["hookSpecificOutput"]


def test_tool_only_rule_matches_any_path():
    rules = [_rule("c1", "Edit", "any edit reminder")]  # no path_pattern
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert _ctx(out) == "any edit reminder"


def test_deny_still_blocks_even_when_context_rule_matches():
    rules = [_rule("c1", "Edit", "a reminder")]
    event = {"tool_name": "Edit", "tool_input": {"file_path": "/work/secrets/key.py"}}
    out = enforce.evaluate_pretooluse(event, [DENY_EDIT], rules)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    # a block carries no additionalContext (the call never proceeds)
    assert "additionalContext" not in out["hookSpecificOutput"]


def test_multiple_matching_context_rules_concatenate_in_order():
    rules = [
        _rule("c1", "Edit", "first", path="*.py"),
        _rule("c2", "Edit", "second"),  # tool-only, also matches
        _rule("c3", "Write", "ignored"),  # wrong tool
    ]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert _ctx(out) == "first\n\nsecond"


def test_regex_path_op_matches():
    rules = [_rule("c1", "Edit", "regex hit", path=r"\.py$", op="regex")]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert _ctx(out) == "regex hit"


def test_empty_text_rule_is_skipped():
    rules = [_rule("c1", "Edit", "", path="*.py")]
    out = enforce.evaluate_pretooluse(EDIT_PY, [], rules)
    assert "additionalContext" not in out["hookSpecificOutput"]


# --- store / persistence round-trip -----------------------------------------
@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))


def test_store_add_list_remove_roundtrip(isolated):
    assert cr.load() == []
    cr.add(ContextRule(id="r1", tool="Edit", path_pattern="*.py", text="hi"))
    cr.add(ContextRule(id="r2", tool="Bash", text="careful"))
    ids = [r.id for r in cr.load()]
    assert ids == ["r1", "r2"]

    # the on-disk JSON is exactly what enforce.load_context_rules reads (no compile step)
    raw = enforce.load_context_rules()
    assert {r["id"] for r in raw} == {"r1", "r2"}

    assert cr.remove("r1") is True
    assert [r.id for r in cr.load()] == ["r2"]
    assert cr.remove("nope") is False


def test_store_add_replaces_same_id(isolated):
    cr.add(ContextRule(id="r1", tool="Edit", text="old"))
    cr.add(ContextRule(id="r1", tool="Edit", text="new"))
    rules = cr.load()
    assert len(rules) == 1 and rules[0].text == "new"


def test_enforce_reads_authored_rules_from_disk(isolated):
    # End to end: a rule authored via the store is injected by the hot path with NO rules
    # passed in (it loads context_rules_path itself), proving the file IS the contract.
    cr.add(ContextRule(id="r1", tool="Edit", path_pattern="*.py", text="from disk"))
    out = enforce.evaluate_pretooluse(EDIT_PY, [])  # context_rules=None -> loads from disk
    assert _ctx(out) == "from disk"


def test_load_context_rules_fail_open_on_missing_file(isolated):
    assert enforce.load_context_rules() == []
    assert cr.load() == []


def test_malformed_file_is_tolerated(isolated):
    from precept import paths

    paths.precept_home().mkdir(parents=True, exist_ok=True)
    paths.context_rules_path().write_text("{not json", encoding="utf-8")
    assert cr.load() == []
    assert enforce.load_context_rules() == []
    # a JSON object (not a list) is also tolerated
    paths.context_rules_path().write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert enforce.load_context_rules() == []
