"""The keep/veto core, extracted so the CLI and the MCP server share ONE code path.

`precept keep` / `precept delete` and the MCP `review_decide` tool must apply the
review gate identically, so the logic lives here (pure: it mutates and persists a
Lesson, recompiles, and returns a small result) and both surfaces call it. No console
output here; each surface renders the result its own way.
"""

from __future__ import annotations

from . import catalog, compile as _compile, writers
from .models import Determinism, Lesson, Status


def keep_lesson(le: Lesson) -> dict[str, object]:
    """Keep a lesson: PENDING -> ACTIVE. A deterministic, not-yet-compiled lesson is
    synthesized into an enforcing policy (fail-CLOSED: on any error it stays soft, never
    a junk policy). Persists the card, recompiles the cache, and syncs the writers.
    Returns {id, tier ('hard'|'soft'), destination (soft artifact path or None),
    recompiled (active-policy count)}."""
    le.status = Status.ACTIVE
    le.signals.human_kept = True
    le.needs_review = False
    if not le.policies and le.determinism != Determinism.STYLISTIC:
        from . import synthesize  # lazy: only the keep path needs the model SDK

        try:
            synthesize.compile_lesson(le)
        except Exception:
            pass  # fail closed: kept as soft, never a junk policy
    catalog.write(le)
    n = _compile.compile_all()
    dest = None
    if not le.policies:
        w = writers.for_artifact(le.artifact_type)
        d = w.destination_for(le) if w is not None else None
        dest = str(d) if d is not None else None
    return {
        "id": le.id,
        "tier": "hard" if le.policies else "soft",
        "destination": dest,
        "recompiled": n,
    }


def veto_lesson(le: Lesson) -> dict[str, object]:
    """Veto a lesson: mark it ARCHIVED (soft delete, never removes the card file),
    persist, and recompile so it stops enforcing. Returns {id, recompiled}."""
    le.status = Status.ARCHIVED
    le.signals.human_kept = False
    le.needs_review = False
    catalog.write(le)
    n = _compile.compile_all()
    return {"id": le.id, "recompiled": n}
