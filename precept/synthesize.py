"""COMPILE step: matcher synthesis — turn a semantic Lesson into an enforcing Policy.

This is where determinism is EARNED (not self-declared): a stronger model (Sonnet)
is asked to produce a deterministic, structured matcher for the correction. If it
can't (`can_compile=False`) or the matcher fails the typed validator gate, we mint
NO policy and the lesson stays soft — fail-closed, never a junk hard-block.

Word-boundary discipline: substring matchers over-match ("npm install" also matches
"pnpm install"), so the synthesizer is told to prefer anchored/`\\b` regex.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .models import (
    CheckKind, Condition, Decision, Determinism, EnforcementTier, HookEvent, Lesson,
    Match, MatchOp, Policy, TrajectorySpec,
)

SYNTH_MODEL = "claude-sonnet-4-6"

# The typed validator gate: a Match may only target a known tool + a real field of it.
TOOL_FIELDS: dict[str, set[str]] = {
    "Bash": {"command"},
    "Edit": {"file_path", "old_string", "new_string"},
    "Write": {"file_path", "content"},
    "Read": {"file_path"},
    "WebFetch": {"url", "prompt"},
    "Glob": {"pattern", "path"},
    "Grep": {"pattern", "path"},
    "NotebookEdit": {"notebook_path", "new_source"},
}

SYSTEM = """You compile ONE correction into a deterministic, mechanical guardrail \
for Claude Code, or decline.

Pick the NARROWEST blocking mechanism:
- A banned/required command or a protected file edit -> hook_event=PreToolUse, \
check_kind=single_call, with a Match over the tool's input field.
- "X must happen before the agent claims it's done" (tests ran, lint passed) -> \
hook_event=Stop, check_kind=trajectory, with ONLY requires=(the Match that proves X \
happened). Do NOT produce a claim regex — whether the agent is claiming completion is \
judged by AI at the Stop gate, not by a pattern.

Matchers must be EXACT. Prefer anchored / word-boundary (\\b) regex over plain \
substrings — e.g. "\\bnpm install" so it does NOT also match "pnpm install".
Only target a real field of a real tool (Bash.command, Edit.file_path, etc.).

PREFER REWRITE for a clean substitution. When the correction is a clean swap — the \
user wants one tool field F changed from Y to X with everything else intact ("use \
pnpm not npm", "use rg not grep") — emit decision=rewrite with \
rewrite_to={"<field>": "<the corrected full field value>"} plus a Match that detects \
the wrong form. rewrite_to REPLACES the named field wholesale, so only use it when a \
single, unambiguous corrected value exists for the WHOLE field — e.g. an exact-command \
swap ("npm install" -> {"command": "pnpm install"}) or an Edit field. Use deny (NOT \
rewrite) when: (a) the op is destructive (rm -rf, reading a secret, editing a protected \
file) — those must be blocked, never silently corrected; or (b) the wrong token is \
embedded in a variadic command where replacing the whole field would drop arguments \
("npm install left-pad" -> a blind field replace would lose "left-pad"). Reason first; \
pick rewrite only when the corrected value is the entire, confident field value.

Set can_compile=false if the correction is stylistic or needs judgment (e.g. "be \
concise", "don't leave stub code") — those cannot be a mechanical matcher. When in \
doubt, decline; a missed hard-rule is better than a wrong one.

