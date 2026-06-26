"""The typed spine of Precept.

Two objects carry the whole system:

  Lesson   - what the DETECT classifier extracts from a correction the user made.
             Captured from explicit signal only (a real correction), never inferred.

  Policy   - the COMPILE step's output: a Lesson's deterministic core lowered into an
             executable intermediate representation (the "policy IR"). The ENFORCE hook
             matches Policies against PreToolUse events and BLOCKS the ones that violate.

Keeping these as Pydantic models (not free-form dicts) is the point: the same types flow
classifier -> catalog card -> hook, so coverage is *measurable* (what fraction of lessons
lower to a hard Policy vs. fall back to soft injection) and every rule is auditable.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Determinism(str, Enum):
    """Can this lesson be checked mechanically, or only nudged?

    DETERMINISTIC  -> compiles to a hard PreToolUse BLOCK (the wedge: ~100% adherence).
    STYLISTIC      -> no mechanical check exists ("be more concise"); falls back to soft
                      context injection (~70% adherence). We bound this honestly.
    """

    DETERMINISTIC = "deterministic"
    STYLISTIC = "stylistic"


class Status(str, Enum):
    """A lesson's lifecycle. The pending -> active gate is the credibility core:
    a noisy classifier that mints junk destroys trust, so nothing enforces until a human keeps it.
    """

    PENDING = "pending"  # classifier proposed it; awaiting human keep/delete
    ACTIVE = "active"  # kept by the user; enforced/injected
    ARCHIVED = "archived"  # retired (superseded, decayed, or never triggered)


class Action(str, Enum):
    """What a Policy does when it matches a tool call mid-trajectory."""

    BLOCK = "block"  # deny the tool call pre-completion (the wedge)
    WARN = "warn"  # allow, but surface a warning
    INJECT = "inject"  # soft context only (stylistic fallback)


class Lesson(BaseModel):
    """One correction the user gave the agent, captured as structured, auditable data."""

    id: str = Field(description="stable slug, e.g. 'run-tests-before-success'")
    created: date
    source_session: str = Field(description="transcript/session id this was extracted from")
    status: Status = Status.PENDING
    confidence: float = Field(ge=0.0, le=1.0, description="classifier confidence at mint time")

    # The lesson content. Note prefer-Y, not just avoid-X: an enforceable rule needs a
    # positive target ("use pnpm"), not only a prohibition ("don't use npm").
    trigger: str = Field(description="the context/action that should fire this rule")
    what_was_wrong: str
    what_to_do_instead: str = Field(description="the prefer-Y target")
    scope: str = Field(description="where it applies, e.g. 'this repo' / 'all node projects'")
    origin_quote: str = Field(description="the user's exact words that produced this lesson")

    determinism: Determinism


class Match(BaseModel):
    """The condition half of a Policy: when does this rule apply to a tool call?

    Deliberately simple and inspectable - regex/substring over the tool name and its
    stringified arguments. No ML in the hot path; the hook must be fast and explainable.
    """

    tool: str = Field(description="the Claude Code tool this guards, e.g. 'Bash'")
    arg_pattern: str | None = Field(
        default=None,
        description="regex matched against the tool's stringified input; None = any input",
    )
    forbidden_substrings: list[str] = Field(
        default_factory=list,
        description="if any appears in the input, the match fires (e.g. ['npm install'])",
    )


class Policy(BaseModel):
    """The compiled, executable form of a Lesson's deterministic core - the policy IR.

    This is what makes Precept 'policy-as-code': a typed, portable rule that an adapter
    lowers to a Claude Code PreToolUse hook today, and (the one allowed stretch) to a
    generic CI/pre-commit check tomorrow. Enforcement and audit travel; inference does not.
    """

    id: str
    lesson_id: str = Field(description="provenance: which Lesson this came from")
    match: Match
    action: Action = Action.BLOCK
    message: str = Field(description="shown to the agent/user when the policy fires")
