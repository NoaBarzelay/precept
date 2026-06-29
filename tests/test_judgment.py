"""Judgment-rule tests: the verdict model, the enforce gate (block/allow/fail-open),
and deterministic judgment-policy synthesis — all without a network call."""

from datetime import date

from precept import enforce, synthesize
from precept.judge import (
    ConsolidatedVerdict, Question, QuestionVerdict, Verdict,
    consolidated_verdict, verdict,
)
from precept.models import CheckKind, Determinism, HookEvent, Lesson, Origin


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


JUDGMENT_POLICY = {
    "id": "j", "lesson_id": "no-stubs", "enforcement_tier": "hard",
    "hook_event": "Stop", "check_kind": "judgment", "decision": "deny",
    "message": "Don't leave stub implementations.", "judgment_prompt": "no stub/TODO code left",
}

TRANSCRIPT = [{"message": {"role": "assistant", "content": [{"type": "text", "text": "Done — left a TODO stub in parser.py."}]}}]

# A judgment policy gated to fire only when an Edit happened this turn.
JUDGMENT_POLICY_GATED = {
    **JUDGMENT_POLICY, "applies_when": {"tool": "Edit", "conditions": []},
}
EDIT_TRANSCRIPT = [
    {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "parser.py", "old_string": "a", "new_string": "# TODO"}}]}},
    {"message": {"role": "assistant", "content": [{"type": "text", "text": "Left a TODO stub."}]}},
]


def test_verdict_parses_and_fails_open():
    v = verdict("rule", "ctx", client=FakeClient(Verdict(reasoning="r", ok=False, reason="stub")))
    assert v.ok is False and v.reason == "stub"
    assert verdict("rule", "ctx", client=FakeClient(raises=True)) is None  # fail open


def test_consolidated_verdict_parses_and_fails_open():
    parsed = ConsolidatedVerdict(reasoning="r", verdicts=[QuestionVerdict(id="a", ok=False, reason="x")])
    out = consolidated_verdict([Question(id="a", kind="standard", prompt="p")], "ctx", client=FakeClient(parsed))
    assert out["a"].ok is False and out["a"].reason == "x"
    # a failing client -> None (fail open)
    assert consolidated_verdict([Question(id="a", kind="standard", prompt="p")], "ctx", client=FakeClient(raises=True)) is None
    # no questions -> empty map, no client touched
    assert consolidated_verdict([], "ctx", client=FakeClient(raises=True)) == {}


def test_enforce_blocks_on_negative_verdict():
    out = enforce.evaluate_stop_entries(
        TRANSCRIPT, [JUDGMENT_POLICY],
        verdict_fn=lambda q, c: {"j": {"ok": False, "reason": "stub left"}},
    )
    assert out.get("decision") == "block"
    assert "stub" in out["reason"].lower()


def test_enforce_allows_on_positive_verdict():
    assert enforce.evaluate_stop_entries(
        TRANSCRIPT, [JUDGMENT_POLICY], verdict_fn=lambda q, c: {"j": {"ok": True}}
    ) == {}


def test_enforce_fails_open_when_judge_unavailable():
    assert enforce.evaluate_stop_entries(
        TRANSCRIPT, [JUDGMENT_POLICY], verdict_fn=lambda q, c: None
    ) == {}


def test_judgment_applies_when_skips_for_free():
    # gate requires an Edit; TRANSCRIPT has none -> rule skipped, model never called.
    def _boom(q, c):
        raise AssertionError("verdict_fn must not be called when applies_when does not match")

    assert enforce.evaluate_stop_entries(TRANSCRIPT, [JUDGMENT_POLICY_GATED], verdict_fn=_boom) == {}


def test_judgment_applies_when_fires_when_relevant():
    out = enforce.evaluate_stop_entries(
        EDIT_TRANSCRIPT, [JUDGMENT_POLICY_GATED],
        verdict_fn=lambda q, c: {"j": {"ok": False, "reason": "stub"}},
    )
    assert out.get("decision") == "block"


# A trajectory rule and a judgment rule that BOTH need asking on the same turn.
_TRAJ = {
    "id": "t", "lesson_id": "tests-first", "enforcement_tier": "hard",
    "hook_event": "Stop", "check_kind": "trajectory", "message": "Run tests first.",
    "trajectory": {"requires": {"tool": "Bash", "conditions": [{"field": "command", "op": "regex", "value": "pytest"}]}},
}


def test_mixed_trajectory_and_judgment_use_one_call_with_relevance_gate():
    # On an Edit turn with no pytest run: the trajectory rule is unmet (-> claim
    # question) AND the gated judgment rule is relevant (Edit happened -> standard
    # question). Both must ride a SINGLE consolidated verdict call; an irrelevant
    # judgment rule (applies_when not matched) generates no question at all.
    irrelevant = {**JUDGMENT_POLICY, "id": "irrel", "applies_when": {"tool": "WebFetch", "conditions": []}}
    calls: list = []

    def vf(questions, context):
        calls.append(questions)
        return {q["id"]: {"ok": True} for q in questions}

    out = enforce.evaluate_stop_entries(
        EDIT_TRANSCRIPT, [_TRAJ, JUDGMENT_POLICY_GATED, irrelevant], verdict_fn=vf
    )
    assert out == {}
    assert len(calls) == 1  # exactly one consolidated call
    ids = {q["id"] for q in calls[0]}
    assert ids == {"t", "j"}  # traj + relevant judgment only; "irrel" was free-skipped
    kinds = {q["id"]: q["kind"] for q in calls[0]}
    assert kinds["t"] == "claim" and kinds["j"] == "standard"


def test_judgment_lesson_compiles_without_an_llm():
    le = Lesson(
        id="no-stubs", created=date(2026, 6, 27), origin=Origin.CORRECTION, source_session="s",
        determinism=Determinism.JUDGMENT, trigger="finishing a task",
        what_was_wrong="left stub functions", what_to_do_instead="finish every function, no stubs",
    )
    # a client that would raise if used — proves judgment synthesis needs no model call
    synthesize.compile_lesson(le, client=FakeClient(raises=True))
    assert len(le.policies) == 1
    assert le.policies[0].check_kind == CheckKind.JUDGMENT
    assert le.policies[0].hook_event == HookEvent.STOP
    assert "no stubs" in le.policies[0].judgment_prompt
