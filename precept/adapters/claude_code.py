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

UserPromptSubmit stdin: {session_id, transcript_path, cwd, permission_mode,
  hook_event_name: "UserPromptSubmit", prompt}
UserPromptSubmit stdout (exit 0):
  - block + ERASE the prompt: {"decision": "block", "reason": str}  (reason shown to the
    user, NOT fed to the model)
  - inject context (prompt proceeds): {"hookSpecificOutput": {"hookEventName":
    "UserPromptSubmit", "additionalContext": str}}
  - omit (return {}) to let the prompt proceed unchanged.
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


def stop_context(additional_context: str) -> dict:
    """Allow the stop but inject context (item 3: proactively surface a drafted rule).
    The Stop hook reads `hookSpecificOutput.additionalContext` like the other surfaces."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": additional_context,
        }
    }


# --- SessionStart -----------------------------------------------------------
def sessionstart_allow() -> dict:
    return {}  # nothing to inject this session


def sessionstart_context(additional_context: str) -> dict:
    """SessionStart can only inject context (it cannot block). Used to surface any
    still-unreviewed drafted rules at the top of a new session (item 3)."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }


# --- UserPromptSubmit decisions ---------------------------------------------
def userpromptsubmit_allow() -> dict:
    return {}  # exit 0, no output -> the prompt proceeds unchanged


def userpromptsubmit_block(reason: str) -> dict:
    # blocks prompt processing and ERASES the prompt; `reason` is shown to the user.
    return {"decision": "block", "reason": reason}


def userpromptsubmit_context(additional_context: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }


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
