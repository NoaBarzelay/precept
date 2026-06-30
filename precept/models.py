"""The typed spine of Precept (COMPILE-time models).

These Pydantic models are used everywhere EXCEPT the enforcement hot path. The
PreToolUse/Stop hooks must start fast and import nothing heavy, so they read a
compiled, plain-JSON policy cache via `precept.enforce` (stdlib only). COMPILE
turns these models into that cache; nothing here is imported at enforce time.

Design anchors (see the project brief, FINAL+1 hardening section):
  - A session correction becomes a `Lesson`; a Lesson compiles to 1..N `Policy`.
  - A Policy is *data*, never code — `precept.enforce` is a fixed hardened
    interpreter over it (Cedar/OPA discipline).
  - Closed-set fields are Enums so the schema is self-validating and the model
    can only emit legal values during structured extraction.
  - Confidence is GROUNDED (computed from real signals), never an LLM self-report.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Closed sets
# ---------------------------------------------------------------------------
class ArtifactType(str, Enum):
    """The 9 things a session can compile into. RULE is the HARD-enforced wedge;
    the rest are recalled/steered."""

    RULE = "rule"
    KNOWLEDGE = "knowledge"
    CLAUDE_MD = "claude_md"
    SKILL = "skill"
    AGENT_PERSONA = "agent_persona"
    OUTPUT_STYLE = "output_style"
    SLASH_COMMAND = "slash_command"
    MCP_CONFIG = "mcp_config"
    PERMISSION_PROFILE = "permission_profile"


class EnforcementTier(str, Enum):
    """Honesty backbone: only HARD artifacts actually block. Never claim
    enforcement for a SOFT artifact (CLAUDE.md/skill/output-style are context,
    not enforced configuration — Claude Code's own docs say so)."""

    HARD = "hard"  # hook / permission-deny / subagent tool-scoping
    SOFT = "soft"  # CLAUDE.md / skill / output style — steered, not enforced


class Determinism(str, Enum):
    """How a rule is checked. Earned at COMPILE (matcher synthesis), not self-declared."""

    DETERMINISTIC = "deterministic"  # exact/structured check -> hard hook
    JUDGMENT = "judgment"  # LLM verdict {ok,reason} at a deterministic gate -> hard hook
    STYLISTIC = "stylistic"  # no mechanical check -> soft only


class Status(str, Enum):
    PENDING = "pending"  # classifier proposed it; awaiting human keep/veto
    ACTIVE = "active"  # kept; enforced / injected
    ARCHIVED = "archived"  # retired (superseded or decayed)


class HookEvent(str, Enum):
    """Claude Code hook events Precept compiles to. Only these can BLOCK:
    PreToolUse (deny a call) and Stop (refuse to finish)."""

    PRE_TOOL_USE = "PreToolUse"
    STOP = "Stop"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    POST_TOOL_USE = "PostToolUse"  # cannot block — validate/warn only


class CheckKind(str, Enum):
    SINGLE_CALL = "single_call"  # guard one tool call (PreToolUse)
    TRAJECTORY = "trajectory"  # "X must have happened before finishing" (Stop)
    JUDGMENT = "judgment"  # LLM verdict at the gate


class Decision(str, Enum):
    """Mirrors the live PreToolUse contract; `rewrite` maps to `updatedInput`."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    REWRITE = "rewrite"


class Scope(str, Enum):
    GLOBAL = "global"  # applies everywhere
    REPO = "repo"  # this repository
    LANGUAGE = "language"  # e.g. all node projects
    TOOL = "tool"  # tied to a specific tool


class Durability(str, Enum):
    PERSISTENT = "persistent"  # a standing rule
    DECAYING = "decaying"  # retire if it never fires
    EPHEMERAL = "ephemeral"  # one-off / session-local


class Origin(str, Enum):
    CORRECTION = "correction"  # extracted from a real user correction (the trusted path)
    BOOTSTRAP = "bootstrap"  # imported from the user's existing setup at P0
    AGENT_PROPOSED = "agent_proposed"  # suggested by an agent — can only ever be PENDING
    MANUAL = "manual"  # hand-authored


class MatchOp(str, Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    REGEX = "regex"
    NOT_REGEX = "not_regex"  # matches when the pattern is ABSENT (presence-required rules, item D)
    GLOB = "glob"
    STARTS_WITH = "starts_with"


# ---------------------------------------------------------------------------
# Grounded confidence (not an LLM self-report)
# ---------------------------------------------------------------------------
class GroundedSignals(BaseModel):
    """Confidence is composed from observable signals, because verbalized LLM
    confidence is miscalibrated (clusters at 90-100% regardless of correctness)."""

    has_verbatim_quote: bool = False  # an exact user quote backs this lesson
    imperative_correction: bool = False  # phrased as a correction ("never", "always", "stop")
    deterministic_by_construction: bool = False  # compiles to an exact check
    human_kept: bool | None = None  # None=not yet reviewed; True=kept; False=vetoed
    fire_count: int = Field(default=0, ge=0)  # times the compiled policy has actually fired

    def score(self) -> float:
        """A transparent, bounded score in [0,1]. Deliberately simple and auditable."""
        if self.human_kept is False:
            return 0.0
        s = 0.0
        if self.has_verbatim_quote:
            s += 0.30
        if self.imperative_correction:
            s += 0.20
        if self.deterministic_by_construction:
            s += 0.20
        if self.human_kept is True:
            s += 0.20
        if self.fire_count > 0:
            s += 0.10
        return round(min(s, 1.0), 2)


# ---------------------------------------------------------------------------
# Policy IR (Cedar PARC-flavored: action=tool, resource/condition=Match)
# ---------------------------------------------------------------------------
class Condition(BaseModel):
    """One predicate over a field of the tool's input. Structured, not a
    stringify-then-regex hack — keeps matching exact and auditable."""

    field: str = Field(description="dotted path into tool_input, e.g. 'command' or 'file_path'")
    op: MatchOp
    value: str


class Match(BaseModel):
    """The condition half of a Policy: when does this apply to a tool call?
    ALL conditions must hold (AND). Empty conditions = matches any call to `tool`."""

    tool: str = Field(description="the Claude Code tool guarded, e.g. 'Bash', 'Edit'")
    conditions: list[Condition] = Field(default_factory=list)


class TrajectorySpec(BaseModel):
    """For CheckKind.TRAJECTORY (Stop hook): a precondition that must have
    appeared earlier in the session. The deterministic half asks "did a tool call
    matching `requires` happen?"; the "is the agent claiming completion?" half is
    now an AI verdict at the Stop gate (#4), not a regex.

    e.g. requires=(a Bash call matching a test runner)."""

    requires: Match
    claim_pattern: str | None = Field(
        default=None,
        description="DEPRECATED: claim detection is now an AI verdict (#4). Retained "
        "optional only so old compiled caches / golden cases still load; the enforce "
        "path IGNORES it.",
    )


class Policy(BaseModel):
    """The compiled, executable form of (part of) a Lesson. One Lesson -> 1..N."""

    id: str
    lesson_id: str
    enforcement_tier: EnforcementTier
    hook_event: HookEvent
    check_kind: CheckKind
    decision: Decision = Decision.DENY
    message: str = Field(description="permissionDecisionReason / Stop reason shown to the agent")

    # exactly one of these is populated per check_kind
    match: Match | None = None  # SINGLE_CALL / JUDGMENT gate
    trajectory: TrajectorySpec | None = None  # TRAJECTORY
    judgment_prompt: str | None = None  # JUDGMENT (the LLM verdict prompt; the card IS auditable)
    rewrite_to: dict[str, str] | None = None  # REWRITE -> updatedInput
    applies_when: Match | None = None  # JUDGMENT relevance gate (#5): only ask the model
    #                                    when the turn's tool activity matches (free skip).
    #                                    INVARIANT: meaningful ONLY on JUDGMENT policies (the
    #                                    validator below rejects it elsewhere); None = always relevant.

    # Scope (item C): a rule fires everywhere (GLOBAL, the default) unless narrowed.
    scope: Scope = Scope.GLOBAL
    scope_value: str | None = None  # REPO -> the repo root path; LANGUAGE -> a language marker.
    #                                  GLOBAL must leave this None (validator-enforced).

    # Permission compile (item B): a CLEAN tool+path/domain/whole-tool ban can be
    # enforced natively by Claude Code as a settings.json permission rule instead of a
    # PreToolUse hook. When set, COMPILE routes this to settings.json and EXCLUDES the
    # policy from the hook cache (enforce.py never sees it).
    permission_rule: str | None = None

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> "Policy":
        if self.check_kind == CheckKind.TRAJECTORY and self.trajectory is None:
            raise ValueError("TRAJECTORY policy requires a `trajectory` spec")
        if self.check_kind == CheckKind.SINGLE_CALL and self.match is None:
            raise ValueError("SINGLE_CALL policy requires a `match`")
        if self.check_kind == CheckKind.JUDGMENT and not self.judgment_prompt:
            raise ValueError("JUDGMENT policy requires a `judgment_prompt`")
        if self.decision == Decision.REWRITE and not self.rewrite_to:
            raise ValueError("REWRITE decision requires `rewrite_to`")
        # Honesty (item 0): applies_when is only meaningful as a JUDGMENT relevance gate.
        if self.applies_when is not None and self.check_kind != CheckKind.JUDGMENT:
            raise ValueError("applies_when is only meaningful on JUDGMENT policies")
        # Scope (item C): a repo rule needs a root to test cwd against; global carries none.
        if self.scope == Scope.REPO and not self.scope_value:
            raise ValueError("REPO scope requires a `scope_value` (the repo root path)")
        if self.scope == Scope.GLOBAL and self.scope_value is not None:
            raise ValueError("GLOBAL scope must not carry a `scope_value`")
        # Permission rule (item B): only a hard deny/ask single-call PreToolUse ban routes
        # to settings.json; everything else stays a hook.
        if self.permission_rule is not None:
            if self.decision not in (Decision.DENY, Decision.ASK):
                raise ValueError("permission_rule is only valid for DENY/ASK decisions")
            if self.hook_event != HookEvent.PRE_TOOL_USE:
                raise ValueError("permission_rule is only valid for PreToolUse policies")
            if self.check_kind != CheckKind.SINGLE_CALL:
                raise ValueError("permission_rule is only valid for single_call policies")
        # Honesty invariant: only blockable events may carry a hard deny.
        if self.enforcement_tier == EnforcementTier.HARD and self.hook_event not in (
            HookEvent.PRE_TOOL_USE,
            HookEvent.STOP,
            HookEvent.USER_PROMPT_SUBMIT,
        ):
            raise ValueError(f"{self.hook_event} cannot HARD-enforce; use SOFT")
        return self


class Lesson(BaseModel):
    """One correction/learning captured as auditable data; compiles to policies."""

    id: str = Field(description="stable slug, e.g. 'run-tests-before-success'")
    created: date
    origin: Origin
    source_session: str
    artifact_type: ArtifactType = ArtifactType.RULE
    status: Status = Status.PENDING
    scope: Scope = Scope.GLOBAL
    scope_value: str | None = None  # repo root (REPO) or language marker; mirrors Policy (item C)
    durability: Durability = Durability.PERSISTENT
    determinism: Determinism = Determinism.DETERMINISTIC

    trigger: str
    what_was_wrong: str
    what_to_do_instead: str = Field(description="the prefer-Y target, not just avoid-X")
    origin_quote: str = Field(default="", description="the user's exact words, if any")

    # Proactive review (item 3): set when this lesson was just drafted from a correction
    # and should be SURFACED to the user immediately (via the Stop/SessionStart hook's
    # additionalContext: "I drafted a rule from your correction — keep it?"). It NEVER
    # changes enforcement (that stays gated on status=ACTIVE); it only flags that the user
    # has not yet been asked. Cleared once kept/vetoed.
    needs_review: bool = False

    # Governance (item 6): when this rule SUPERSEDES an older one, the older lesson's id.
    # The superseded lesson is moved to ARCHIVED with a back-pointer; nothing is hard-deleted.
    supersedes: str | None = None
    superseded_by: str | None = None  # set on the OLD (archived) lesson -> the replacement id

    signals: GroundedSignals = Field(default_factory=GroundedSignals)
    policies: list[Policy] = Field(default_factory=list)

    @property
    def confidence(self) -> float:
        return self.signals.score()


# ---------------------------------------------------------------------------
# DETECT extraction wrapper (Jason Liu's "Maybe" pattern + leading reasoning)
# ---------------------------------------------------------------------------
class Note(BaseModel):
    """A KNOWLEDGE artifact: a freeform note you recall later ('what do I know about
    X'). Markdown is the source of truth; the FTS index is derived and rebuildable."""

    id: str
    created: date
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    source: str = ""


class ExtractedKnowledge(BaseModel):
    """A durable fact/entity worth FILING as a knowledge file (slice 2 capture). The
    capture step turns this into a `type: knowledge` vault file, auto-routed to a folder."""

    title: str = Field(description="the entity/topic this is about, Title Case (the filename)")
    body: str = Field(description="the durable knowledge, in a few clear sentences")
    tags: list[str] = Field(default_factory=list, description="0-3 lowercase topical tags")
    sources: list[str] = Field(
        default_factory=list,
        description="any URLs/citations the user gave; empty if none (NEVER invent one)",
    )


class MaybeKnowledge(BaseModel):
    """Forced output schema for CAPTURE: `chain_of_thought` FIRST (generated before the
    verdict), then an explicit abstain path. Bias HARD toward abstaining — a junk knowledge
    file is worse than a missed one, and capture auto-writes (PENDING) without asking."""

    chain_of_thought: str = Field(description="brief reasoning about whether durable knowledge is present")
    is_knowledge: bool
    knowledge: ExtractedKnowledge | None = None
    abstain_reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "MaybeKnowledge":
        if self.is_knowledge and self.knowledge is None:
            raise ValueError("is_knowledge=True requires a `knowledge`")
        if not self.is_knowledge and self.knowledge is not None:
            raise ValueError("is_knowledge=False must not carry a `knowledge`")
        return self


class ExtractedLesson(BaseModel):
    """What the classifier emits for a single salient correction. The COMPILE
    step turns this into a Lesson + Policies (assigning id/status/signals)."""

    trigger: str
    what_was_wrong: str
    what_to_do_instead: str
    origin_quote: str
    scope: Scope
    durability: Durability
    determinism: Determinism
    proposed_artifact_type: ArtifactType


class MaybeLesson(BaseModel):
    """The forced output schema for DETECT. `chain_of_thought` is FIRST so it is
    generated before the verdict (Pydantic field order == generation order).
    An explicit abstain path is the single most important precision control."""

    chain_of_thought: str = Field(description="brief reasoning about whether this turn contains a real correction")
    is_lesson: bool
    lesson: ExtractedLesson | None = None
    abstain_reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "MaybeLesson":
        if self.is_lesson and self.lesson is None:
            raise ValueError("is_lesson=True requires a `lesson`")
        if not self.is_lesson and self.lesson is not None:
            raise ValueError("is_lesson=False must not carry a `lesson`")
        return self


# ---------------------------------------------------------------------------
# Cedar-style decision resolution: deny > ask > rewrite > allow, default-deny on HARD
# ---------------------------------------------------------------------------
_PRECEDENCE = {Decision.DENY: 3, Decision.ASK: 2, Decision.REWRITE: 1, Decision.ALLOW: 0}


def resolve_decisions(decisions: list[Decision]) -> Decision:
    """Order-independent precedence. No matching HARD policy -> ALLOW (the call
    proceeds); among matches, the most restrictive wins."""
    if not decisions:
        return Decision.ALLOW
    return max(decisions, key=lambda d: _PRECEDENCE[d])
