"""CAPTURE — mine durable KNOWLEDGE from a session and file it into the vault (slice 2).

Rides the SAME per-turn detect pass (off the Stop hook). Where DETECT mines rule
*corrections*, CAPTURE mines durable *knowledge worth filing* (a fact, an entity, a
decision the user stated) and writes it as a proper `type: knowledge` vault file —
AUTO-ROUTED to the best-matching existing folder via the index (entities = folders),
proposing a NEW folder only when clearly novel.

Discipline (same spine as DETECT):
  - PROVENANCE GATE: only genuine user-typed turns are mined (never the agent's own text,
    never tool-result-only turns) — that is how junk/abuse stays out.
  - Structured extraction via `messages.parse` with `MaybeKnowledge`, an explicit abstain
    path, biased HARD toward abstaining (capture auto-writes without asking).
  - FAIL-CLOSED on any classifier error (abstain — never mint on failure).
  - The written file is PENDING / needs-confirmation (never silently final); the review
    surface (extended for knowledge) lists it so the user keeps or drops it.

This module imports the Anthropic SDK lazily and stays off the hot path; it runs in the
detached `precept detect` process, after the rule-correction pass.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Any, Protocol

from .. import meter
from ..models import MaybeKnowledge
from . import config as kconfig
from . import store

CAPTURE_MODEL = "claude-haiku-4-5"  # cheap, schema-constrained extraction (mirrors DETECT)
_MAX_TURNS = 8

# Recall-biased PRE-FILTER (cost gate only, like DETECT's): cheap cues that a user turn
# might STATE durable knowledge worth filing — a definition, an attribution, a fact, a
# standing decision. Over-fires by design (a needless cheap LLM call is fine); a miss would
# drop real knowledge. The semantic decision stays the LLM.
_PREFILTER = re.compile(
    r"\b(is|are|was|were|means|stands for|founded|acquired|raised|led by|"
    r"remember|note that|fyi|for the record|turns out|the (?:ceo|founder|fund|company|"
    r"thesis|valuation)|headquartered|based in)\b",
    re.IGNORECASE,
)


def looks_like_knowledge(turns: list[str]) -> bool:
    """The pre-filter gate: might ANY of these user turns state durable knowledge? Recall-
    biased (over-fires); a True only earns a (cheap) LLM classification call."""
    return any(_PREFILTER.search(t or "") for t in turns)


SYSTEM = """You inspect the tail of a coding/research-agent session and decide whether the \
USER stated DURABLE KNOWLEDGE worth filing as a lasting note — a fact, an entity \
description, an attribution, a decision, or a definition that will be useful to recall \
later (e.g. "Bessemer is a venture firm founded in 1911", "we decided the API lives in \
src/api", "Midway 1942 was the turning point of the Pacific war").

Abstain (is_knowledge=false) when there is NO durable, file-worthy knowledge: a task or \
command, a question, small talk, a transient status, a correction of the agent (that is \
handled elsewhere), or the agent's own text. Bias HARD toward abstaining — a junk note \
is worse than a missed one, and what you extract is auto-written without asking.

When you DO extract:
- title: the entity/topic, Title Case — this becomes the filename and the routing key.
- body: the durable knowledge in a few clear, self-contained sentences.
- tags: 0-3 lowercase topical tags, or none.
- sources: only URLs/citations the USER actually provided; NEVER invent one. Empty is fine.
Reason briefly in chain_of_thought first, then fill the fields."""


class _ParseClient(Protocol):  # the slice of the Anthropic client we use (for testing)
    class messages:  # noqa: N801
        @staticmethod
        def parse(**kwargs: Any) -> Any: ...


def _build_context(turns: list[str]) -> str:
    tail = turns[-_MAX_TURNS:]
    if not tail:
        return ""
    return "Recent USER turns (most recent last):\n\n" + "\n---\n".join(tail)


def classify(context: str, client: _ParseClient | None = None) -> MaybeKnowledge:
    """One schema-constrained classifier call. FAILS CLOSED (abstains) on any error."""
    try:
        if client is None:
            from .. import inference

            client = inference.get_client()
        resp = client.messages.parse(
            model=CAPTURE_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": context}],
            output_format=MaybeKnowledge,
        )
        meter.record(meter.CAPTURE, CAPTURE_MODEL, resp)
        return resp.parsed_output
    except Exception as exc:  # network, parse, validation — never file on failure
        from .. import inference

        inference.note_failure(meter.CAPTURE, exc)  # de-silence: record, then still abstain
        return MaybeKnowledge(
            chain_of_thought="classifier unavailable",
            is_knowledge=False,
            abstain_reason=f"fail-closed: {type(exc).__name__}",
        )


def capture_from_turns(
    turns: list[str], *, today: _date | None = None, client: _ParseClient | None = None,
) -> store.WriteResult | None:
    """Classify the given (already provenance-filtered) user turns and, if durable knowledge
    is present, FILE it as a PENDING knowledge file in the vault — auto-routed to the best
    folder. Returns the WriteResult, or None when nothing was captured.

    FAIL-OPEN end to end: a missing vault (PRECEPT_VAULT unset) or any classifier/IO error
    quietly yields None — capture never wedges the detached detect pass."""
    if not turns or not looks_like_knowledge(turns):
        return None
    # A vault must be configured to file into; absent one, capture is a no-op (never guess).
    try:
        kconfig.resolve_vault()
    except ValueError:
        return None
    context = _build_context(turns)
    if not context:
        return None
    maybe = classify(context, client)
    if not maybe.is_knowledge or maybe.knowledge is None:
        return None
    k = maybe.knowledge
    try:
        return store.file_knowledge(
            k.title, k.body, tags=k.tags or None, sources=k.sources or None,
            pending=True, today=today,
        )
    except Exception:
        return None  # fail-open: never let capture break the detect pass
