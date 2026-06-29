"""End-to-end COMPILE routing — the cross-module seams the per-module tests don't
exercise: a single `compile_all` pass over a mixed catalog must split a clean ban
(-> native settings.json permissions.deny) from a Bash-arg ban (-> hook cache),
idempotently, while preserving the user's own permission rules; and a synthesized
rewrite must travel from the model draft all the way to a PreToolUse `updatedInput`.
All offline (faked synthesizer client; isolated $PRECEPT_CLAUDE_HOME/$STATE_DIR)."""

import json
from datetime import date

import pytest

from precept import compile as compile_mod
from precept import enforce, install, paths, synthesize
from precept.models import (
    CheckKind, Condition, Decision, Determinism, EnforcementTier, HookEvent, Lesson,
    Match, MatchOp, Origin, Policy, Status,
)
from precept.synthesize import PolicyDraft


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    home.mkdir()
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(home))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    return home


class _FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed

    def parse(self, **kwargs):
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed):
        self.messages = _FakeMessages(parsed)


def _active_lesson(lid: str, *policies: Policy) -> Lesson:
    le = Lesson(
        id=lid, created=date(2026, 6, 29), origin=Origin.CORRECTION, source_session="s",
        determinism=Determinism.DETERMINISTIC, trigger="t", what_was_wrong="w",
        what_to_do_instead="d",
    )
    le.status = Status.ACTIVE
    le.policies = list(policies)
    return le


def _ban(pid: str, lesson_id: str, match: Match, permission_rule=None) -> Policy:
    return Policy(
        id=pid, lesson_id=lesson_id, enforcement_tier=EnforcementTier.HARD,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.DENY, message="blocked", match=match,
        permission_rule=permission_rule,
    )


CLEAN_BAN = _ban(
    "clean", "L1",
    Match(tool="Read", conditions=[Condition(field="file_path", op=MatchOp.GLOB, value=".env")]),
    permission_rule="Read(.env)",
)
BASH_ARG_BAN = _ban(
    "basharg", "L2",
    Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.REGEX, value=r"\brm -rf")]),
)


def _settings() -> dict:
    return json.loads(install.settings_path().read_text(encoding="utf-8"))


def _cache() -> list:
    return json.loads(paths.policies_cache().read_text(encoding="utf-8"))


