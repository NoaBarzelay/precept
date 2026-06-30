"""Context-rule store (item A): the authoring side of the non-blocking PreToolUse reminders.

A context rule injects `text` as additionalContext when a tool call matches (tool name +
an optional file-path pattern) on an ALLOW. It NEVER blocks. This module is the CRUD over
the JSON file that is the SOURCE OF TRUTH; the enforce hot path reads the same JSON directly
(stdlib, fail-open) via `enforce.load_context_rules`, so there is no compile step — context
rules ARE data. Writes are atomic (temp -> fsync -> os.replace), like every Precept writer.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import paths
from .models import ContextRule
from .safety import atomic_write_text


def load() -> list[ContextRule]:
    """Every authored context rule, tolerant of a stray/old entry (skipped, never fatal)."""
    try:
        data = json.loads(paths.context_rules_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[ContextRule] = []
    for item in data:
        try:
            out.append(ContextRule.model_validate(item))
        except Exception:
            continue
    return out


def save(rules: list[ContextRule]) -> Path:
    """Atomically (re)write the whole rule file."""
    paths.precept_home().mkdir(parents=True, exist_ok=True)
    payload = [r.model_dump(mode="json", exclude_none=True) for r in rules]
    p = paths.context_rules_path()
    atomic_write_text(p, json.dumps(payload, indent=2) + "\n")
    return p


def add(rule: ContextRule) -> ContextRule:
    """Add a rule (replacing any existing one with the same id) and persist."""
    rules = [r for r in load() if r.id != rule.id]
    rules.append(rule)
    save(rules)
    return rule


def remove(rule_id: str) -> bool:
    """Remove the rule with this id. Returns True if one was removed, False if not found."""
    rules = load()
    kept = [r for r in rules if r.id != rule_id]
    if len(kept) == len(rules):
        return False
    save(kept)
    return True


def gen_id() -> str:
    """A short, stable, collision-resistant id when the caller doesn't supply one."""
    return f"ctx-{uuid.uuid4().hex[:8]}"
