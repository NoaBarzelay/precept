"""Judgment verdicts for judgment-kind rules. Lazy-imported by `enforce` ONLY when
a judgment policy is actually in play, so the deterministic hot path stays stdlib.

A judgment rule ("don't leave stub code", "don't claim done without evidence")
can't be a mechanical matcher — but the GATE is still deterministic (our Stop hook
fires every time). At the gate we ask a cheap model for a structured {ok, reason}
verdict. The judgment_prompt is auditable on the lesson card.

Bias: ok defaults toward True. A judgment FALSE-block (blocking compliant work) is
the costly error, so the model only fails a rule when it's clearly violated. Any
error (no key, network) -> None -> the caller FAILS OPEN.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from . import meter

JUDGE_MODEL = "claude-haiku-4-5"

SYSTEM = """You are a strict but fair gate enforcing ONE rule the user set for their \
coding agent. Given the rule and the agent's final state, decide whether the rule \
is satisfied. Set ok=false ONLY if the rule is CLEARLY violated; when uncertain or \
the rule doesn't apply here, set ok=true (a wrongful block is worse than a miss). \
If ok=false, give a one-sentence reason the agent can act on. Reason first."""


class Verdict(BaseModel):
    reasoning: str = Field(description="brief: does the rule apply, and is it satisfied?")
    ok: bool
    reason: str = ""


def verdict(judgment_prompt: str, context: str, client: Any | None = None) -> Verdict | None:
    try:
        if client is None:
            from . import inference

            client = inference.get_client()
        resp = client.messages.parse(
            model=JUDGE_MODEL,
            max_tokens=512,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"RULE: {judgment_prompt}\n\nAGENT FINAL STATE:\n{context}"}],
            output_format=Verdict,
        )
        meter.record(meter.JUDGE_VERDICT, JUDGE_MODEL, resp)
        return resp.parsed_output
    except Exception as exc:
        from . import inference

        inference.note_failure(meter.JUDGE_VERDICT, exc)  # de-silence; still fail open
        return None  # fail open


# ---------------------------------------------------------------------------
# Consolidated verdict (#4 + #5): ONE call answering every gate question this turn.
# ---------------------------------------------------------------------------
CONSOLIDATED_SYSTEM = """You are a strict but fair gate over SEVERAL checks the user \
set for their coding agent. You are given the agent's final state and a numbered list \
of questions. For EACH question, decide ok (true/false).

Bias hard toward ok=true: a wrongful block is worse than a miss, so set ok=false ONLY \
when the question is CLEARLY answered against the agent. When uncertain or not \
applicable, ok=true.

Two kinds of question:
- kind="claim": the required step was already shown NOT to have happened. So you are \
only judging INTENT: is the agent claiming the task is complete / working / done? \
Set ok=false ONLY if it is clearly claiming completion (that's the violation). If it \
is just narrating progress, asking, or not claiming done, ok=true.
- kind="standard": is the stated standard clearly UNMET in the final state? ok=false \
only if clearly violated; otherwise ok=true.

In every case ok=false means "block this". Answer every question by its id. \
Reason first (brief, per question)."""


class Question(BaseModel):
    """One thing to check at the gate this turn. `kind` frames it for the model:
    a trajectory 'claim' check vs a judgment 'standard'."""

    id: str
    kind: str  # "claim" | "standard"
    prompt: str  # claim: the requirement that was UNMET; standard: the rule text


class QuestionVerdict(BaseModel):
    id: str
    ok: bool  # True = no violation (default-safe)
    reason: str = ""


class ConsolidatedVerdict(BaseModel):
    reasoning: str = Field(description="brief: per-question, does it apply and is it satisfied?")
    verdicts: list[QuestionVerdict]


def consolidated_verdict(
    questions: list[Question],
    context: str,
    client: Any | None = None,
) -> dict[str, QuestionVerdict] | None:
    """Ask the model ONCE about all gate questions for this turn. Returns a
    {id -> QuestionVerdict} map, or None on any failure (caller FAILS OPEN).
    Missing/extra ids in the response are tolerated; a missing id is treated as
    ok=True by the caller (default-safe)."""
    if not questions:
        return {}
    try:
        if client is None:
            from . import inference

            client = inference.get_client()
        listing = "\n".join(
            f"- id={q.id} kind={q.kind}: {q.prompt}" for q in questions
        )
        resp = client.messages.parse(
            model=JUDGE_MODEL,
            max_tokens=1024,
            system=CONSOLIDATED_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": f"AGENT FINAL STATE:\n{context}\n\nQUESTIONS:\n{listing}",
                }
            ],
            output_format=ConsolidatedVerdict,
        )
        meter.record(meter.JUDGE_CONSOLIDATED, JUDGE_MODEL, resp)
        return {v.id: v for v in resp.parsed_output.verdicts}
    except Exception as exc:
        from . import inference

        inference.note_failure(meter.JUDGE_CONSOLIDATED, exc)  # de-silence; still fail open
        return None  # fail open


# ---------------------------------------------------------------------------
# Conflict detection (item 6): does a PAIR of rules contradict? This is the same
# LLM-judge seam — injectable so governance stays deterministic + fail-open in tests.
# ---------------------------------------------------------------------------
CONFLICT_SYSTEM = """You decide whether TWO rules a user set for their coding agent \
CONTRADICT — i.e. obeying one necessarily violates the other (e.g. "always use npm" vs \
"never use npm, use pnpm"). Two rules that merely cover different topics, or that can both \
be satisfied at once, do NOT conflict. Bias toward conflicts=false: only flag a CLEAR, \
direct contradiction. If they conflict, name the field/behavior they disagree on. \
Reason first."""


class ConflictVerdict(BaseModel):
    reasoning: str = Field(description="brief: can both rules be obeyed at once?")
    conflicts: bool
    reason: str = ""


def conflict_verdict(rule_a: str, rule_b: str, client: Any | None = None) -> ConflictVerdict | None:
    """Ask whether two rule descriptions contradict. None on any failure (caller treats
    None as 'no conflict' — fail-open: never propose retiring a rule on a model hiccup)."""
    try:
        if client is None:
            from . import inference

            client = inference.get_client()
        resp = client.messages.parse(
            model=JUDGE_MODEL,
            max_tokens=512,
            system=CONFLICT_SYSTEM,
            messages=[{"role": "user", "content": f"RULE A:\n{rule_a}\n\nRULE B:\n{rule_b}"}],
            output_format=ConflictVerdict,
        )
        meter.record(meter.JUDGE_CONFLICT, JUDGE_MODEL, resp)
        return resp.parsed_output
    except Exception as exc:
        from . import inference

        inference.note_failure(meter.JUDGE_CONFLICT, exc)  # de-silence; still fail open
        return None  # fail open