For a judgment standard you may optionally set applies_when to the tool activity that \
makes it relevant (e.g. a Match over Edit/Write for a code-quality rule), so the rule \
is only evaluated when that activity occurred this turn. Reason first."""


class PolicyDraft(BaseModel):
    """What the synthesizer emits. We assemble the full Policy (ids/tier) ourselves."""

    reasoning: str = Field(description="brief: what mechanism and why, or why it can't compile")
    can_compile: bool
    hook_event: HookEvent | None = None
    check_kind: CheckKind | None = None
    decision: Decision | None = None
    message: str | None = None
    match: Match | None = None
    trajectory: TrajectorySpec | None = None
    rewrite_to: dict[str, str] | None = None
    applies_when: Match | None = None  # JUDGMENT relevance gate (#5); None = always relevant


def validate_match(match: Match | None) -> bool:
    if match is None:
        return True
    allowed = TOOL_FIELDS.get(match.tool)
    if allowed is None:
        return False
    return all(c.field.split(".")[0] in allowed for c in match.conditions)


# --- Shape classifier: hook vs native permission rule (item B) --------------
# Tools whose path/domain/whole-tool bans Claude Code enforces reliably as a
# settings.json permission rule. Bash is ABSENT on purpose: CC ignores Bash-arg
# patterns (Bash(command:...)) with a startup warning, so a Bash ban MUST stay a hook.
_PERMISSION_SHAPE = {
    "Read": "path", "Edit": "path", "Write": "path",
    "Glob": "path", "Grep": "path", "WebFetch": "domain",
}
# Only these path ops map cleanly to gitignore-style permission specifiers; a regex
# ban does NOT (translating a regex to a gitignore glob is unsafe) -> it stays a hook.
_CLEAN_PATH_OPS = {MatchOp.GLOB, MatchOp.EQUALS, MatchOp.STARTS_WITH}
_PATH_FIELDS = {"file_path", "pattern", "path"}


def _host_of(value: str) -> str | None:
    """Extract a bare hostname from a WebFetch url condition value (a URL or a host)."""
    v = (value or "").strip()
    if not v:
        return None
    host = urlparse(v).netloc if "://" in v else v.split("/")[0]
    host = host.split("@")[-1].split(":")[0].strip()
    # a bare host only: no path/space/regex metacharacters
    if not host or "/" in host or " " in host or any(c in host for c in "()[]\\^$+?"):
        return None
    return host


def _as_permission_rule(match: Match | None, decision: Decision) -> str | None:
    """Return a settings.json permission string for a CLEAN tool+path/domain/whole-tool
    ban ('Read(.env)', 'WebFetch(domain:x)', 'WebSearch'), or None if this ban needs
    argument logic and must stay a PreToolUse hook.

    Only DENY/ASK become permission rules. A Bash.command ban NEVER qualifies (CC ignores
    Bash arg-patterns -> bypassable). Regex path bans don't convert (conservative — a hook
    is always a correct fallback)."""
    if match is None or decision not in (Decision.DENY, Decision.ASK):
        return None
    tool = match.tool
    if tool == "Bash":
        return None
    if not match.conditions:  # whole-tool ban -> bare Tool name
        return tool
    shape = _PERMISSION_SHAPE.get(tool)
    if shape is None or len(match.conditions) != 1:
        return None  # argument logic / unmapped tool -> hook
    cond = match.conditions[0]
    op = MatchOp(cond.op) if not isinstance(cond.op, MatchOp) else cond.op
    if shape == "path":
        if cond.field not in _PATH_FIELDS or op not in _CLEAN_PATH_OPS:
            return None
        spec = cond.value.strip()
        if not spec or " " in spec:
            return None
        # A bare filename/glob passes through (CC path specifiers already use *,**;
        # bare `.env` == `**/.env`, matching at any depth — exactly what we want).
        return f"{tool}({spec})"
    if shape == "domain" and cond.field == "url":
        host = _host_of(cond.value)
        return f"WebFetch(domain:{host})" if host else None
    return None


def _draft_to_policy(lesson: Lesson, draft: PolicyDraft) -> Policy | None:
    if not draft.can_compile or draft.hook_event is None or draft.check_kind is None:
        return None
    if not validate_match(draft.match):
        return None
    if draft.trajectory is not None and not validate_match(draft.trajectory.requires):
        return None
    if not validate_match(draft.applies_when):
        return None
    decision = draft.decision or Decision.DENY
    # Shape classifier (item B): a clean tool+path/domain/whole-tool ban routes to a
    # native settings.json permission rule (auditable, deterministic — NOT LLM-chosen)
    # instead of a hook. Only on a deny/ask single-call PreToolUse policy.
    permission_rule = None
    if (
        draft.hook_event == HookEvent.PRE_TOOL_USE
        and draft.check_kind == CheckKind.SINGLE_CALL
    ):
        permission_rule = _as_permission_rule(draft.match, decision)
    try:
        return Policy(
            id=f"{lesson.id}-p1",
            lesson_id=lesson.id,
            enforcement_tier=EnforcementTier.HARD,
            hook_event=draft.hook_event,
            check_kind=draft.check_kind,
            decision=decision,
            message=draft.message or lesson.what_to_do_instead,
            match=draft.match,
            trajectory=draft.trajectory,
            rewrite_to=draft.rewrite_to,
            applies_when=draft.applies_when,
            scope=lesson.scope,
            scope_value=lesson.scope_value,
            permission_rule=permission_rule,
        )
    except Exception:  # Policy validators rejected the shape -> fail closed
        return None


def synthesize_policy(lesson: Lesson, client: Any | None = None) -> Policy | None:
    """Try to compile a Lesson into one enforcing Policy. Returns None (soft) on any
    failure or if the correction isn't mechanically checkable."""
    if lesson.determinism == Determinism.STYLISTIC:
        return None
    context = (
        f"Correction to compile:\n"
        f"- trigger: {lesson.trigger}\n"
        f"- what was wrong: {lesson.what_was_wrong}\n"
        f"- do instead: {lesson.what_to_do_instead}\n"
        f"- user's words: {lesson.origin_quote}\n"
        f"- scope: {lesson.scope.value}"
    )
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=SYNTH_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": context}],
            output_format=PolicyDraft,
        )
        return _draft_to_policy(lesson, resp.parsed_output)
    except Exception:
        return None  # fail closed: no policy rather than a wrong one


