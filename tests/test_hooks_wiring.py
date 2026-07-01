"""Wiring (item B): the PreToolUse hook logs an event (and still enforces), and the
SessionStart hook surfaces the throttled health reminder — both fail-open, nothing blocks."""

import io
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from precept import hooks, telemetry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PRECEPT_VAULT", raising=False)
    monkeypatch.delenv("PRECEPT_WATCHED_FILES", raising=False)
    return tmp_path


def _feed_stdin(monkeypatch, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_pretooluse_main_logs_event(isolated, monkeypatch, capsys):
    _feed_stdin(monkeypatch, {
        "tool_name": "Edit", "tool_input": {"file_path": "/x/y.py"},
        "session_id": "S", "cwd": "/x",
    })
    rc = hooks.pretooluse_main()
    assert rc == 0
    # the event was logged...
    recs = telemetry.read_events()
    assert len(recs) == 1 and recs[0]["tool"] == "Edit"
    # ...and the call was still allowed (enforcement ran, fail-open, no policies)
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_pretooluse_main_fail_open_on_bad_stdin(isolated, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hooks.pretooluse_main() == 0  # never raises


def test_stop_main_does_not_spawn_detect(isolated, monkeypatch):
    # A1/A2: DETECT must NOT run on every turn end (it spends subscription quota).
    calls = []
    monkeypatch.setattr(hooks, "_spawn_detect", lambda event: calls.append(event))
    _feed_stdin(monkeypatch, {"hook_event_name": "Stop"})
    assert hooks.stop_main() == 0
    assert calls == []


def test_sessionend_spawns_detect(isolated, monkeypatch):
    # DETECT runs once per session, at SessionEnd.
    calls = []
    monkeypatch.setattr(hooks, "_spawn_detect", lambda event: calls.append(event))
    _feed_stdin(monkeypatch, {"hook_event_name": "SessionEnd", "transcript_path": "/t.jsonl"})
    assert hooks.detect_main() == 0
    assert len(calls) == 1


def test_spawn_detect_disabled_by_env(isolated, monkeypatch):
    # PRECEPT_DISABLE_DETECT turns the learning loop off entirely (enforce-only mode).
    import subprocess
    popen_calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: popen_calls.append(a))
    monkeypatch.setenv("PRECEPT_DISABLE_DETECT", "1")
    hooks._spawn_detect({"transcript_path": "/t.jsonl", "session_id": "S"})
    assert popen_calls == []


def test_sessionstart_main_surfaces_health_reminder(isolated, monkeypatch, capsys):
    stale = isolated / "stale.md"
    stale.write_text("x", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(stale, (old, old))
    monkeypatch.setenv("PRECEPT_WATCHED_FILES", str(stale))
    _feed_stdin(monkeypatch, {"hook_event_name": "SessionStart"})

    rc = hooks.sessionstart_main()
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "system-health check" in ctx
    assert ">30d" in ctx
