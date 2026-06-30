"""Proactive review surfacing (item 3): turn the `needs_review` PENDING lessons into a
short in-session prompt the agent injects via a hook's `additionalContext`, so a freshly
drafted rule is surfaced RIGHT AWAY ("I drafted a rule from your correction — keep it?")
instead of waiting for the user to run `precept list`.

This NEVER enforces anything (enforcement stays gated on status=ACTIVE). It only changes
HOW the user is asked — proactively, in-flow — not WHETHER they approve. STDLIB ONLY +
fail-OPEN by every caller: this rides the hot path, so a read error surfaces nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths

_MAX_SURFACED = 5  # don't flood the context if a burst of corrections piled up


def _frontmatter(text: str) -> dict:
    """Parse just the YAML-ish frontmatter we need WITHOUT importing pyyaml/pydantic
    (the hot path stays stdlib). We only read a handful of flat string/bool fields, so a
    tiny line scanner over the `---`…`---` block is enough; anything unparseable is skipped."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line or line[0] in " \t-#" or ":" not in line:
            continue  # skip nested/list lines; we only want top-level scalars
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip("'\"")
    return out


def _pending_reviews() -> list[dict]:
    """Scan the catalog cards for PENDING lessons flagged needs_review. Reads markdown
    directly (stdlib) so SessionStart/Stop never import the compile-time stack."""
    d = paths.catalog_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.md")):
        try:
            fm = _frontmatter(Path(p).read_text(encoding="utf-8"))
        except OSError:
            continue
        if fm.get("status") == "pending" and fm.get("needs_review") in ("true", "True"):
            out.append(fm)
    return out


def review_context() -> str | None:
    """Build the additionalContext string for the currently-unreviewed drafted rules, or
    None when there is nothing to surface. Safe to call on every Stop/SessionStart."""
    pending = _pending_reviews()
    if not pending:
        return None
    lines = [
        "Precept drafted "
        f"{len(pending)} rule(s) from your recent corrections (still PENDING — not "
        "enforced yet). For each: keep it with `precept keep <id>`, or drop it with "
        "`precept delete <id>`. Ask me to keep or skip and I'll run it for you.",
    ]
    for fm in pending[:_MAX_SURFACED]:
        rid = fm.get("id", "?")
        summary = fm.get("what_to_do_instead") or fm.get("trigger") or "(see card)"
        lines.append(f"  - {rid}: {summary}")
    if len(pending) > _MAX_SURFACED:
        lines.append(f"  …and {len(pending) - _MAX_SURFACED} more (`precept list`).")
    return "\n".join(lines)


def review_payload() -> dict:
    """A JSON-serializable {"pending": [...]} summary, for a `precept review` command or
    an MCP surface later. Lightweight; the cards remain the source of truth."""
    return {
        "pending": [
            {
                "id": fm.get("id", "?"),
                "summary": fm.get("what_to_do_instead") or fm.get("trigger") or "",
            }
            for fm in _pending_reviews()
        ]
    }


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(review_payload(), indent=2))
