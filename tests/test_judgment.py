"""Judgment-rule tests: the verdict model, the enforce gate (block/allow/fail-open),
and deterministic judgment-policy synthesis — all without a network call."""

from datetime import date

from precept import enforce, synthesize
from precept.judge import Verdict, verdict
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


def test_verdict_parses_and_fails_open():
    v = verdict("rule", "ctx", client=FakeClient(Verdict(reasoning="r", ok=False, reason="stub")))
    assert v.ok is False and v.reason == "stub"
    assert verdict("rule", "ctx", client=FakeClient(raises=True)) is None  # fail open


def test_enforce_blocks_on_negative_verdict(monkeypatch):
    monkeypatch.setattr(enforce, "_judge", lambda p, c: Verdict(reasoning="r", ok=False, reason="stub left"))
    out = enforce.evaluate_stop_entries(TRANSCRIPT, [JUDGMENT_POLICY])
    assert out.get("decision") == "block"
    assert "stub" in out["reason"].lower()


def test_enforce_allows_on_positive_verdict(monkeypatch):
    monkeypatch.setattr(enforce, "_judge", lambda p, c: Verdict(reasoning="r", ok=True))
    assert enforce.evaluate_stop_entries(TRANSCRIPT, [JUDGMENT_POLICY]) == {}


def test_enforce_fails_open_when_judge_unavailable(monkeypatch):
    monkeypatch.setattr(enforce, "_judge", lambda p, c: None)  # no key / network
    assert enforce.evaluate_stop_entries(TRANSCRIPT, [JUDGMENT_POLICY]) == {}


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
