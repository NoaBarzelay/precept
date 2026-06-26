from datetime import date

import pytest

from precept import catalog
from precept.models import (
    CheckKind, Condition, Decision, Determinism, EnforcementTier, GroundedSignals,
    HookEvent, Lesson, Match, MatchOp, MaybeLesson, Origin, Policy, TrajectorySpec,
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
