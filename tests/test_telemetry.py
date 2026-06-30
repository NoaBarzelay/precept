"""Telemetry (item B): the event log + the weekly scorecard.

A planted event-log fixture must tally correctly (tool counts, edits under a configurable
root, memory-file edits, skill invocations), and the report must stay generic (no literals —
every root/pattern is a parameter)."""

from datetime import datetime, timedelta, timezone

import pytest

from precept import telemetry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))


NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def _ev(tool, *, ago_days=0, file_path=None, command=None, session="s1", cwd="/work"):
    ts = (NOW - timedelta(days=ago_days)).isoformat()
    return {
        "ts": ts, "tool": tool, "session": session, "cwd": cwd,
        "file_path": file_path, "bash_cmd": command,
        "skill_name": None,
    }


PLANTED = [
    _ev("Edit", file_path="/work/repo/a.py"),
    _ev("Edit", file_path="/work/repo/b.py"),
    _ev("Write", file_path="/work/repo/notes/MEMORY.md"),
    _ev("Edit", file_path="/elsewhere/c.py"),  # outside the root
    _ev("Bash", command="pytest -q"),
    _ev("Read", file_path="/home/u/.claude/skills/daily-tracking/SKILL.md"),
    _ev("Read", file_path="/home/u/.claude/skills/knowledge/SKILL.md"),
    _ev("Read", file_path="/work/repo/a.py"),  # a normal read, not a skill
    _ev("Edit", file_path="/work/repo/old.py", ago_days=99),  # outside the 7d window
]


def test_scorecard_tallies_planted_log(isolated):
    card = telemetry.compute_scorecard(
        PLANTED, days=7, root="/work/repo",
        memory_regex=r"MEMORY\.md$", now=NOW,
    )
    # 8 events inside the 7-day window (the 99-day-old Edit is excluded).
    assert card["total"] == 8
    assert card["by_tool"]["Edit"] == 3  # the in-window edits (old.py excluded)
    assert card["by_tool"]["Write"] == 1
    assert card["by_tool"]["Bash"] == 1
    assert card["by_tool"]["Read"] == 3
    # Edit/Write calls = 3 Edit + 1 Write in window
    assert card["edit_count"] == 4
    # under /work/repo: a.py, b.py, MEMORY.md = 3 (c.py is /elsewhere)
    assert card["edits_under_root"] == 3
    # memory-file edits: MEMORY.md only
    assert card["memory_edits"] == 1
    # skill invocations: the two SKILL.md reads (the normal read of a.py is not one)
    assert card["skill_invocations"] == 2
    assert card["skills_by_name"] == {"daily-tracking": 1, "knowledge": 1}


def test_scorecard_window_excludes_old_events(isolated):
    card = telemetry.compute_scorecard(PLANTED, days=1, now=NOW)
    assert card["total"] == 8  # all planted (except the 99d one) are <=0 days old here
    card2 = telemetry.compute_scorecard(
        [_ev("Edit", ago_days=10)], days=7, now=NOW
    )
    assert card2["total"] == 0


def test_unconfigured_root_and_memory_are_none(isolated):
    card = telemetry.compute_scorecard(PLANTED, days=7, now=NOW)
    assert card["edits_under_root"] is None
    assert card["memory_edits"] is None
    md = telemetry.render_markdown(card)
    assert "no --root configured" in md
    assert "no --memory-regex configured" in md


def test_configurable_skill_regex(isolated):
    # A custom skill pattern that matches nothing -> zero skill invocations.
    card = telemetry.compute_scorecard(PLANTED, days=7, skill_regex=r"/NOPE/", now=NOW)
    assert card["skill_invocations"] == 0


def test_log_event_round_trips_through_disk(isolated):
    telemetry.log_event(
        {"tool_name": "Edit", "tool_input": {"file_path": "/x/y.py"},
         "session_id": "S", "cwd": "/x"},
        now=NOW,
    )
    telemetry.log_event(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "session_id": "S"},
        now=NOW,
    )
    recs = telemetry.read_events()
    assert [r["tool"] for r in recs] == ["Edit", "Bash"]
    assert recs[0]["file_path"] == "/x/y.py"
    assert recs[1]["bash_cmd"] == "ls -la"
    assert recs[1]["file_path"] is None


def test_event_record_extracts_skill_name():
    rec = telemetry.event_record(
        {"tool_name": "Read",
         "tool_input": {"file_path": "/a/skills/foo/SKILL.md"}},
        now=NOW,
    )
    assert rec["skill_name"] == "foo"
    # a non-skill read carries no skill_name
    rec2 = telemetry.event_record(
        {"tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}}, now=NOW
    )
    assert rec2["skill_name"] is None


def test_read_events_tolerates_garbage_lines(isolated, tmp_path):
    from precept import paths

    p = paths.event_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"ts": "x", "tool": "Edit"}\nnot json\n\n{"tool":"Bash","ts":"y"}\n',
                 encoding="utf-8")
    recs = telemetry.read_events()
    assert [r["tool"] for r in recs] == ["Edit", "Bash"]


def test_log_event_is_fail_open_on_bad_path(isolated, monkeypatch):
    # An unwritable path must not raise (the hook stays non-blocking).
    monkeypatch.setattr(telemetry.paths, "event_log", lambda: __import__("pathlib").Path("/proc/nonexistent/dir/x.jsonl"))
    telemetry.log_event({"tool_name": "Edit"})  # must not raise
