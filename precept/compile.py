"""COMPILE: turn the markdown catalog into the plain-JSON policy cache that the
enforcement hot path reads. This is the one-way bridge markdown-card -> runtime.

The cache is DERIVED and disposable: `precept compile` (or `reindex`) can always
rebuild it from the cards, which are the source of truth.
"""

from __future__ import annotations

from typing import Any

from . import catalog, paths, writers
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
        # HARD hook policies block; a CONTEXT policy is a non-blocking prompt-time injector
        # (SOFT by nature) but still lives in the hook cache so enforce.py can surface it.
        if p.enforcement_tier != EnforcementTier.HARD and p.decision != Decision.CONTEXT:
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


def aggregate_permission_rules(lessons: list[Lesson]) -> dict[str, list[str]]:
    """All ACTIVE HARD permission-rule strings across the lessons, bucketed by deny/ask,
    de-duped and sorted per bucket so the settings write is idempotent. Pure; used by
    `compile_all` (for the returned count) and by the permissions writer (for the sync)."""
    rules: dict[str, list[str]] = {"deny": [], "ask": []}
    for lesson in lessons:
        lr = _permission_rules(lesson)
        rules["deny"].extend(lr["deny"])
        rules["ask"].extend(lr["ask"])
    return {b: sorted(set(v)) for b, v in rules.items()}


def compile_all(lessons: list[Lesson] | None = None) -> int:
    """Rebuild the policy cache from the catalog AND sync every registered artifact host
    (native permission rules into settings.json, conventions into Precept-owned
    `.claude/rules/*.md` files). Returns the total count (hook policies + permission
    rules; the convention sync is a side effect, not counted)."""
    lessons = catalog.load_all() if lessons is None else lessons
    compiled: list[dict[str, Any]] = []
    for lesson in lessons:
        compiled.extend(_runtime_policies(lesson))
    paths.ensure_dirs()
    import json

    atomic_write_text(paths.policies_cache(), json.dumps(compiled, indent=2))
    # COMMIT: each registered writer syncs its host from the same lessons (one writer
    # module + one registry line per entity commit target — see writers.py).
    for writer in writers.WRITERS.values():
        writer.sync(lessons)
    n_perms = sum(len(v) for v in aggregate_permission_rules(lessons).values())
    return len(compiled) + n_perms
