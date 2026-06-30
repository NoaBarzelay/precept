"""Phase 0 — BOOTSTRAP: seed the catalog from the user's EXISTING setup.

Two sources, both offline (no LLM needed at import — the demo is instant):
  1. settings.json `permissions.deny` / `.ask` — these are already structured
     (`Tool(pattern)`), so they compile straight into HARD policies. "Precept already
     enforces the bans you set."
  2. CLAUDE.md bullet directives — captured as PENDING SOFT lessons for review.
     (A deterministic one can be upgraded to HARD later by `precept keep`, which runs
     matcher synthesis.)

Everything is minted PENDING + origin=BOOTSTRAP, so the human still reviews it — and
the imported set doubles as seed tasks for the eval harness.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from pathlib import Path

from . import catalog, paths
from .detect import _slugify
from .models import (
    ArtifactType, CheckKind, Condition, Decision, Determinism, Durability,
    EnforcementTier, GroundedSignals, HookEvent, Lesson, Match, MatchOp, Origin,
    Policy, Scope, Status,
)
from .synthesize import validate_match

# Tool -> the input field a permission pattern most likely constrains.
_PRIMARY_FIELD = {
    "Bash": "command", "Read": "file_path", "Edit": "file_path", "Write": "file_path",
    "WebFetch": "url", "Glob": "pattern", "Grep": "pattern", "NotebookEdit": "notebook_path",
}

_RULE_RE = re.compile(r"^\s*([A-Za-z_]+)\s*(?:\((.*)\))?\s*$")


def parse_permission_rule(rule: str) -> tuple[str, str | None] | None:
    """'Bash(rm -rf *)' -> ('Bash', 'rm -rf *'); 'Read(.env)' -> ('Read', '.env');
    'WebSearch' -> ('WebSearch', None)."""
    m = _RULE_RE.match(rule or "")
    if not m:
        return None
    return m.group(1), (m.group(2) if m.group(2) else None)


# Boundary note (item B): an imported permission rule becomes a HARD HOOK policy here,
# NOT a Precept-managed settings.json permission entry. Precept only "adopts" (re-writes
# as a managed permission) clean bans it SYNTHESIZED from a real correction — never the
# user's pre-existing permission entries, which it must not claim ownership of. The shape
# classifier (`synthesize._as_permission_rule`) is therefore invoked only in synthesize.
def lesson_from_permission(rule: str, decision: Decision, *, today: _date | None = None) -> Lesson | None:
    parsed = parse_permission_rule(rule)
    if not parsed:
        return None
    tool, pattern = parsed
    field = _PRIMARY_FIELD.get(tool)
    if field is None:
        return None  # unknown tool -> skip (typed validator gate)
    conditions = [Condition(field=field, op=MatchOp.GLOB, value=pattern)] if pattern else []
    match = Match(tool=tool, conditions=conditions)
    if not validate_match(match):
        return None
    verb = "Deny" if decision == Decision.DENY else "Confirm"
    slug = _slugify(f"{verb}-{tool}-{pattern or 'all'}")
    lesson = Lesson(
        id=slug,
        created=today or _date.today(),
        origin=Origin.BOOTSTRAP, source_session="bootstrap:settings.json",
        status=Status.PENDING, artifact_type=ArtifactType.RULE,
        scope=Scope.GLOBAL, durability=Durability.PERSISTENT,
        determinism=Determinism.DETERMINISTIC,
        trigger=f"{tool} call matching {pattern or 'anything'}",
        what_was_wrong=f"your settings {decision.value} this",
        what_to_do_instead=f"{verb.lower()} {tool}({pattern or ''})",
        origin_quote=rule,
        signals=GroundedSignals(deterministic_by_construction=True),
        policies=[Policy(
            id=f"{slug}-p1",
            lesson_id=slug,
            enforcement_tier=EnforcementTier.HARD, hook_event=HookEvent.PRE_TOOL_USE,
            check_kind=CheckKind.SINGLE_CALL, decision=decision,
            message=f"Blocked by your imported permission rule: {tool}({pattern or ''}).",
            match=match,
        )],
    )
    return lesson


def import_claude_md(text: str, *, limit: int = 50, today: _date | None = None) -> list[Lesson]:
    """Capture genuine CLAUDE.md directives (bulleted or numbered) as PENDING soft
    lessons. Skips code fences, headers, tables, and link/citation lines so we don't
    mint junk from example blocks."""
    out: list[Lesson] = []
    in_fence = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line[0] in "#|>":
            continue
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.+)$", line)
        if not m:
            continue
        directive = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1)).strip().rstrip(".")
        if "http://" in directive or "https://" in directive:  # citations / links
            continue
        if directive.count("](") >= 1:  # markdown-link-dominated
            continue
        if len(directive.split()) < 3 or len(directive) > 200:
            continue
        out.append(Lesson(
            id=_slugify(directive), created=today or _date.today(),
            origin=Origin.BOOTSTRAP, source_session="bootstrap:CLAUDE.md",
            status=Status.PENDING, artifact_type=ArtifactType.CLAUDE_MD,
            scope=Scope.GLOBAL, determinism=Determinism.STYLISTIC,
            trigger=directive, what_was_wrong="(existing CLAUDE.md directive)",
            what_to_do_instead=directive, origin_quote=directive,
            signals=GroundedSignals(),
        ))
        if len(out) >= limit:
            break
    return out


def bootstrap(claude_home: Path | None = None) -> list[Lesson]:
    """Import the user's existing setup as PENDING lessons. Returns what was minted."""
    home = Path(claude_home) if claude_home else paths.claude_home()
    minted: list[Lesson] = []

    settings_file = home / "settings.json"
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    perms = settings.get("permissions", {}) if isinstance(settings, dict) else {}
    for rule in perms.get("deny", []) or []:
        le = lesson_from_permission(rule, Decision.DENY)
        if le:
            minted.append(le)
    for rule in perms.get("ask", []) or []:
        le = lesson_from_permission(rule, Decision.ASK)
        if le:
            minted.append(le)

    claude_md = home / "CLAUDE.md"
    if claude_md.exists():
        minted += import_claude_md(claude_md.read_text(encoding="utf-8"))

    # dedup by id (don't overwrite an existing card)
    seen: set[str] = set()
    written: list[Lesson] = []
    for le in minted:
        if le.id in seen or catalog.card_path(le.id).exists():
            continue
        seen.add(le.id)
        catalog.write(le)
        written.append(le)
    return written
