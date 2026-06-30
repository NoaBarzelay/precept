"""Knowledge-pillar configuration: resolve the (PRIVATE) vault path and the
(LOCAL, derived) index path.

THE SPLIT (same discipline as `precept.paths`):
  - The VAULT is the user's private markdown source of truth. It may live in a
    cloud-synced folder (iCloud/Obsidian). Precept NEVER bundles a vault path
    literal and NEVER copies vault content into the repo — the path is supplied
    at RUNTIME (env `PRECEPT_VAULT` first, then a config value/explicit arg).
  - The INDEX is a derived, disposable SQLite DB. It MUST live on a real LOCAL
    disk (reuses `paths.state_dir()`), never in the vault, never in iCloud, because
    SQLite corrupts under sync. It is fully rebuildable from the vault markdown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import paths


@dataclass(frozen=True)
class KnowledgeConfig:
    """Resolved knowledge-pillar paths. `vault` is the private source of truth;
    `index_db` is the derived local index. Both are absolute, expanded paths."""

    vault: Path
    index_db: Path


def resolve_vault(vault: str | Path | None = None) -> Path:
    """Resolve the vault root. Precedence: explicit arg > `PRECEPT_VAULT` env > error.

    There is deliberately NO default vault literal — the vault is private and must be
    supplied by the caller/environment, so the repo never ships a path into anyone's
    iCloud. Raises if none is given (fail loud, not into a guessed directory)."""
    raw = vault if vault is not None else os.environ.get("PRECEPT_VAULT")
    if not raw:
        raise ValueError(
            "No vault configured. Set the PRECEPT_VAULT environment variable (or pass "
            "vault=) to the markdown vault root. Precept ships no default vault path."
        )
    return Path(raw).expanduser().resolve()


def knowledge_index_db() -> Path:
    """The knowledge-pillar index DB (separate file from the notes index, same local
    state dir). Derived + disposable; rebuildable from the vault."""
    return paths.state_dir() / "knowledge_index.db"


def load(vault: str | Path | None = None) -> KnowledgeConfig:
    """Resolve both paths in one call (the vault from runtime, the index from local state)."""
    return KnowledgeConfig(vault=resolve_vault(vault), index_db=knowledge_index_db())
