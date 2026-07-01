"""UserPromptSubmit prompt-time rules (item D): deterministic presence rules,
judgment rules, scope filtering, fail-open, the adapter wire shapes, and install."""

from precept import enforce, install
from precept.adapters import claude_code as cc

_TICKET = {
    "id": "ticket", "lesson_id": "include-ticket", "enforcement_tier": "hard",
    "hook_event": "UserPromptSubmit", "check_kind": "single_call", "decision": "deny",
    "message": "Include the ticket id (e.g. ABC-123).",
    "match": {"tool": "UserPromptSubmit", "conditions": [
        {"field": "prompt", "op": "not_regex", "value": "[A-Z]+-[0-9]+"}]},
}

_JUDGE = {
    "id": "pj", "lesson_id": "be-specific", "enforcement_tier": "hard",
    "hook_event": "UserPromptSubmit", "check_kind": "judgment", "decision": "deny",
    "message": "Say which environment.", "judgment_prompt": "does the prompt name the env?",
}


def test_blocks_when_required_pattern_absent():
    out = enforce.evaluate_userpromptsubmit({"prompt": "fix the bug"}, [_TICKET])
    assert out["decision"] == "block"
    assert "ticket" in out["reason"].lower()


def test_allows_when_present():
    assert enforce.evaluate_userpromptsubmit({"prompt": "fix ABC-123 bug"}, [_TICKET]) == {}


def test_allows_when_no_prompt_rules():
    assert enforce.evaluate_userpromptsubmit({"prompt": "anything"}, []) == {}


def test_fails_open_on_no_policies():
    # a malformed/empty event with no policies in play -> allow (never wedge).
    assert enforce.evaluate_userpromptsubmit({}, []) == {}


def test_judgment_fails_open_on_none_verdict():
    # a judgment prompt rule whose verdict call hiccups (None) must NOT erase the prompt.
    assert enforce.evaluate_userpromptsubmit(
        {"prompt": "deploy"}, [_JUDGE], verdict_fn=lambda q, c: None
    ) == {}


def test_scope_filter_on_prompt_rule():
    repo = {**_TICKET, "scope": "repo", "scope_value": "/work/myrepo"}
    # cwd outside the repo -> rule not applied -> allow despite the missing ticket
    assert enforce.evaluate_userpromptsubmit(
        {"prompt": "fix the bug", "cwd": "/elsewhere"}, [repo]
    ) == {}


_CONTEXT_FP = {
    "id": "fp", "lesson_id": "explain-first-principles", "enforcement_tier": "soft",
    "hook_event": "UserPromptSubmit", "check_kind": "single_call", "decision": "context",
    "message": "Explain from first principles: define every term before using it.",
    "match": {"tool": "UserPromptSubmit", "conditions": [
        {"field": "prompt", "op": "regex", "value": "(?i)\\bexplain\\b"}]},
}


def test_context_rule_injects_message_on_match():
    out = enforce.evaluate_userpromptsubmit({"prompt": "explain how hooks work"}, [_CONTEXT_FP])
    assert out.get("decision") != "block"
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "first principles" in ctx


def test_context_rule_silent_when_no_match():
    # a prompt with no explanation keyword injects nothing -> plain allow.
    assert enforce.evaluate_userpromptsubmit({"prompt": "run the tests"}, [_CONTEXT_FP]) == {}


def test_block_wins_over_context_injection():
    # a matching deny rule still blocks even when a context rule also matched.
    out = enforce.evaluate_userpromptsubmit(
        {"prompt": "explain the bug"}, [_CONTEXT_FP, _TICKET]
    )
    assert out["decision"] == "block"


def test_judgment_prompt_rule_uses_verdict_fn():
    blocked = enforce.evaluate_userpromptsubmit(
        {"prompt": "deploy it"}, [_JUDGE], verdict_fn=lambda q, c: {"pj": {"ok": False, "reason": "no env"}}
    )
    assert blocked["decision"] == "block"
    assert enforce.evaluate_userpromptsubmit(
        {"prompt": "deploy to staging"}, [_JUDGE], verdict_fn=lambda q, c: {"pj": {"ok": True}}
    ) == {}


def test_additional_context_shape():
    out = cc.userpromptsubmit_context("remember the ticket")
    assert out == {"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": "remember the ticket"}}
    assert cc.userpromptsubmit_block("nope") == {"decision": "block", "reason": "nope"}
    assert cc.userpromptsubmit_allow() == {}


def test_not_regex_op():
    # the new _check op: True when the pattern is ABSENT
    assert enforce._check("fix the bug", "not_regex", "[A-Z]+-[0-9]+") is True
    assert enforce._check("fix ABC-123", "not_regex", "[A-Z]+-[0-9]+") is False


def test_install_registers_userpromptsubmit():
    import os

    s = install.apply_install({})
    names = [os.path.basename(h.get("command", ""))
             for entries in s.get("hooks", {}).values()
             for e in entries for h in e.get("hooks", [])]
    assert "precept-hook-userpromptsubmit" in names  # absolute path now (item 2)
    assert "UserPromptSubmit" in s["hooks"]


def test_install_strip_removes_userpromptsubmit():
    restored = install.strip_precept(install.apply_install({}))
    assert "hooks" not in restored or "UserPromptSubmit" not in restored.get("hooks", {})