# Cues that a judgment lesson is a CODE-QUALITY standard, hence only relevant on a
# turn that edited code. Keeps the judgment-compile path model-free (item 0 / #5).
_CODE_QUALITY_CUES = (
    "stub", "todo", "placeholder", "dead code", "incomplete", "finish",
    "implement", "no fake", "lazy", "scaffold", "not implemented", "pass  #",
)


def _infer_applies_when(lesson: Lesson) -> Match | None:
    """Best-effort relevance gate (#5) for a JUDGMENT lesson — no LLM call.

    A code-quality standard ("no stub code") is only relevant when the turn edited
    code, so gate it on Edit (the dominant code-mutation tool). `applies_when` is a
    single Match (one tool), so we target Edit rather than widen the schema to an
    OR-of-tools; the cost is only a rare Write-introduced stub (a conservative gate:
    when it doesn't match the rule is skipped for free, never wrongly fired). When no
    confident mapping exists we return None (always-relevant — no regression)."""
    text = f"{lesson.trigger} {lesson.what_was_wrong} {lesson.what_to_do_instead}".lower()
    if any(cue in text for cue in _CODE_QUALITY_CUES):
        return Match(tool="Edit", conditions=[])
    return None


def _judgment_policy(lesson: Lesson, applies_when: Match | None = None) -> Policy:
    """Build a Stop judgment policy directly from the lesson (no LLM needed): the
    gate is deterministic, the verdict prompt is the rule itself (auditable).

    `applies_when` is an optional relevance gate (#5): when set, the rule is only
    asked of the model if the turn's tool activity matches it (else skipped for
    free). The explicit-arg path is kept (a caller can still pass one); when None we
    INFER a sensible gate from the lesson so the free relevance-skip actually fires
    in production (item 0). A None inference => always relevant (no regression)."""
    return Policy(
        id=f"{lesson.id}-p1",
        lesson_id=lesson.id,
        enforcement_tier=EnforcementTier.HARD,
        hook_event=HookEvent.STOP,
        check_kind=CheckKind.JUDGMENT,
        decision=Decision.DENY,
        message=lesson.what_to_do_instead,
        applies_when=applies_when if applies_when is not None else _infer_applies_when(lesson),
        scope=lesson.scope,
        scope_value=lesson.scope_value,
        judgment_prompt=(
            f"Requirement: {lesson.what_to_do_instead}. "
            f"(The user flagged this because: {lesson.what_was_wrong}.) "
            f"Has the agent satisfied this requirement in its final output? "
            f"ok=false only if it clearly has not."
        ),
    )


def compile_lesson(lesson: Lesson, client: Any | None = None) -> Lesson:
    """Attach an enforcing policy if one is possible and none exists yet.
    Judgment lessons get a Stop verdict gate; deterministic ones get a synthesized
    matcher; anything that won't compile is honestly downgraded to soft."""
    if lesson.policies:
        return lesson
    if lesson.determinism == Determinism.JUDGMENT:
        lesson.policies = [_judgment_policy(lesson)]
        return lesson
    policy = synthesize_policy(lesson, client)
    if policy is not None:
        lesson.policies = [policy]
        lesson.signals.deterministic_by_construction = True
    elif lesson.determinism != Determinism.JUDGMENT:
        lesson.determinism = Determinism.STYLISTIC  # honest: it's soft, not enforced
        lesson.signals.deterministic_by_construction = False
    return lesson
