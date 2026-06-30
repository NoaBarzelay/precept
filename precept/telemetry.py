"""Tool-call telemetry (item B): the event log + the weekly scorecard.

`log_event` appends ONE JSON line per guarded tool call to a Precept-owned JSONL under the
local state dir — cheap and FAIL-OPEN (it rides the PreToolUse hot path, so any error writes
nothing and never blocks the call). `build_report` reads that log back and renders a markdown
scorecard for the last N days.

Generic by construction: every "root" and "pattern" the report tallies is a config value or
a CLI flag — Precept ships NO path or content literal. The one structural default is the
Claude Code skill convention (`*/skills/*/SKILL.md`), which is a tool convention, not a
user/vault path, and is itself overridable.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import paths

# Tools that write a file (so "edits under a root" / "memory-file edits" are well-defined).
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# A Read of one of these is a skill invocation. STRUCTURAL Claude Code convention (not a
# user/vault literal); overridable via the report's `skill_regex`.
DEFAULT_SKILL_REGEX = r"/skills/[^/]+/SKILL\.md$"

_MAX_CMD = 2000  # cap the logged bash command so a line stays small (single-write append)


def _skill_name(tool: str, file_path: str) -> str | None:
    """The skill folder name when `file_path` is a skill SKILL.md Read, else None. Computed
    at log time as a convenience; `build_report` recomputes from file_path so the pattern
    stays configurable there."""
    if tool != "Read" or not file_path:
        return None
    m = re.search(r"/skills/([^/]+)/SKILL\.md$", file_path)
    return m.group(1) if m else None


def event_record(event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Project a raw PreToolUse hook payload into the flat log record. Pure (no I/O), so the
    shape is unit-testable on its own."""
    tool = event.get("tool_name", "") or ""
    ti = event.get("tool_input", {}) or {}
    file_path = ti.get("file_path") if isinstance(ti, dict) else None
    bash_cmd = ti.get("command") if (isinstance(ti, dict) and tool == "Bash") else None
    if isinstance(bash_cmd, str):
        bash_cmd = bash_cmd[:_MAX_CMD]
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "ts": ts,
        "tool": tool,
        "session": event.get("session_id"),
        "cwd": event.get("cwd"),
        "file_path": file_path if isinstance(file_path, str) else None,
        "bash_cmd": bash_cmd,
        "skill_name": _skill_name(tool, file_path if isinstance(file_path, str) else ""),
    }


def log_event(event: dict[str, Any], *, path: Path | None = None, now: datetime | None = None) -> None:
    """Append one JSON line for this tool call. FAIL-OPEN: any error is swallowed (the hook
    never blocks a call because telemetry hiccuped). A single short-line O_APPEND write is
    atomic enough for concurrent short-lived hooks (lines are capped small)."""
    try:
        p = path or paths.event_log()
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event_record(event, now=now), ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # fail open: telemetry must never wedge or slow the guarded call


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    """Parse the event log, tolerating a stray/corrupt line (skipped)."""
    p = path or paths.event_log()
    out: list[dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _within(rec: dict[str, Any], cutoff: datetime) -> bool:
    raw = rec.get("ts")
    if not isinstance(raw, str):
        return False
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= cutoff


def _under_root(file_path: str | None, root: str) -> bool:
    if not file_path:
        return False
    try:
        fp = os.path.realpath(file_path)
        rt = os.path.realpath(root)
    except OSError:
        return False
    return fp == rt or fp.startswith(rt + os.sep)


def compute_scorecard(
    events: list[dict[str, Any]],
    *,
    days: int = 7,
    root: str | None = None,
    memory_regex: str | None = None,
    skill_regex: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tally the windowed events into a plain dict (pure; the markdown renderer is separate
    and the tests assert on this)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    windowed = [e for e in events if _within(e, cutoff)]

    by_tool = Counter(e.get("tool", "") or "?" for e in windowed)
    edits = [e for e in windowed if (e.get("tool") or "") in EDIT_TOOLS]

    mem_re = re.compile(memory_regex) if memory_regex else None
    skill_re = re.compile(skill_regex or DEFAULT_SKILL_REGEX)

    edits_under_root = (
        sum(1 for e in edits if _under_root(e.get("file_path"), root)) if root else None
    )
    memory_edits = (
        sum(1 for e in edits if e.get("file_path") and mem_re.search(e["file_path"]))
        if mem_re else None
    )
    skills = Counter()
    for e in windowed:
        if (e.get("tool") or "") == "Read":
            fp = e.get("file_path") or ""
            if fp and skill_re.search(fp):
                m = re.search(r"/skills/([^/]+)/SKILL\.md$", fp)
                skills[m.group(1) if m else fp] += 1

    return {
        "days": days,
        "total": len(windowed),
        "by_tool": dict(by_tool.most_common()),
        "edit_count": len(edits),
        "root": root,
        "edits_under_root": edits_under_root,
        "memory_regex": memory_regex,
        "memory_edits": memory_edits,
        "skill_invocations": sum(skills.values()),
        "skills_by_name": dict(skills.most_common()),
    }


def render_markdown(card: dict[str, Any]) -> str:
    """Render a scorecard dict as a markdown report."""
    lines = [
        f"# Precept activity scorecard — last {card['days']} day(s)",
        "",
        f"- Total tool calls: **{card['total']}**",
        "",
        "## By tool",
    ]
    if card["by_tool"]:
        for tool, n in card["by_tool"].items():
            lines.append(f"- {tool}: {n}")
    else:
        lines.append("- (none)")
    lines += ["", "## Edits"]
    lines.append(f"- Edit/Write calls ({', '.join(EDIT_TOOLS)}): {card['edit_count']}")
    if card["root"] is not None:
        lines.append(f"- …under `{card['root']}`: {card['edits_under_root']}")
    else:
        lines.append("- …under a root: (no --root configured)")
    if card["memory_regex"] is not None:
        lines.append(f"- edits to memory files matching `{card['memory_regex']}`: {card['memory_edits']}")
    else:
        lines.append("- edits to memory files: (no --memory-regex configured)")
    lines += ["", "## Skill invocations"]
    lines.append(f"- Total (Read of `*/skills/*/SKILL.md`): {card['skill_invocations']}")
    for name, n in card["skills_by_name"].items():
        lines.append(f"  - {name}: {n}")
    return "\n".join(lines)


def build_report(
    *,
    days: int = 7,
    root: str | None = None,
    memory_regex: str | None = None,
    skill_regex: str | None = None,
    path: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Read the event log and render the markdown scorecard for the last `days`."""
    card = compute_scorecard(
        read_events(path), days=days, root=root, memory_regex=memory_regex,
        skill_regex=skill_regex, now=now,
    )
    return render_markdown(card)
