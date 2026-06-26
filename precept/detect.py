"""DETECT — turn a real correction in a session transcript into a PENDING lesson.

Design (see DECISIONS.md):
  - Runs off the Stop / SessionEnd hook, fire-and-forget, fail-CLOSED.
  - PROVENANCE GATE: only genuine user-typed turns are considered as corrections;
    we never mint a lesson from the agent's own text (that's how junk/abuse gets in).
  - Structured extraction via the Anthropic SDK `messages.parse` with `MaybeLesson`
    as the schema: a leading `chain_of_thought`, then an explicit abstain path
    (`is_lesson=False`) — the single most important precision control.
  - Output is always PENDING (origin=CORRECTION). A human `precept keep`s it before
    anything enforces. Matcher synthesis (lesson -> enforcing Policy) is COMPILE's job.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Any, Protocol

from . import catalog
from .adapters import claude_code as cc
from .models import (
    Determinism, ExtractedLesson, GroundedSignals, Lesson, MaybeLesson, Origin, Status,
)

CLASSIFIER_MODEL = "claude-haiku-4-5"  # cheap, schema-constrained extraction
_MAX_TURNS = 8  # only look at the tail of the conversation

SYSTEM = """You inspect the tail of a coding-agent session and decide whether the \
USER corrected the agent — and if so, extract ONE durable, reusable lesson.

A correction is the user telling the agent it did something wrong or should do \
something differently in the future (e.g. "no, never use npm, use pnpm", "you \
didn't run the tests", "stop editing files in src/, those are generated").

Abstain (is_lesson=false) when there is NO genuine correction: a new task, a \
question, praise, a one-off preference with no future relevance, or the agent's \
own text. Bias toward abstaining — a false lesson is worse than a missed one.

When you do extract a lesson:
- what_to_do_instead must be a positive target (prefer-Y), not only a prohibition.
- origin_quote must be the user's exact words.
- determinism: "deterministic" if it could be checked mechanically (a banned/required \
command, a protected file path); "judgment" if it needs a verdict ("don't leave \
stub code"); "stylistic" if it's purely about tone/format.
Reason briefly in chain_of_thought first, then fill the fields."""


class _ParseClient(Protocol):  # the slice of the Anthropic client we use (for testing)
    class messages:  # noqa: N801
        @staticmethod
        def parse(**kwargs: Any) -> Any: ...


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:6]) or "lesson"


def _user_turns(entries: list[dict[str, Any]]) -> list[str]:
    """Provenance gate: extract only genuine user-authored text turns."""
    turns: list[str] = []
    for e in entries:
        msg = e.get("message", e)
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            turns.append(content)
        elif isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            # skip tool_result-only user turns (not human-typed)
            if text.strip():
                turns.append(text)
    return turns


def _build_context(entries: list[dict[str, Any]]) -> str:
    turns = _user_turns(entries)
    if not turns:
        return ""
    tail = turns[-_MAX_TURNS:]
    return "Recent USER turns (most recent last):\n\n" + "\n---\n".join(tail)


def classify(context: str, client: _ParseClient | None = None) -> MaybeLesson:
    """One schema-constrained classifier call. FAILS CLOSED (abstains) on any error."""
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=CLASSIFIER_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": context}],
            output_format=MaybeLesson,
        )
        return resp.parsed_output
    except Exception as exc:  # network, parse, validation — never mint on failure
        return MaybeLesson(
            chain_of_thought="classifier unavailable",
            is_lesson=False,
            abstain_reason=f"fail-closed: {type(exc).__name__}",
        )


def lesson_from_extraction(ex: ExtractedLesson, *, session: str, today: _date | None = None) -> Lesson:
    quote = ex.origin_quote.strip()
    imperative = bool(re.search(r"\b(never|always|don'?t|stop|must|use)\b", quote, re.I))
    return Lesson(
        id=_slugify(ex.what_to_do_instead or ex.trigger),
        created=today or _date.today(),
        origin=Origin.CORRECTION,
        source_session=session,
        status=Status.PENDING,
        scope=ex.scope,
        durability=ex.durability,
        determinism=ex.determinism,
        artifact_type=ex.proposed_artifact_type,
        trigger=ex.trigger,
        what_was_wrong=ex.what_was_wrong,
        what_to_do_instead=ex.what_to_do_instead,
        origin_quote=quote,
        signals=GroundedSignals(
            has_verbatim_quote=bool(quote),
            imperative_correction=imperative,
            deterministic_by_construction=ex.determinism == Determinism.DETERMINISTIC,
        ),
        policies=[],  # matcher synthesis is COMPILE's job; PENDING until reviewed + compiled
    )


def detect_from_transcript(
    transcript_path: str, *, session: str = "", client: _ParseClient | None = None
) -> list[Lesson]:
    """Read a transcript, classify, and write any minted lesson as a PENDING card.
    Returns the minted lessons (empty if abstained or nothing new)."""
    entries = cc.read_transcript(transcript_path)
    context = _build_context(entries)
    if not context:
        return []
    maybe = classify(context, client)
    if not maybe.is_lesson or maybe.lesson is None:
        return []
    lesson = lesson_from_extraction(maybe.lesson, session=session or transcript_path)
    # cheap dedup: don't re-mint an id that already exists (LLM consolidation is later)
    if catalog.card_path(lesson.id).exists():
        return []
    catalog.write(lesson)
    return [lesson]
