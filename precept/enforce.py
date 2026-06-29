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
import os
import re
from pathlib import Path
from typing import Any, Callable

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
        if op == "not_regex":  # matches when the pattern is ABSENT (presence-required rules)
            return re.search(target, value) is None
    except re.error:
        return False
    return False


def _in_scope(policy: dict[str, Any], cwd: str) -> bool:
    """Scope gate (item C). Default GLOBAL: a policy fires everywhere unless it
    declares a narrower scope. Missing scope/scope_value => global (back-compat: old
    caches, and the eval/test callers that pass cwd="", fire all global rules).

    REPO: fire only when cwd is at/under the stored repo root. The fail-OPEN bias is
    INVERTED here on purpose — a repo-scoped rule with no usable cwd is SKIPPED (we
    can't confirm we're in its repo), which is narrower, never wider, so it never
    wedges a session (skipping = allow)."""
    scope = policy.get("scope") or "global"
    if scope == "global":
        return True
    if scope == "repo":
        sv = policy.get("scope_value")
        if not sv or not cwd:
            return False  # can't place cwd inside the repo -> don't fire a repo rule globally
        try:
            cwd_r = os.path.realpath(cwd)
            root_r = os.path.realpath(sv)
        except OSError:
            return False
        return cwd_r == root_r or cwd_r.startswith(root_r + os.sep)
    if scope == "language":
        return True  # TODO(item C follow-up): real language detection from cwd; global for now
    return True  # unknown scope -> fire (fail-open, never wedge)


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
    cwd = event.get("cwd", "") or ""

    hits = [
        p for p in pols
        if p.get("hook_event") == "PreToolUse"
        and p.get("check_kind") == "single_call"
        and _in_scope(p, cwd)
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


def _consolidated_judge(questions: list[dict[str, Any]], context: str):
    """Lazy bridge to the judgment model — keeps the deterministic path stdlib;
    the anthropic SDK / judge is imported ONLY when there are AI questions to ask
    this turn (the caller returns before reaching here if `questions` is empty)."""
    from . import judge

    qs = [judge.Question(**q) for q in questions]
    return judge.consolidated_verdict(qs, context)


def _stop_context(final: str, calls: list[tuple[str, dict[str, Any]]]) -> str:
    tools = "; ".join(f"{n}({json.dumps(i)[:120]})" for n, i in calls[-10:]) or "(none)"
    return f"Final assistant message:\n{final}\n\nRecent tool calls: {tools}"


def _ok(v: Any) -> bool:
    """Read `ok` whether the verdict is a pydantic QuestionVerdict (production) or a
    plain dict (the eval harness / tests inject dicts). Keeps enforce stdlib-only."""
    got = getattr(v, "ok", None)
    if got is None and isinstance(v, dict):
        got = v.get("ok")
    return bool(got)


def _reason(v: Any) -> str:
    got = getattr(v, "reason", None)
    if got is None and isinstance(v, dict):
        got = v.get("reason")
    return got or ""


def evaluate_stop_entries(
    entries: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    verdict_fn: Callable[[list, str], dict | None] | None = None,
    cwd: str = "",
) -> dict:
    """Evaluate Stop rules over already-parsed transcript entries (also used by the
    eval harness, which supplies inline transcripts).

    Flow: run the cheap deterministic gates first to decide WHICH AI questions
    actually need asking, then ask the model ONCE (a single consolidated verdict
    over all questions). Block on the first violation in question order.
      - trajectory: deterministic half asks "did a call matching `requires` happen?".
        If UNMET, an AI 'claim' question asks "is the agent claiming completion?".
      - judgment:   an optional `applies_when` relevance gate skips the rule for FREE
        when no tool call this turn matches; otherwise a 'standard' question is asked.

    `verdict_fn(questions, context) -> {id: verdict} | None` is the injection seam:
    production leaves it None (the real lazy judge); tests/eval pass a fake. FAIL
    OPEN: a None/empty result never blocks (never wedge the session)."""
    traj = [
        p for p in policies
        if p.get("hook_event") == "Stop" and p.get("check_kind") == "trajectory" and _in_scope(p, cwd)
    ]
    judg = [
        p for p in policies
        if p.get("hook_event") == "Stop" and p.get("check_kind") == "judgment" and _in_scope(p, cwd)
    ]
    if not traj and not judg:
        return cc.stop_allow()

    calls = _transcript_tool_calls(entries)
    final = _last_assistant_text(entries)

    # 1. Deterministic gates -> collect the AI questions that actually need asking.
    questions: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    for p in traj:
        spec = p.get("trajectory") or {}
        requires = spec.get("requires")
        satisfied = any(_matches(requires, name, inp) for name, inp in calls)
        if satisfied:
            continue  # requirement met -> rule moot, no question
        # Requirement UNMET: the claim/intent decision is an AI verdict (#4).
        questions.append({
            "id": p["id"],
            "kind": "claim",
            "prompt": p.get("message") or "The required step did not happen before finishing.",
        })
        by_id[p["id"]] = p

    for p in judg:
        aw = p.get("applies_when")  # #5 relevance gate
        if aw is not None and not any(_matches(aw, n, i) for n, i in calls):
            continue  # not relevant this turn -> skip for FREE (no question, no model)
        questions.append({
            "id": p["id"],
            "kind": "standard",
            "prompt": p.get("judgment_prompt", ""),
        })
        by_id[p["id"]] = p

    # 2. All-deterministic fast path: nothing to ask -> allow, zero model import.
    if not questions:
        return cc.stop_allow()

    # 3. ONE verdict call (fail open on None/empty).
    context = _stop_context(final, calls)
    vf = verdict_fn or _consolidated_judge
    result = vf(questions, context)
    if not result:
        return cc.stop_allow()

    # 4. Block on the first violation, in question order (trajectory then judgment).
    for q in questions:
        v = result.get(q["id"])
        if v is not None and not _ok(v):  # missing id => ok (default-safe)
            p = by_id[q["id"]]
            return cc.stop_block(p.get("message") or _reason(v) or "A required standard was not met.")
    return cc.stop_allow()


def evaluate_stop(event: dict[str, Any], policies: list[dict[str, Any]] | None = None) -> dict:
    """Trajectory rules: block stopping if a required precondition never happened
    while the agent is claiming success. Reads the transcript from the event."""
    pols = policies if policies is not None else load_compiled()
    entries = cc.read_transcript(event.get("transcript_path", ""))
    return evaluate_stop_entries(entries, pols, cwd=event.get("cwd", "") or "")
