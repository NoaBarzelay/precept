"""COMPILE: turn the markdown catalog into the plain-JSON policy cache that the
enforcement hot path reads. This is the one-way bridge markdown-card -> runtime.

The cache is DERIVED and disposable: `precept compile` (or `reindex`) can always
rebuild it from the cards, which are the source of truth.
"""

from __future__ import annotations

from typing import Any

from . import catalog, paths
from .models import EnforcementTier, Lesson, Status
from .safety import atomic_write_text


def _runtime_policies(lesson: Lesson) -> list[dict[str, Any]]:
    """Only ACTIVE lessons' HARD policies enter the enforcement cache."""
    if lesson.status != Status.ACTIVE:
        return []
    out: list[dict[str, Any]] = []
    for p in lesson.policies:
        if p.enforcement_tier != EnforcementTier.HARD:
            continue
        out.append(p.model_dump(mode="json", exclude_none=True))
    return out


def compile_all(lessons: list[Lesson] | None = None) -> int:
    """Rebuild the policy cache from the catalog. Returns the policy count."""
    lessons = catalog.load_all() if lessons is None else lessons
    compiled: list[dict[str, Any]] = []
    for lesson in lessons:
        compiled.extend(_runtime_policies(lesson))
    paths.ensure_dirs()
    import json

    atomic_write_text(paths.policies_cache(), json.dumps(compiled, indent=2))
    return len(compiled)
