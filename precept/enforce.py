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


def load_context_rules(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the authored context rules (item A) as plain dicts. STDLIB only / FAIL-OPEN:
    a missing or unreadable file injects nothing."""
    p = path or paths.context_rules_path()
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _context_matches(rule: dict[str, Any], tool_name: str, tool_input: dict[str, Any]) -> bool:
    """A context rule matches when the tool name is equal and (if a path_pattern is set) the
    tool's file_path passes the pattern. No path_pattern => the tool name alone matches."""
    if rule.get("tool") != tool_name:
        return False
    pattern = rule.get("path_pattern")
    if not pattern:
        return True
    return _check(_get_field(tool_input, "file_path"), rule.get("path_op", "glob"), pattern)


def _collect_context(
    context_rules: list[dict[str, Any]] | None, tool_name: str, tool_input: dict[str, Any]
) -> str | None:
    """Concatenated text of every context rule that matches this call, or None. The order is
    the rules' file order, so the injection is stable/auditable."""
    rules = context_rules if context_rules is not None else load_context_rules()
    texts = [
        r["text"]
        for r in rules
        if r.get("text") and _context_matches(r, tool_name, tool_input)
    ]
    return "\n\n".join(texts) if texts else None


def _matches(match: dict[str, Any] | None, tool_name: str, tool_input: dict[str, Any]) -> bool:
    if not match:
        return False
    if match.get("tool") != tool_name:
        return False
    for cond in match.get("conditions", []):
        if not _check(_get_field(tool_input, cond["field"]), cond["op"], cond["value"]):
            return False
    return True  # empty conditions => matches any call to this tool


def evaluate_pretooluse(
    event: dict[str, Any],
    policies: list[dict[str, Any]] | None = None,
    context_rules: list[dict[str, Any]] | None = None,
) -> dict:
    """Return the PreToolUse hook output (allow/deny/ask/rewrite) per the live contract.

    Context rules (item A) ride ON TOP of the allow decision: after the deny/ask/rewrite
    resolution, only when the call is otherwise ALLOWED do we attach any matching context
    rules' concatenated text as additionalContext. A deny/ask wins and blocks; a rewrite
    keeps its own shape — context rules never change the verdict, they only add a reminder."""
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
    if hits:
        winner = max(hits, key=lambda p: _PRECEDENCE.get(p.get("decision", "allow"), 0))
        decision = winner.get("decision", "allow")
        reason = winner.get("message", "Blocked by a Precept rule.")
        if decision == "deny":
            return cc.pretooluse_deny(reason)
        if decision == "ask":
            return cc.pretooluse_ask(reason)
        if decision == "rewrite" and winner.get("rewrite_to"):
            # updatedInput REPLACES the tool's arguments wholesale (per the hook contract),
            # so a partial rewrite_to must be MERGED over the original input or it would drop
            # the sibling fields (e.g. a {new_string: ...} rewrite would erase file_path).
            merged = {**tool_input, **winner["rewrite_to"]}
            return cc.pretooluse_rewrite(merged, reason)

    # Otherwise ALLOW -> attach any matching context-rule reminders (item A).
    ctx = _collect_context(context_rules, tool_name, tool_input)
    return cc.pretooluse_allow(additional_context=ctx)


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


def _stop_already_surfaced(session_id: str, policy_id: str) -> bool:
    """Has this judgment Stop policy already blocked once this session? Per-session dedupe
    so a judgment nudge fires ONCE and never nags every turn. FAIL-OPEN: any error -> treat
    as not-yet-surfaced (worst case one extra nudge, never a crash)."""
    if not session_id:
        return False
    try:
        led = json.loads(paths.stop_surfaced_ledger().read_text())
        return policy_id in led.get(session_id, [])
    except Exception:
        return False


def _mark_stop_surfaced(session_id: str, policy_id: str) -> None:
    """Record that a judgment Stop policy blocked this session. FAIL-OPEN and atomic."""
    if not session_id:
        return
    try:
        p = paths.stop_surfaced_ledger()
        try:
            led = json.loads(p.read_text())
        except Exception:
            led = {}
        led.setdefault(session_id, [])
        if policy_id not in led[session_id]:
            led[session_id].append(policy_id)
        from .safety import atomic_write_text

        atomic_write_text(p, json.dumps(led))
    except Exception:
        pass  # fail open: a ledger write must never wedge a session


def evaluate_stop_entries(
    entries: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    verdict_fn: Callable[[list, str], dict | None] | None = None,
    cwd: str = "",
    session_id: str = "",
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
            # Per-session dedupe for JUDGMENT rules: a judgment nudge has no objective,
            # satisfiable condition, so block it AT MOST ONCE per session then stop nagging.
            # (Trajectory rules keep blocking until the required call happens — that self-
            # terminates once the step runs, so it never loops.)
            if p.get("check_kind") == "judgment" and session_id:
                if _stop_already_surfaced(session_id, q["id"]):
                    continue  # already surfaced this session -> do not block again
                _mark_stop_surfaced(session_id, q["id"])
            return cc.stop_block(p.get("message") or _reason(v) or "A required standard was not met.")
    return cc.stop_allow()


def evaluate_stop(event: dict[str, Any], policies: list[dict[str, Any]] | None = None) -> dict:
    """Trajectory rules: block stopping if a required precondition never happened
    while the agent is claiming success. Reads the transcript from the event."""
    pols = policies if policies is not None else load_compiled()
    entries = cc.read_transcript(event.get("transcript_path", ""))
    return evaluate_stop_entries(
        entries,
        pols,
        cwd=event.get("cwd", "") or "",
        session_id=str(event.get("session_id", "") or ""),
    )


def evaluate_userpromptsubmit(
    event: dict[str, Any],
    policies: list[dict[str, Any]] | None = None,
    verdict_fn: Callable[[list, str], dict | None] | None = None,
) -> dict:
    """Prompt-time rules (item D). FAIL-OPEN. Two flavors, both scope-filtered by cwd:

      - single_call over the PROMPT TEXT: a Match whose tool == 'UserPromptSubmit' with a
        condition over a synthetic 'prompt' field. A presence-required rule ("the prompt
        must contain the ticket id") uses op=not_regex/not_contains so the Match is TRUE
        exactly when the requirement is VIOLATED (the required thing is missing) -> block.
      - judgment: a model verdict over the prompt (lazy judge), like Stop judgment, riding
        the same consolidated-verdict seam (verdict_fn for tests/eval; real judge in prod).

    Block on the first matching deterministic rule, then the first failed judgment verdict;
    any None/empty verdict never blocks (never erase the user's prompt on a model hiccup)."""
    pols = policies if policies is not None else load_compiled()
    cwd = event.get("cwd", "") or ""
    prompt = event.get("prompt", "") or ""
    ups = [
        p for p in pols
        if p.get("hook_event") == "UserPromptSubmit" and _in_scope(p, cwd)
    ]

    synthetic_input = {"prompt": prompt}
    # 1. Deterministic single_call rules over the prompt text (these can BLOCK).
    for p in ups:
        if p.get("check_kind") == "single_call" and _matches(
            p.get("match"), "UserPromptSubmit", synthetic_input
        ):
            return cc.userpromptsubmit_block(
                p.get("message") or "Blocked by a Precept prompt rule."
            )

    # 2. Judgment prompt rules -> one consolidated verdict (reuse the Stop seam).
    judg = [p for p in ups if p.get("check_kind") == "judgment"]
    if judg:
        questions = [
            {"id": p["id"], "kind": "standard", "prompt": p.get("judgment_prompt", "")}
            for p in judg
        ]
        by_id = {p["id"]: p for p in judg}
        context = f"User prompt:\n{prompt}"
        vf = verdict_fn or _consolidated_judge
        result = vf(questions, context)
        if result:
            for q in questions:
                v = result.get(q["id"])
                if v is not None and not _ok(v):
                    p = by_id[q["id"]]
                    return cc.userpromptsubmit_block(
                        p.get("message") or _reason(v) or "Blocked by a Precept prompt rule."
                    )

    # 3. Not blocking -> retrieval injection: surface (a) relevant vault knowledge (slice 2)
    # and (b) relevant retrieval_only CONVENTIONS (P1, activity-keyed by prompt + cwd) as
    # additionalContext so the prompt proceeds already grounded. Cheap/bounded + FAIL-OPEN
    # (no vault/index/catalog or any error => inject nothing, exactly the prior allow shape).
    parts = [c for c in (_knowledge_retrieval(prompt), _convention_retrieval(prompt, cwd)) if c]
    if parts:
        return cc.userpromptsubmit_context("\n\n".join(parts))
    return cc.userpromptsubmit_allow()


def _knowledge_retrieval(prompt: str) -> str | None:
    """Lazy bridge to the knowledge-pillar retrieval (slice 2). Kept out of the hot
    deterministic path import; any error yields None (fail-open)."""
    try:
        from .knowledge import retrieval

        return retrieval.retrieval_context(prompt)
    except Exception:
        return None


def _convention_retrieval(prompt: str, cwd: str) -> str | None:
    """Lazy bridge to activity-keyed CONVENTION retrieval (P1): inject the retrieval_only
    conventions relevant to this prompt + cwd. Lazy import (pydantic/catalog) keeps the
    deterministic hot path stdlib; any error yields None (fail-open)."""
    try:
        from . import convention

        return convention.retrieval_context(prompt, cwd)
    except Exception:
        return None
