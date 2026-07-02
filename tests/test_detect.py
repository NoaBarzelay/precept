"""DETECT tests — orchestration, provenance, abstain, and fail-closed — all
without a network call (the Anthropic client is faked)."""

import json


from precept import detect
from precept.models import (
    ArtifactType, Determinism, Durability, ExtractedLesson, MaybeLesson, Scope, Status,
)


class _FakeMessages:
    def __init__(self, parsed=None, raises=False):
        self._parsed, self._raises = parsed, raises

    def parse(self, **kwargs):
        if self._raises:
            raise RuntimeError("network down")
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed=None, raises=False):
        self.messages = _FakeMessages(parsed, raises)


def _maybe_lesson() -> MaybeLesson:
    return MaybeLesson(
        chain_of_thought="user said never npm; that's a durable correction",
        is_lesson=True,
        lesson=ExtractedLesson(
            trigger="installing node dependencies",
            what_was_wrong="agent ran npm install",
            what_to_do_instead="use pnpm install",
            origin_quote="never use npm, use pnpm",
            scope=Scope.LANGUAGE, durability=Durability.PERSISTENT,
            determinism=Determinism.DETERMINISTIC, proposed_artifact_type=ArtifactType.RULE,
        ),
    )


def _transcript(tmp_path, turns):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps({"message": {"role": "user", "content": t}}) for t in turns))
    return str(p)


def test_detect_mints_pending_lesson(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))  # isolate cursor/lock
    tp = _transcript(tmp_path, ["never use npm, use pnpm"])
    minted = detect.detect_from_transcript(tp, session="s1", client=FakeClient(_maybe_lesson()))
    assert len(minted) == 1
    le = minted[0]
    assert le.status == Status.PENDING  # never auto-active
    assert le.origin_quote == "never use npm, use pnpm"
    assert le.signals.has_verbatim_quote and le.signals.imperative_correction
    assert le.policies == []  # matcher synthesis is COMPILE's job


def test_detect_abstains(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))  # isolate cursor/lock
    # "no, that's wrong" trips the pre-filter so the classifier (which abstains) is reached.
    tp = _transcript(tmp_path, ["no, that looks wrong"])
    abstain = MaybeLesson(chain_of_thought="just praise", is_lesson=False, abstain_reason="no correction")
    assert detect.detect_from_transcript(tp, client=FakeClient(abstain)) == []


def test_classify_fails_closed_on_error():
    out = detect.classify("anything", client=FakeClient(raises=True))
    assert out.is_lesson is False
    assert "fail-closed" in (out.abstain_reason or "")


def test_provenance_gate_ignores_empty_transcript(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))  # isolate cursor/lock
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert detect.detect_from_transcript(str(p), client=FakeClient(_maybe_lesson())) == []
