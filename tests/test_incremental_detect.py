"""Item 1 — incremental on-the-fly detection: cursor advances and skips old turns,
the regex pre-filter gates the LLM call, and the per-session lock prevents a
double-classify. No network (the Anthropic client is faked)."""

import json

from precept import detect, paths
from precept.models import (
    ArtifactType, Determinism, Durability, ExtractedLesson, MaybeLesson, Scope,
)


class _FakeMessages:
    def __init__(self, parsed=None, raises=False):
        self._parsed, self._raises, self.calls = parsed, raises, 0

    def parse(self, **kwargs):
        self.calls += 1
        if self._raises:
            raise RuntimeError("network down")
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed=None, raises=False):
        self.messages = _FakeMessages(parsed, raises)


def _maybe(quote="never use npm, use pnpm") -> MaybeLesson:
    return MaybeLesson(
        chain_of_thought="durable correction",
        is_lesson=True,
        lesson=ExtractedLesson(
            trigger="installing deps", what_was_wrong="ran npm",
            what_to_do_instead="use pnpm install", origin_quote=quote,
            scope=Scope.GLOBAL, durability=Durability.PERSISTENT,
            determinism=Determinism.DETERMINISTIC, proposed_artifact_type=ArtifactType.RULE,
        ),
    )


def _write_turns(path, turns):
    path.write_text("\n".join(
        json.dumps({"message": {"role": "user", "content": t}}) for t in turns
    ))
    return str(path)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))


# --- pre-filter (cost gate) -------------------------------------------------
def test_prefilter_lets_corrections_through_and_drops_noise():
    assert detect.looks_like_correction(["no, never use npm, use pnpm"])
    assert detect.looks_like_correction(["actually, you should have run the tests"])
    assert detect.looks_like_correction(["use rg not grep"])
    # word-boundary anchored: 'no' inside 'notation' / 'another' must not trip it
    assert not detect.looks_like_correction(["please add notation to the diagram"])
    assert not detect.looks_like_correction(["build another parser module"])
    assert not detect.looks_like_correction([])


def test_prefilter_blocks_the_llm_call_on_noise(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tp = _write_turns(tmp_path / "t.jsonl", ["add a feature to the parser please"])
    client = FakeClient(_maybe())
    minted = detect.detect_from_transcript(tp, session_id="s", client=client)
    assert minted == []
    assert client.messages.calls == 0  # the LLM was never called (pure cost gate)


def test_prefilter_admits_a_real_correction(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tp = _write_turns(tmp_path / "t.jsonl", ["never use npm, use pnpm"])
    client = FakeClient(_maybe())
    minted = detect.detect_from_transcript(tp, session_id="s", client=client)
    assert len(minted) == 1
    assert client.messages.calls == 1


# --- cursor (skip already-seen turns) ---------------------------------------
def test_cursor_advances_and_skips_old_turns(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    p = tmp_path / "t.jsonl"
    # First Stop: one benign turn. Cursor should advance past it; no LLM call.
    _write_turns(p, ["let's build the parser"])
    client = FakeClient(_maybe())
    assert detect.detect_from_transcript(str(p), session_id="s", client=client) == []
    assert detect.read_cursor("s") == 1
    assert client.messages.calls == 0

    # Second Stop: the SAME old turn plus a NEW correction. Only the new turn is
    # classified (old one is behind the cursor) -> exactly one LLM call, one lesson.
    _write_turns(p, ["let's build the parser", "no, use pnpm not npm"])
    assert len(detect.detect_from_transcript(str(p), session_id="s", client=client)) == 1
    assert client.messages.calls == 1
    assert detect.read_cursor("s") == 2

    # Third Stop: nothing new at all -> no work, cursor unchanged.
    assert detect.detect_from_transcript(str(p), session_id="s", client=client) == []
    assert client.messages.calls == 1
    assert detect.read_cursor("s") == 2


def test_cursor_resets_when_transcript_shrinks(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    detect.write_cursor("s", 99)  # cursor ahead of a freshly-rotated transcript
    p = tmp_path / "t.jsonl"
    _write_turns(p, ["never use npm, use pnpm"])
    client = FakeClient(_maybe())
    minted = detect.detect_from_transcript(str(p), session_id="s", client=client)
    assert len(minted) == 1  # reclassified from 0 rather than skipping everything
    assert detect.read_cursor("s") == 1


# --- lock (idempotent under near-simultaneous Stops) ------------------------
def test_lock_prevents_double_classify(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tp = _write_turns(tmp_path / "t.jsonl", ["never use npm, use pnpm"])
    client = FakeClient(_maybe())
    # Hold the lock as if a concurrent Stop were mid-classification.
    with detect._DetectLock("s") as held:
        assert held.acquired
        minted = detect.detect_from_transcript(tp, session_id="s", client=client)
    assert minted == []  # second Stop saw the lock and skipped
    assert client.messages.calls == 0
    # cursor was NOT advanced by the skipped run (the holder owns advancing it)
    assert detect.read_cursor("s") == 0


def test_lock_is_released_after_detection(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tp = _write_turns(tmp_path / "t.jsonl", ["never use npm, use pnpm"])
    detect.detect_from_transcript(tp, session_id="s", client=FakeClient(_maybe()))
    # lock dir must not linger after the run
    assert not paths.detect_lock("s").exists()
