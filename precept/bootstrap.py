"""Phase 0 — BOOTSTRAP: seed the catalog from the user's existing setup.

NOT YET IMPLEMENTED (next build step). The locked design:
  - Read ~/.claude/CLAUDE.md, ~/.claude/settings.json (+ existing hooks/permissions),
    and the user's Second Brain feedback_*.md / MEMORY.md / skills.
  - Classify each existing directive into an artifact type + enforcement tier
    (a deny rule -> HARD policy; a convention -> SOFT CLAUDE.md/skill).
  - Mint everything as PENDING with origin=BOOTSTRAP so the human still reviews it.
  - Doubles as eval-seeding: real existing rules become golden-set tasks.
"""

from __future__ import annotations

from .models import Lesson


def bootstrap() -> list[Lesson]:  # pragma: no cover
    raise NotImplementedError("Bootstrap import lands in the next build step; see module docstring.")
