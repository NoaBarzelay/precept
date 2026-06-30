"""Item 3 — proactive review: a freshly detected rule is flagged needs_review and
surfaced via the Stop/SessionStart additionalContext, while the PENDING gate is intact
(nothing enforces until kept)."""

import io
import json

from datetime import date

from precept import catalog, detect, hooks, review
from precept.models import (
    ArtifactType, Determinism, Durability, ExtractedLesson, Lesson, MaybeLesson, Origin,
    Scope, Status,
)


class _FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed

    def parse(self, **kwargs):
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed):
        self.messages = _FakeMessages(parsed)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))


def _maybe() -> MaybeLesson:
    return MaybeLesson(
        chain_of_thought="correction", is_lesson=True,
        lesson=ExtractedLesson(
            trigger="installing deps", what_was_wrong="ran npm",
            what_to_do_instead="use pnpm install", origin_quote="never use npm, use pnpm",
            scope=Scope.GLOBAL, durability=Durability.PERSISTENT,
            determinism=Determinism.DETERMINISTIC, proposed_artifact_type=ArtifactType.RULE,
        ),
    )


def test_detected_lesson_is_flagged_needs_review(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"message": {"role": "user", "content": "never use npm, use pnpm"}}))
    minted = detect.detect_from_transcript(str(p), session_id="s", client=FakeClient(_maybe()))
    assert len(minted) == 1
    le = minted[0]
    assert le.needs_review is True
    assert le.status == Status.PENDING  # the keep-gate is intact (NOT auto-enforced)


def test_review_context_lists_pending_drafts(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    le = Lesson(
        id="use-pnpm", created=date(2026, 6, 30), origin=Origin.CORRECTION,
        source_session="s", status=Status.PENDING, needs_review=True,
        trigger="installing deps", what_was_wrong="ran npm",
        what_to_do_instead="use pnpm install",
    )
    catalog.write(le)
    ctx = review.review_context()
    assert ctx is not None
    assert "use-pnpm" in ctx and "pnpm" in ctx
    assert "keep" in ctx.lower()


def test_review_context_none_when_nothing_pending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert review.review_context() is None
    # an ACTIVE (already-reviewed) lesson must NOT be surfaced
    le = Lesson(
        id="done", created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        status=Status.ACTIVE, needs_review=False, trigger="t", what_was_wrong="w",
        what_to_do_instead="do",
    )
    catalog.write(le)
    assert review.review_context() is None


def test_stop_hook_injects_additional_context_when_allowing(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    le = Lesson(
        id="use-pnpm", created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        status=Status.PENDING, needs_review=True, trigger="installing deps",
        what_was_wrong="ran npm", what_to_do_instead="use pnpm install",
    )
    catalog.write(le)
    # Stop event with no transcript -> enforce allows ({}), so the review injection fires.
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "Stop"})))
    # don't actually spawn a detached detect subprocess in the test
    monkeypatch.setattr(hooks, "_spawn_detect", lambda event: None)
    hooks.stop_main()
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "use-pnpm" in out["hookSpecificOutput"]["additionalContext"]


def test_sessionstart_hook_injects_pending_reviews(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    le = Lesson(
        id="use-pnpm", created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        status=Status.PENDING, needs_review=True, trigger="installing deps",
        what_was_wrong="ran npm", what_to_do_instead="use pnpm install",
    )
    catalog.write(le)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart"})))
    hooks.sessionstart_main()
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "use-pnpm" in out["hookSpecificOutput"]["additionalContext"]


def test_sessionstart_emits_nothing_when_no_pending(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    hooks.sessionstart_main()
    assert capsys.readouterr().out == ""  # nothing to surface -> silent


def test_keep_clears_needs_review(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    le = Lesson(
        id="use-pnpm", created=date(2026, 6, 30), origin=Origin.CORRECTION, source_session="s",
        status=Status.PENDING, needs_review=True, determinism=Determinism.STYLISTIC,
        trigger="t", what_was_wrong="w", what_to_do_instead="do",
    )
    catalog.write(le)
    from typer.testing import CliRunner

    from precept.cli import app

    res = CliRunner().invoke(app, ["keep", "use-pnpm"])
    assert res.exit_code == 0
    reloaded = next(x for x in catalog.load_all() if x.id == "use-pnpm")
    assert reloaded.needs_review is False
    assert reloaded.status == Status.ACTIVE
    assert review.review_context() is None  # no longer surfaced
