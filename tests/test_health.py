"""System-health staleness reminder (item B-3): the tiered reminder + the once-per-day
throttle, both generic (watched paths come from config, never a repo literal)."""

import os
from datetime import date, datetime, timedelta, timezone

import pytest

from precept import health


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PRECEPT_WATCHED_FILES", raising=False)
    return tmp_path


NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def _touch(path, *, age_days):
    path.write_text("x", encoding="utf-8")
    when = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (when, when))
    return path


def test_fresh_file_yields_no_reminder(isolated):
    f = _touch(isolated / "fresh.md", age_days=2)
    assert health.staleness_reminder([f], now=NOW) is None


def test_soft_tier_past_7_days(isolated):
    f = _touch(isolated / "soft.md", age_days=10)
    msg = health.staleness_reminder([f], now=NOW)
    assert msg is not None
    assert ">7d" in msg
    assert ">30d" not in msg
    assert "~10d ago" in msg


def test_hard_tier_past_30_days(isolated):
    f = _touch(isolated / "hard.md", age_days=45)
    msg = health.staleness_reminder([f], now=NOW)
    assert msg is not None
    assert ">30d" in msg
    assert "overdue" in msg


def test_mixed_tiers_and_missing_file(isolated):
    soft = _touch(isolated / "soft.md", age_days=8)
    hard = _touch(isolated / "hard.md", age_days=99)
    missing = isolated / "gone.md"  # never created -> skipped (fail-open)
    msg = health.staleness_reminder([soft, hard, missing], now=NOW)
    assert "2 watched file(s)" in msg
    assert str(soft) in msg and str(hard) in msg
    assert str(missing) not in msg


def test_boundary_exactly_7_days_is_soft(isolated):
    f = _touch(isolated / "edge.md", age_days=7)
    msg = health.staleness_reminder([f], now=NOW)
    assert msg is not None and ">7d" in msg


# --- once-per-day throttle --------------------------------------------------
def test_throttle_holds_within_a_day(isolated):
    today = date(2026, 6, 30)
    assert health.should_run_today(today) is True
    health.mark_ran(today)
    assert health.should_run_today(today) is False  # same day -> throttled
    assert health.should_run_today(date(2026, 7, 1)) is True  # next day -> runs again


def test_health_reminder_throttled_after_first_run(isolated):
    today = date(2026, 6, 30)
    f = _touch(isolated / "stale.md", age_days=40)
    os.environ["PRECEPT_WATCHED_FILES"] = str(f)
    try:
        first = health.health_reminder(today)
        assert first is not None and ">30d" in first
        # second call same day -> throttled -> None even though the file is still stale
        assert health.health_reminder(today) is None
    finally:
        del os.environ["PRECEPT_WATCHED_FILES"]


def test_health_reminder_none_when_nothing_watched(isolated):
    assert health.health_reminder(date(2026, 6, 30)) is None
    # and it did NOT stamp (nothing ran), so a later config still gets a first run
    f = _touch(isolated / "stale.md", age_days=40)
    os.environ["PRECEPT_WATCHED_FILES"] = str(f)
    try:
        assert health.health_reminder(date(2026, 6, 30)) is not None
    finally:
        del os.environ["PRECEPT_WATCHED_FILES"]


def test_load_watched_from_env_and_config(isolated):
    from precept import paths

    a = isolated / "a.md"
    b = isolated / "b.md"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")
    os.environ["PRECEPT_WATCHED_FILES"] = str(a)
    paths.precept_home().mkdir(parents=True, exist_ok=True)
    import json

    paths.watched_files_config().write_text(json.dumps([str(b)]), encoding="utf-8")
    try:
        watched = health.load_watched()
        assert a in watched and b in watched
    finally:
        del os.environ["PRECEPT_WATCHED_FILES"]