def test_compile_all_splits_clean_ban_to_settings_and_basharg_to_hook(isolated):
    # ONE compile pass over a mixed catalog: the clean tool+path ban becomes a native
    # permissions.deny entry; the Bash-arg ban (CC ignores Bash arg-patterns) stays a
    # hook in the runtime cache. This is the item-B contract end to end.
    n = compile_mod.compile_all([_active_lesson("L1", CLEAN_BAN), _active_lesson("L2", BASH_ARG_BAN)])

    assert _settings()["permissions"]["deny"] == ["Read(.env)"]
    cache_ids = [p["id"] for p in _cache()]
    assert cache_ids == ["basharg"]  # ONLY the hook rule; the clean ban is not double-enforced
    assert n == 2  # 1 hook policy + 1 permission string

    # And the cached Bash hook actually fires, while the clean ban does NOT (it lives in
    # settings.json, which enforce.py never reads — proving the routing isn't redundant).
    blocked = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, _cache()
    )
    assert blocked["hookSpecificOutput"]["permissionDecision"] == "deny"
    read_env = enforce.evaluate_pretooluse(
        {"tool_name": "Read", "tool_input": {"file_path": ".env"}}, _cache()
    )
    assert read_env["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_compile_all_is_idempotent_and_preserves_user_permissions(isolated):
    # The user already has a hand-written deny rule in settings.json.
    install.settings_path().write_text(
        json.dumps({"permissions": {"deny": ["Bash(sudo *)"]}}), encoding="utf-8"
    )
    compile_mod.compile_all([_active_lesson("L1", CLEAN_BAN)])
    deny = _settings()["permissions"]["deny"]
    assert "Bash(sudo *)" in deny  # the user's own rule survives the sync
    assert "Read(.env)" in deny  # ours is added

    # Re-compiling the same catalog is byte-for-byte stable (the dedup + sort in
    # compile_all + the sidecar manifest make the settings write idempotent).
    first = install.settings_path().read_text(encoding="utf-8")
    compile_mod.compile_all([_active_lesson("L1", CLEAN_BAN)])
    assert install.settings_path().read_text(encoding="utf-8") == first


def test_recompile_without_lesson_strips_managed_deny_but_keeps_user_rule(isolated):
    install.settings_path().write_text(
        json.dumps({"permissions": {"deny": ["Bash(sudo *)"]}}), encoding="utf-8"
    )
    compile_mod.compile_all([_active_lesson("L1", CLEAN_BAN)])
    assert "Read(.env)" in _settings()["permissions"]["deny"]

    # The lesson is gone (deleted/archived) -> recompiling an empty catalog must remove
    # ONLY Precept's managed string, never the user's.
    compile_mod.compile_all([])
    deny = _settings().get("permissions", {}).get("deny", [])
    assert "Read(.env)" not in deny  # ours is gone
    assert "Bash(sudo *)" in deny  # the user's survives


def test_inactive_lesson_contributes_neither_hook_nor_permission(isolated):
    # A non-ACTIVE lesson is fully inert: no settings.json entry, no cache entry.
    le = _active_lesson("L1", CLEAN_BAN, BASH_ARG_BAN)
    le.status = Status.PENDING
    compile_mod.compile_all([le])
    assert _settings().get("permissions", {}).get("deny", []) == []
    assert _cache() == []


# --- Item A: a synthesized rewrite travels to a PreToolUse updatedInput ------
def _rewrite_draft() -> PolicyDraft:
    return PolicyDraft(
        reasoning="clean whole-field substitution", can_compile=True,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.REWRITE, message="Use pnpm, not npm.",
        rewrite_to={"command": "pnpm install"},
        match=Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.EQUALS, value="npm install")]),
    )


def _sub_lesson() -> Lesson:
    return Lesson(
        id="use-pnpm", created=date(2026, 6, 29), origin=Origin.CORRECTION, source_session="s",
        determinism=Determinism.DETERMINISTIC, trigger="installing deps",
        what_was_wrong="ran npm install", what_to_do_instead="use pnpm install",
    )


def test_npm_to_pnpm_correction_synthesizes_rewrite_then_enforces_updatedinput():
    # The full item-A chain: a substitution correction compiles to decision=rewrite WITH
    # rewrite_to, is NOT classified as a permission rule (a rewrite must stay a hook to
    # transform input), and PreToolUse returns the transformed updatedInput payload.
    p = synthesize.synthesize_policy(_sub_lesson(), client=FakeClient(_rewrite_draft()))
    assert p is not None
    assert p.decision == Decision.REWRITE
    assert p.rewrite_to == {"command": "pnpm install"}
    assert p.permission_rule is None  # a rewrite can't be a native deny entry -> stays a hook

    pol = p.model_dump(mode="json", exclude_none=True)
    out = enforce.evaluate_pretooluse(
        {"tool_name": "Bash", "tool_input": {"command": "npm install"}}, [pol]
    )
    hs = out["hookSpecificOutput"]
    assert hs["permissionDecision"] == "allow"  # a rewrite is an allow + updatedInput, not a block
    assert hs["updatedInput"] == {"command": "pnpm install"}


def test_rewrite_policy_stays_in_hook_cache_not_settings(isolated):
    # A rewrite lesson must end up in the runtime hook cache (so enforce can transform
    # the call) and NEVER in settings.json (which can't rewrite, only allow/deny/ask).
    p = synthesize.synthesize_policy(_sub_lesson(), client=FakeClient(_rewrite_draft()))
    le = _active_lesson("use-pnpm", p)
    compile_mod.compile_all([le])
    assert _settings().get("permissions", {}).get("deny", []) == []
    assert [c["id"] for c in _cache()] == [p.id]
    assert _cache()[0]["rewrite_to"] == {"command": "pnpm install"}
