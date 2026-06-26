"""Matcher-synthesis tests — the COMPILE step — with a faked model, no network."""

from datetime import date

from precept import synthesize
from precept.models import (
    CheckKind, Condition, Decision, Determinism, EnforcementTier, HookEvent, Lesson,
    Match, MatchOp, Origin,
)
from precept.synthesize import PolicyDraft, validate_match


class _FakeMessages:
    def __init__(self, parsed=None, raises=False):
        self._parsed, self._raises = parsed, raises

    def parse(self, **kwargs):
        if self._raises:
            raise RuntimeError("down")
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed=None, raises=False):
        self.messages = _FakeMessages(parsed, raises)


def _lesson(determinism=Determinism.DETERMINISTIC) -> Lesson:
    return Lesson(
        id="use-pnpm", created=date(2026, 6, 26), origin=Origin.CORRECTION, source_session="s",
        determinism=determinism, trigger="install deps", what_was_wrong="ran npm",
        what_to_do_instead="use pnpm", origin_quote="never npm",
    )


def _ok_draft() -> PolicyDraft:
    return PolicyDraft(
        reasoning="banned command", can_compile=True,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.DENY, message="Use pnpm.",
        match=Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.REGEX, value=r"\bnpm install")]),
    )


def test_synthesizes_hard_policy():
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ok_draft()))
    assert p is not None
    assert p.enforcement_tier == EnforcementTier.HARD
    assert p.match.tool == "Bash"
    assert p.lesson_id == "use-pnpm"


def test_compile_lesson_attaches_policy():
    le = synthesize.compile_lesson(_lesson(), client=FakeClient(_ok_draft()))
    assert len(le.policies) == 1
    assert le.signals.deterministic_by_construction is True


def test_validator_gate_rejects_unknown_tool_and_field():
    assert validate_match(Match(tool="Frobnicate")) is False
    assert validate_match(Match(tool="Bash", conditions=[Condition(field="nope", op=MatchOp.EQUALS, value="x")])) is False
    assert validate_match(Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.EQUALS, value="x")])) is True


def test_cannot_compile_returns_none_and_downgrades_to_soft():
    draft = PolicyDraft(reasoning="stylistic", can_compile=False)
    le = synthesize.compile_lesson(_lesson(), client=FakeClient(draft))
    assert le.policies == []
    assert le.determinism == Determinism.STYLISTIC  # honest downgrade


def test_stylistic_lesson_never_calls_model():
    # raises=True would blow up if the client were used; stylistic short-circuits first
    le = synthesize.compile_lesson(_lesson(Determinism.STYLISTIC), client=FakeClient(raises=True))
    assert le.policies == []
