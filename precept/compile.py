"""COMPILE: turn the markdown catalog into the plain-JSON policy cache that the
enforcement hot path reads. This is the one-way bridge markdown-card -> runtime.

The cache is DERIVED and disposable: `precept compile` (or `reindex`) can always
rebuild it from the cards, which are the source of truth.
"""

from __future__ import annotations

from typing import Any

from . import catalog, claude_md, install, paths
from .models import Decision, EnforcementTier, Lesson, Scope, Status
from .safety import atomic_write_text


def _runtime_policies(lesson: Lesson) -> list[dict[str, Any]]:
    """Only ACTIVE lessons' HARD HOOK policies enter the enforcement cache. A policy that
    carries a `permission_rule` is enforced natively by Claude Code (settings.json), so it
    is routed there by `compile_all` and EXCLUDED here — enforce.py never sees it."""
    if lesson.status != Status.ACTIVE:
        return []
    out: list[dict[str, Any]] = []
    for p in lesson.policies:
        if p.enforcement_tier != EnforcementTier.HARD:
            continue
        if p.permission_rule:  # routed to settings.json, not the hook cache (item B)
            continue
        # A repo-scoped rule with no root can't be enforced (no cwd to test against) ->
        # skip it (defensive; the model validator already requires it, but never trust).
        if p.scope == Scope.REPO and not p.scope_value:
            continue
        out.append(p.model_dump(mode="json", exclude_none=True))
    return out


def _permission_rules(lesson: Lesson) -> dict[str, list[str]]:
    """The ACTIVE HARD permission-rule strings from a lesson, bucketed by deny/ask."""
    rules: dict[str, list[str]] = {"deny": [], "ask": []}
    if lesson.status != Status.ACTIVE:
        return rules
    for p in lesson.policies:
        if p.enforcement_tier != EnforcementTier.HARD or not p.permission_rule:
            continue
        if p.scope == Scope.REPO and not p.scope_value:
            continue  # a repo rule can't be a global permission entry -> skip defensively
        rules["ask" if p.decision == Decision.ASK else "deny"].append(p.permission_rule)
    return rules


def compile_all(lessons: list[Lesson] | None = None) -> int:
    """Rebuild the policy cache from the catalog AND sync the native permission rules into
    settings.json. Returns the total count (hook policies + permission rules)."""
    lessons = catalog.load_all() if lessons is None else lessons
    compiled: list[dict[str, Any]] = []
    perm_rules: dict[str, list[str]] = {"deny": [], "ask": []}
    for lesson in lessons:
        compiled.extend(_runtime_policies(lesson))
        lr = _permission_rules(lesson)
        perm_rules["deny"].extend(lr["deny"])
        perm_rules["ask"].extend(lr["ask"])
    paths.ensure_dirs()
    import json

    atomic_write_text(paths.policies_cache(), json.dumps(compiled, indent=2))
    # De-dup + deterministic order so the settings write is idempotent.
    perm_rules = {b: sorted(set(v)) for b, v in perm_rules.items()}
    install.write_managed_permissions(perm_rules)
    # SOFT artifact #3: sync the ACTIVE conventions into Precept-owned `.claude/rules/*.md`
    # files (a side effect like the permissions sync; NOT counted in the returned policy
    # total, which is the HARD hook + permission count).
    claude_md.write_managed_rules(lessons)
    return len(compiled) + sum(len(v) for v in perm_rules.values())
