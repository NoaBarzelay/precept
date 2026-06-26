"""Claude Code hook wire-format adapter. Stdlib only (runs in the hot path).

Verified against the live contract (code.claude.com/docs/en/hooks, 2026-06-26):

PreToolUse stdin: {session_id, transcript_path, cwd, permission_mode,
  hook_event_name, tool_name, tool_input}
PreToolUse stdout (exit 0): {"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "allow"|"deny"|"ask"|"defer",
  "permissionDecisionReason": str, "updatedInput": {...}, "additionalContext": str}}

Stop stdin: {session_id, transcript_path, cwd, permission_mode, hook_event_name, effort}
Stop stdout (exit 0): {"decision": "block", "reason": str}  (omit to allow)
  -> there is NO stop_hook_active field or block cap in the current contract.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def read_event() -> dict[str, Any]:
    """Parse the hook payload from stdin. Returns {} on any parse failure so the
    caller can FAIL OPEN rather than block the user on a host-format change."""
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def emit(obj: dict[str, Any]) -> None:
    if obj:
        sys.stdout.write(json.dumps(obj))


# --- PreToolUse decisions ---------------------------------------------------
def pretooluse_allow(updated_input: dict | None = None) -> dict:
    out: dict[str, Any] = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    if updated_input is not None:
        out["updatedInput"] = updated_input
    return {"hookSpecificOutput": out}


def pretooluse_deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def pretooluse_ask(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }


def pretooluse_rewrite(updated_input: dict, reason: str = "") -> dict:
    out: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": updated_input,
    }
    if reason:
        out["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": out}


# --- Stop decisions ---------------------------------------------------------
def stop_block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def stop_allow() -> dict:
    return {}  # omitting `decision` lets Claude stop


def read_transcript(path: str) -> list[dict[str, Any]]:
    """Best-effort parse of the transcript JSONL. The transcript IS the session
    state — trajectory rules re-derive history from it, no separate store."""
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
    except OSError:
        pass
    return out
