"""A minimal MCP server over the Precept catalog and its review gate.

Precept's primary consumer is already inside Claude Code (via hooks), so this server
is deliberately small: four workflow-shaped tools that let any local MCP client
(Claude Code, Claude.ai, an editor) drive the human-in-the-loop review gate
conversationally, instead of remembering CLI commands.

The tools are thin wrappers over the same internal functions the CLI uses (no new
business logic). `review_decide` runs the exact `precept keep` / `precept delete`
path, so the review gate semantics are unchanged; the human is still the one driving
the client.

Privacy: this serves the PRIVATE data plane (the user's catalog in ~/.precept) to a
LOCAL client over stdio. There is no network transport. The optional `mcp` SDK is a
separate extra (`pip install "precept[mcp]"`) so the core stays lean; `precept mcp`
errors helpfully when it is absent.
"""

from __future__ import annotations

from typing import Any

from . import catalog, enforce
from .models import Lesson


def _find(entity_id: str) -> Lesson | None:
    for le in catalog.load_all():
        if le.id == entity_id:
            return le
    return None


def _policy_summary(le: Lesson) -> list[dict[str, str]]:
    return [
        {
            "hook_event": p.hook_event.value,
            "check_kind": p.check_kind.value,
            "decision": p.decision.value,
        }
        for p in le.policies
    ]


def catalog_search(query: str, status: str | None = None) -> list[dict[str, Any]]:
    """Search the Precept catalog. `query` is a case-insensitive substring matched
    against each entity's id, trigger, and correction text (empty query returns all).
    `status` optionally filters by pending, active, or archived. Returns id, type,
    status, and the one-line trigger for each match."""
    q = (query or "").lower().strip()
    want = status.lower().strip() if status else None
    out: list[dict[str, Any]] = []
    for le in catalog.load_all():
        if want and le.status.value != want:
            continue
        haystack = " ".join(
            [le.id, le.trigger, le.what_was_wrong, le.what_to_do_instead]
        ).lower()
        if not q or q in haystack:
            out.append(
                {
                    "id": le.id,
                    "type": le.artifact_type.value,
                    "status": le.status.value,
                    "trigger": le.trigger,
                }
            )
    return out


def entity_show(entity_id: str) -> dict[str, Any]:
    """Show one catalog entity in full: its provenance (origin, source session, the
    user's original words), the correction (trigger, what was wrong, what to do
    instead), its compiled policies, and its live fire count, the number of times it
    has actually fired at runtime (derived from the decision log)."""
    le = _find(entity_id)
    if le is None:
        return {"error": f"no entity with id {entity_id!r}"}
    fires = enforce.decision_fire_counts().get(le.id, 0)
    return {
        "id": le.id,
        "type": le.artifact_type.value,
        "status": le.status.value,
        "tier": "hard" if le.policies else "soft",
        "trigger": le.trigger,
        "what_was_wrong": le.what_was_wrong,
        "what_to_do_instead": le.what_to_do_instead,
        "origin_quote": le.origin_quote,
        "origin": le.origin.value,
        "source_session": le.source_session,
        "created": le.created.isoformat(),
        "policies": _policy_summary(le),
        "fire_count": fires,
    }


def review_pending() -> list[dict[str, Any]]:
    """List the PENDING proposals awaiting review (keep or veto). These are entities
    Precept drafted from your sessions that have not yet taken effect."""
    return [
        {"id": le.id, "type": le.artifact_type.value, "trigger": le.trigger}
        for le in catalog.load_all()
        if le.status.value == "pending"
    ]


def review_decide(entity_id: str, decision: str, reason: str | None = None) -> dict[str, Any]:
    """Apply the review gate to one entity. `decision` is "keep" (PENDING -> ACTIVE;
    a deterministic entity is compiled into enforcement) or "veto" (archived, stops
    enforcing; the card file is never deleted). This runs the exact same path as
    `precept keep` / `precept delete`; `reason` is recorded for context only."""
    from . import review_actions

    le = _find(entity_id)
    if le is None:
        return {"error": f"no entity with id {entity_id!r}"}
    d = (decision or "").lower().strip()
    if d == "keep":
        res = review_actions.keep_lesson(le)
        return {"id": le.id, "decision": "kept", **res}
    if d == "veto":
        res = review_actions.veto_lesson(le)
        return {"id": le.id, "decision": "vetoed", **res}
    return {"error": f"decision must be 'keep' or 'veto', got {decision!r}"}


def build_server() -> Any:
    """Construct the FastMCP server with the four tools registered. Lazy-imports the
    optional `mcp` SDK so the core package never depends on it."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - exercised via the CLI message
        raise ImportError(
            "the MCP server needs the optional extra: pip install 'precept[mcp]'"
        ) from e

    mcp = FastMCP("precept")
    mcp.tool()(catalog_search)
    mcp.tool()(entity_show)
    mcp.tool()(review_pending)
    mcp.tool()(review_decide)
    return mcp


def serve() -> None:
    """Run the stdio MCP server (blocks)."""
    build_server().run(transport="stdio")
