from datetime import date

import pytest

from precept import catalog
from precept.models import (
    CheckKind, Condition, Decision, Determinism, EnforcementTier, GroundedSignals,
    HookEvent, Lesson, Match, MatchOp, MaybeLesson, Origin, Policy, Scope,
    resolve_decisions,
)


def _single_call_policy() -> Policy:
    return Policy(
        id="p1", lesson_id="use-pnpm", enforcement_tier=EnforcementTier.HARD,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.DENY, message="Use pnpm, not npm.",
        match=Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.CONTAINS, value="npm install")]),
    )


def test_lesson_card_roundtrip():
    le = Lesson(
        id="use-pnpm", created=date(2026, 6, 26), origin=Origin.CORRECTION,
        source_session="sess-1", determinism=Determinism.DETERMINISTIC,
        trigger="installing node deps", what_was_wrong="ran npm install",
        what_to_do_instead="use pnpm install", origin_quote="never use npm, use pnpm",
        signals=GroundedSignals(has_verbatim_quote=True, imperative_correction=True),
        policies=[_single_call_policy()],
    )
    back = catalog.parse(catalog.render(le))
    assert back.model_dump(mode="json") == le.model_dump(mode="json")
    assert back.policies[0].match.conditions[0].value == "npm install"


def test_decision_precedence_is_order_independent():
    assert resolve_decisions([Decision.ALLOW, Decision.DENY, Decision.ASK]) == Decision.DENY
    assert resolve_decisions([Decision.ASK, Decision.ALLOW]) == Decision.ASK
    assert resolve_decisions([]) == Decision.ALLOW  # no match -> proceed


def test_trajectory_policy_requires_spec():
    with pytest.raises(ValueError):
        Policy(id="x", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.STOP, check_kind=CheckKind.TRAJECTORY,
               message="m")  # missing trajectory


def test_hard_enforcement_only_on_blockable_events():
    with pytest.raises(ValueError):
        Policy(id="x", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.POST_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
               message="m", match=Match(tool="Bash"))


def test_grounded_confidence_score():
    assert GroundedSignals(human_kept=False).score() == 0.0
    full = GroundedSignals(has_verbatim_quote=True, imperative_correction=True,
                           deterministic_by_construction=True, human_kept=True, fire_count=3)
    assert full.score() == 1.0


def test_maybe_lesson_consistency():
    with pytest.raises(ValueError):
        MaybeLesson(chain_of_thought="...", is_lesson=True, lesson=None)


def test_repo_scope_requires_scope_value():
    with pytest.raises(ValueError):
        Policy(id="x", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
               decision=Decision.DENY, message="m", match=Match(tool="Bash"),
               scope=Scope.REPO)  # no scope_value


def test_global_scope_rejects_scope_value():
    with pytest.raises(ValueError):
        Policy(id="x", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
               decision=Decision.DENY, message="m", match=Match(tool="Bash"),
               scope=Scope.GLOBAL, scope_value="/x")


def test_permission_rule_only_on_deny_ask_pretooluse():
    # valid: a deny PreToolUse single_call carrying a permission_rule
    Policy(id="ok", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
           hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
           decision=Decision.DENY, message="m", match=Match(tool="Read"),
           permission_rule="Read(.env)")
    # invalid: a rewrite cannot be a permission rule
    with pytest.raises(ValueError):
        Policy(id="bad", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
               decision=Decision.REWRITE, message="m", match=Match(tool="Read"),
               rewrite_to={"file_path": "x"}, permission_rule="Read(.env)")
    # invalid: a Stop policy cannot be a permission rule
    with pytest.raises(ValueError):
        Policy(id="bad2", lesson_id="l", enforcement_tier=EnforcementTier.HARD,
               hook_event=HookEvent.STOP, check_kind=CheckKind.JUDGMENT,
               decision=Decision.DENY, message="m", judgment_prompt="p",
               permission_rule="Read(.env)")


def test_repo_scoped_policy_roundtrips_through_catalog():
    le = Lesson(
        id="use-pnpm-here", created=date(2026, 6, 29), origin=Origin.CORRECTION,
        source_session="s", scope=Scope.REPO, scope_value="/work/myrepo",
        determinism=Determinism.DETERMINISTIC, trigger="t", what_was_wrong="w",
        what_to_do_instead="use pnpm",
        policies=[Policy(
            id="p", lesson_id="use-pnpm-here", enforcement_tier=EnforcementTier.HARD,
            hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
            decision=Decision.DENY, message="m", match=Match(tool="Bash"),
            scope=Scope.REPO, scope_value="/work/myrepo")],
    )
    back = catalog.parse(catalog.render(le))
    assert back.model_dump(mode="json") == le.model_dump(mode="json")
