"""The enforcement hot path: a fixed, hardened interpreter over compiled policy DATA.

STDLIB ONLY by design — this runs on every guarded tool call as a fresh process,
so it imports no pydantic and no SDK. It reads the plain-JSON policy cache that
COMPILE produced (rules are data, never code; this file never eval()s anything).

Decision precedence mirrors Cedar/OPA: deny > ask > rewrite > allow; no matching
HARD policy -> allow (the call proceeds).
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from . import paths
from .adapters import claude_code as cc

# ReDoS / abuse guards for LLM-generated patterns (re2 is the eventual upgrade).
_MAX_PATTERN = 2000
_MAX_FIELD = 200_000
_PRECEDENCE = {"deny": 3, "ask": 2, "rewrite": 1, "allow": 0}


def load_compiled(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or paths.policies_cache()
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []  # no cache yet / unreadable -> enforce nothing (fail open)


def _get_field(tool_input: dict[str, Any], dotted: str) -> str:
    cur: Any = tool_input
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur if isinstance(cur, str) else json.dumps(cur, sort_keys=True)


def _check(value: str, op: str, target: str) -> bool:
    value = value[:_MAX_FIELD]
    target = target[:_MAX_PATTERN]
    try:
        if op == "contains":
            return target in value
        if op == "not_contains":
            return target not in value
        if op == "equals":
            return value == target
        if op == "starts_with":
            return value.startswith(target)
        if op == "glob":
            return fnmatch.fnmatch(value, target)
        if op == "regex":
            return re.search(target, value) is not None
    except re.error:
        return False
    return False


def _matches(match: dict[str, Any] | None, tool_name: str, tool_input: dict[str, Any]) -> bool:
    if not match:
        return False
    if match.get("tool") != tool_name:
        return False
    for cond in match.get("conditions", []):
        if not _check(_get_field(tool_input, cond["field"]), cond["op"], cond["value"]):
            return False
    return True  # empty conditions => matches any call to this tool


def evaluate_pretooluse(event: dict[str, Any], policies: list[dict[str, Any]] | None = None) -> dict:
    """Return the PreToolUse hook output (allow/deny/ask/rewrite) per the live contract."""
    pols = policies if policies is not None else load_compiled()
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}

    hits = [
        p for p in pols
        if p.get("hook_event") == "PreToolUse"
        and p.get("check_kind") == "single_call"
        and _matches(p.get("match"), tool_name, tool_input)
    ]
    if not hits:
        return cc.pretooluse_allow()

    winner = max(hits, key=lambda p: _PRECEDENCE.get(p.get("decision", "allow"), 0))
    decision = winner.get("decision", "allow")
    reason = winner.get("message", "Blocked by a Precept rule.")
    if decision == "deny":
        return cc.pretooluse_deny(reason)
    if decision == "ask":
        return cc.pretooluse_ask(reason)
    if decision == "rewrite" and winner.get("rewrite_to"):
        return cc.pretooluse_rewrite(winner["rewrite_to"], reason)
    return cc.pretooluse_allow()


def _transcript_tool_calls(entries: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Best-effort extraction of (tool_name, tool_input) pairs from the transcript.
    Transcript shape is host-specific — kept defensive + covered by CI fixtures."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for e in entries:
        msg = e.get("message", e)
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append((block.get("name", ""), block.get("input", {}) or {}))
    return calls


def _last_assistant_text(entries: list[dict[str, Any]]) -> str:
    for e in reversed(entries):
        msg = e.get("message", e)
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
    return ""


def evaluate_stop_entries(entries: list[dict[str, Any]], policies: list[dict[str, Any]]) -> dict:
    """Pure trajectory evaluation over already-parsed transcript entries (also used
    by the eval harness, which supplies inline transcripts)."""
    traj = [p for p in policies if p.get("hook_event") == "Stop" and p.get("check_kind") == "trajectory"]
    if not traj:
        return cc.stop_allow()

    calls = _transcript_tool_calls(entries)
    final = _last_assistant_text(entries)

    for p in traj:
        spec = p.get("trajectory") or {}
        requires = spec.get("requires")
        claim = spec.get("claim_pattern", "")
        satisfied = any(_matches(requires, name, inp) for name, inp in calls)
        claiming = bool(claim) and _check(final, "regex", claim)
        if claiming and not satisfied:
            return cc.stop_block(p.get("message", "A required step has not been completed."))
    return cc.stop_allow()


def evaluate_stop(event: dict[str, Any], policies: list[dict[str, Any]] | None = None) -> dict:
    """Trajectory rules: block stopping if a required precondition never happened
    while the agent is claiming success. Reads the transcript from the event."""
    pols = policies if policies is not None else load_compiled()
    entries = cc.read_transcript(event.get("transcript_path", ""))
    return evaluate_stop_entries(entries, pols)
