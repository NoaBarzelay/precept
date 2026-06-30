"""RETRIEVAL INJECTION (slice 2) — surface relevant vault knowledge as `additionalContext`.

At UserPromptSubmit (query = the prompt) and SessionStart (query = recent context, when
available) we retrieve the top-k relevant knowledge via the existing FTS5/BM25 search and
inject a short, bounded context block, so the agent starts a turn already aware of what the
vault knows. LOCAL ONLY — this is keyword search over the local derived index; no vault
content ever leaves the machine.

Cheap and bounded by construction: small k, bodies truncated to a snippet, a hard cap on the
injected length. FAIL-OPEN: a missing vault/index or any error yields nothing (None).
"""

from __future__ import annotations

from . import config as kconfig
from . import index as kindex

DEFAULT_K = 5          # small top-k (bounded cost / context)
_SNIPPET_CHARS = 240   # truncate each doc's snippet
_MAX_TOTAL = 2000      # hard cap on the whole injected block


def _truncate(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def retrieve(query: str, *, k: int = DEFAULT_K) -> list[dict]:
    """Top-k knowledge docs relevant to `query` (FTS5 BM25), best first. Empty on any
    error / no vault / no index / empty query — the caller then injects nothing."""
    if not (query or "").strip():
        return []
    try:
        db = kconfig.knowledge_index_db()
    except Exception:
        return []
    try:
        # OR-match (recall-biased): a free-text prompt rarely contains every doc token, so
        # requiring all of them would surface nothing. BM25 still ranks the best fit first.
        hits = kindex.search(db, query, k=k, match_any=True)
    except Exception:
        return []
    # Knowledge files only (don't surface raw notes), and keep it bounded.
    return [h for h in hits if h.get("type") in (None, "knowledge")][:k]


def retrieval_context(query: str, *, k: int = DEFAULT_K) -> str | None:
    """Build the bounded `additionalContext` block for a query, or None when there is
    nothing relevant to inject. Safe to call on every UserPromptSubmit / SessionStart."""
    hits = retrieve(query, k=k)
    if not hits:
        return None
    lines = [
        "Relevant knowledge from your vault (retrieved locally; may help this turn):",
    ]
    for h in hits:
        title = h.get("title") or h.get("path") or "?"
        snippet = _truncate(h.get("snippet") or "", _SNIPPET_CHARS)
        folder = h.get("folder") or ""
        loc = f" [{folder}]" if folder else ""
        lines.append(f"  - {title}{loc}: {snippet}" if snippet else f"  - {title}{loc}")
    block = "\n".join(lines)
    return block[:_MAX_TOTAL]
