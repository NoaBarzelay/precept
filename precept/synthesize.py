"""COMPILE step: matcher synthesis — turn a semantic Lesson into an enforcing Policy.

This is where determinism is EARNED (not self-declared): a stronger model (Sonnet)
is asked to produce a deterministic, structured matcher for the correction. If it
can't (`can_compile=False`) or the matcher fails the typed validator gate, we mint
NO policy and the lesson stays soft — fail-closed, never a junk hard-block.

Word-boundary discipline: substring matchers over-match ("npm install" also matches
"pnpm install"), so the synthesizer is told to prefer anchored/`\\b` regex.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .models import (
    CheckKind, Decision, Determinism, EnforcementTier, HookEvent, Lesson, Match,
    Policy, TrajectorySpec,
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
hook_event=Stop, check_kind=trajectory, with requires=(the Match that proves X \
happened) and claim_pattern=(a regex detecting the success claim in the final text).

Matchers must be EXACT. Prefer anchored / word-boundary (\\b) regex over plain \
substrings — e.g. "\\bnpm install" so it does NOT also match "pnpm install".
Only target a real field of a real tool (Bash.command, Edit.file_path, etc.).

Set can_compile=false if the correction is stylistic or needs judgment (e.g. "be \
concise", "don't leave stub code") — those cannot be a mechanical matcher. When in \
doubt, decline; a missed hard-rule is better than a wrong one. Reason first."""


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


def validate_match(match: Match | None) -> bool:
    if match is None:
        return True
    allowed = TOOL_FIELDS.get(match.tool)
    if allowed is None:
        return False
    return all(c.field.split(".")[0] in allowed for c in match.conditions)


def _draft_to_policy(lesson: Lesson, draft: PolicyDraft) -> Policy | None:
    if not draft.can_compile or draft.hook_event is None or draft.check_kind is None:
        return None
    if not validate_match(draft.match):
        return None
    if draft.trajectory is not None and not validate_match(draft.trajectory.requires):
        return None
    try:
        return Policy(
            id=f"{lesson.id}-p1",
            lesson_id=lesson.id,
            enforcement_tier=EnforcementTier.HARD,
            hook_event=draft.hook_event,
            check_kind=draft.check_kind,
            decision=draft.decision or Decision.DENY,
            message=draft.message or lesson.what_to_do_instead,
            match=draft.match,
            trajectory=draft.trajectory,
            rewrite_to=draft.rewrite_to,
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


def compile_lesson(lesson: Lesson, client: Any | None = None) -> Lesson:
    """Attach a synthesized policy if one is possible and none exists yet.
    Downgrades determinism to STYLISTIC (soft) when nothing could be compiled."""
    if lesson.policies:
        return lesson
    policy = synthesize_policy(lesson, client)
    if policy is not None:
        lesson.policies = [policy]
        lesson.signals.deterministic_by_construction = True
    elif lesson.determinism != Determinism.JUDGMENT:
        lesson.determinism = Determinism.STYLISTIC  # honest: it's soft, not enforced
        lesson.signals.deterministic_by_construction = False
    return lesson
