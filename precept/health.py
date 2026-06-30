"""System-health reminder (item B-3): flag CONFIGURED watched files that have gone stale.

Given watched file path(s) — supplied at runtime (env `PRECEPT_WATCHED_FILES` or a JSON
config in precept_home), never hardcoded — this looks at each file's mtime and returns a
reminder string when it is stale: a SOFT tier past `soft_days` (default 7) and a STRONGER
tier past `hard_days` (default 30). It rides the SessionStart hook's additionalContext,
THROTTLED to at most once per calendar day (the same stamp pattern as the knowledge audit).

STDLIB only + FAIL-OPEN: no watched paths / no readable file / any error -> no reminder.
"""

from __future__ import annotations

import json
import os
from datetime import date as _date, datetime, timezone
from pathlib import Path

from . import paths
from .safety import atomic_write_text

SOFT_DAYS = 7
HARD_DAYS = 30


# --- once-per-day throttle (mirrors knowledge.ops, on a dedicated stamp) -----
def last_run_date() -> _date | None:
    """The calendar date the health check last ran, or None if it never has."""
    try:
        raw = paths.health_stamp().read_text(encoding="utf-8").strip()
        return _date.fromisoformat(raw)
    except (OSError, ValueError):
        return None


def should_run_today(today: _date | None = None) -> bool:
    """True at most ONCE per calendar day, so the reminder can ride SessionStart without
    nagging (first session of the day runs it; the rest skip)."""
    today = today or _date.today()
    last = last_run_date()
    return last is None or last < today


def mark_ran(today: _date | None = None) -> None:
    """Record that the health check ran today (atomic write to the local state stamp)."""
    paths.ensure_dirs()
    atomic_write_text(paths.health_stamp(), (today or _date.today()).isoformat() + "\n")


# --- watched-paths config (runtime, never a repo literal) -------------------
def load_watched() -> list[Path]:
    """Resolve the watched file paths from config. Union of `$PRECEPT_WATCHED_FILES`
    (os.pathsep-separated) and an optional JSON list in precept_home. Empty/missing -> []."""
    out: list[str] = []
    env = os.environ.get("PRECEPT_WATCHED_FILES")
    if env:
        out.extend(part for part in env.split(os.pathsep) if part.strip())
    try:
        data = json.loads(paths.watched_files_config().read_text(encoding="utf-8"))
        if isinstance(data, list):
            out.extend(str(x) for x in data if isinstance(x, str) and x.strip())
    except (OSError, ValueError):
        pass
    # de-dup, preserve order
    seen: set[str] = set()
    result: list[Path] = []
    for raw in out:
        if raw not in seen:
            seen.add(raw)
            result.append(Path(raw).expanduser())
    return result


# --- the staleness check ----------------------------------------------------
def _age_days(mtime: float, now: datetime) -> float:
    return (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds() / 86400.0


def staleness_reminder(
    watched: list[Path],
    *,
    now: datetime | None = None,
    soft_days: int = SOFT_DAYS,
    hard_days: int = HARD_DAYS,
) -> str | None:
    """Reminder string for the stale watched files, or None when all are fresh / none exist.
    Files past `hard_days` get the STRONGER tier; those past `soft_days` the SOFT tier; a
    file that can't be stat'd is skipped (fail-open)."""
    now = now or datetime.now(timezone.utc)
    stale: list[tuple[str, int, bool]] = []  # (path, age_days, is_hard)
    for p in watched:
        try:
            age = _age_days(p.stat().st_mtime, now)
        except OSError:
            continue  # missing/unreadable -> can't judge -> skip
        if age >= hard_days:
            stale.append((str(p), int(age), True))
        elif age >= soft_days:
            stale.append((str(p), int(age), False))
    if not stale:
        return None
    lines = [
        f"Precept system-health check: {len(stale)} watched file(s) look stale "
        "(consider refreshing them):"
    ]
    for path, age, is_hard in stale:
        tier = (f">{hard_days}d — overdue, refresh soon" if is_hard
                else f">{soft_days}d — getting stale")
        lines.append(f"  - {path}: last updated ~{age}d ago ({tier}).")
    return "\n".join(lines)


def health_reminder(today: _date | None = None) -> str | None:
    """The throttled SessionStart entrypoint: once per calendar day, resolve the watched
    paths from config and return the staleness reminder (stamping that it ran). Returns None
    when throttled, when nothing is configured, or when everything is fresh. FAIL-OPEN."""
    try:
        if not should_run_today(today):
            return None
        watched = load_watched()
        if not watched:
            return None
        msg = staleness_reminder(watched)
        mark_ran(today)  # stamp once we actually ran (even if nothing was stale)
        return msg
    except Exception:
        return None
