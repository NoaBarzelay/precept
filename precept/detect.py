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

import json
import os
import re
import time
from datetime import date as _date
from typing import Any, Protocol

from . import catalog, paths
from .adapters import claude_code as cc
from .models import (
    Determinism, ExtractedLesson, GroundedSignals, Lesson, MaybeLesson, Origin, Scope,
    Status,
)
from .safety import atomic_write_text

CLASSIFIER_MODEL = "claude-haiku-4-5"  # cheap, schema-constrained extraction
_MAX_TURNS = 8  # only look at the tail of the conversation
_LOCK_STALE_SECS = 120  # reclaim a DETECT lock left behind by a crashed process

# Recall-biased PRE-FILTER (item 1): cheap regex cues that a user turn *might* be a
# correction. This is a COST GATE ONLY — it decides WHETHER to spend an LLM call, never
# what the correction is. The semantic classification stays the LLM (see #4). Biased to
# recall: it's fine to over-fire (a needless cheap LLM call); a miss would drop a real
# correction, so the cues are broad. Word-boundary anchored to avoid matching inside words
# ("another" must not trip "no", "notation" must not trip "no").
_PREFILTER = re.compile(
    r"\b(no|nope|don'?t|never|not|stop|actually|instead|wrong|"
    r"should(?:'?ve| have)?|again|undo|revert|isn'?t|aren'?t|"
    r"use\s+\w+\s+not\s+\w+)\b",
    re.IGNORECASE,
)


def looks_like_correction(turns: list[str]) -> bool:
    """The pre-filter gate: is a correction plausible in ANY of these new user turns?
    Recall-biased (over-fires by design); a True only earns an LLM classification call."""
    return any(_PREFILTER.search(t or "") for t in turns)

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
- scope: default "global" (applies everywhere). Set "repo" ONLY when the correction is \
explicitly about this project/repo ("in this repo", "for this project"); "language" only \
when it's explicitly language-specific ("for all node projects"). When in doubt, global.
- A correction about what the USER'S OWN PROMPT should always contain ("always include \
the ticket id", "always say which env") is a prompt-time rule; still extract it as a \
lesson — COMPILE will target it at the prompt surface.
Reason briefly in chain_of_thought first, then fill the fields."""


class _ParseClient(Protocol):  # the slice of the Anthropic client we use (for testing)
    class messages:  # noqa: N801
        @staticmethod
        def parse(**kwargs: Any) -> Any: ...


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:6]) or "lesson"


def _git_root(cwd: str | None) -> str | None:
    """Walk up from cwd to the nearest dir containing a `.git`; the repo root for a
    repo-scoped lesson (item C). Stdlib os.path only. None if cwd is empty/not in a repo."""
    if not cwd:
        return None
    try:
        cur = os.path.realpath(cwd)
    except OSError:
        return None
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


# ---------------------------------------------------------------------------
# Per-session cursor (item 1): the count of transcript entries already classified,
# so each Stop processes only the NEW tail. Stored as small JSON in the state dir.
# ---------------------------------------------------------------------------
def read_cursor(session_id: str) -> int:
    try:
        data = json.loads(paths.detect_cursor(session_id).read_text(encoding="utf-8"))
        off = data.get("offset", 0) if isinstance(data, dict) else 0
        return off if isinstance(off, int) and off >= 0 else 0
    except (OSError, ValueError):
        return 0  # no cursor yet / unreadable -> start from the beginning


def write_cursor(session_id: str, offset: int) -> None:
    paths.ensure_dirs()
    atomic_write_text(
        paths.detect_cursor(session_id),
        json.dumps({"offset": max(0, int(offset))}) + "\n",
    )


# ---------------------------------------------------------------------------
# Per-session lock (item 1): a single os.mkdir (atomic on every platform) is the
# token, so two Stop events firing close together never double-classify the same
# turns. Idempotent detection; stale locks (crashed holder) are reclaimed by age.
# ---------------------------------------------------------------------------
class _DetectLock:
    """A best-effort, fail-OPEN per-session lock. `acquired` is False when another
    live holder owns it (the caller then skips classifying this turn). On ANY error
    we acquire (fail open: a rare double-classify is dedup'd downstream; never wedge)."""

    def __init__(self, session_id: str):
        self._path = paths.detect_lock(session_id)
        self.acquired = False

    def __enter__(self) -> "_DetectLock":
        paths.ensure_dirs()
        try:
            os.mkdir(self._path)
            self.acquired = True
        except FileExistsError:
            try:  # reclaim a stale lock left by a crashed holder
                if time.time() - os.path.getmtime(self._path) > _LOCK_STALE_SECS:
                    self.acquired = True  # adopt it; we'll remove on exit
            except OSError:
                self.acquired = True  # can't stat -> fail open (proceed)
        except OSError:
            self.acquired = True  # mkdir failed for another reason -> fail open
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.acquired:
            try:
                os.rmdir(self._path)
            except OSError:
                pass


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


def lesson_from_extraction(
    ex: ExtractedLesson, *, session: str, cwd: str | None = None, today: _date | None = None
) -> Lesson:
    quote = ex.origin_quote.strip()
    imperative = bool(re.search(r"\b(never|always|don'?t|stop|must|use)\b", quote, re.I))
    # A repo-scoped lesson needs the repo root resolved from the session's cwd so the
    # enforce-time cwd filter (item C) has a root to test against. If we can't resolve a
    # root, fall back to GLOBAL (a global rule is safe; a repo rule with no root can't fire).
    scope, scope_value = ex.scope, None
    if scope == Scope.REPO:
        root = _git_root(cwd)
        if root:
            scope_value = root
        else:
            scope = Scope.GLOBAL
    return Lesson(
        id=_slugify(ex.what_to_do_instead or ex.trigger),
        created=today or _date.today(),
        origin=Origin.CORRECTION,
        source_session=session,
        status=Status.PENDING,
        needs_review=True,  # item 3: surface it proactively until the user keeps/vetoes
        scope=scope,
        scope_value=scope_value,
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
    transcript_path: str, *, session: str = "", cwd: str | None = None,
    session_id: str | None = None, client: _ParseClient | None = None,
) -> list[Lesson]:
    """Read a transcript, classify the NEW turns, and write any minted lesson as a
    PENDING card. Returns the minted lessons (empty if abstained or nothing new).

    Incremental (item 1): a per-session cursor records how many transcript entries were
    already classified, so each Stop only looks at the tail; a recall-biased regex
    PRE-FILTER gates the (cheap) LLM call so an irrelevant turn costs nothing; a per-session
    LOCK makes detection idempotent under near-simultaneous Stop events.

    `session_id` keys the cursor + lock (defaults to `session`, then the transcript path).
    `cwd` (the session's working dir) lets a repo-scoped lesson resolve its repo root."""
    sess = session or transcript_path
    sid = session_id or session or transcript_path
    with _DetectLock(sid) as lock:
        if not lock.acquired:
            return []  # another Stop is already classifying this session's new turns
        entries = cc.read_transcript(transcript_path)
        start = read_cursor(sid)
        if start > len(entries):  # transcript was truncated/rotated -> reclassify from 0
            start = 0
        new_entries = entries[start:]
        # Advance the cursor to the full length regardless of outcome: these entries are
        # now "seen". Done up front so an abstain/dedup early-return still advances it.
        write_cursor(sid, len(entries))

        new_turns = _user_turns(new_entries)
        # PRE-FILTER cost gate: only spend an LLM call when a correction is plausible in
        # the NEW user turns. (No new user turns at all -> nothing to classify.)
        if not new_turns or not looks_like_correction(new_turns):
            return []
        context = _build_context(new_entries)
        if not context:
            return []
        maybe = classify(context, client)
        if not maybe.is_lesson or maybe.lesson is None:
            return []
        lesson = lesson_from_extraction(maybe.lesson, session=sess, cwd=cwd)
        # cheap dedup: don't re-mint an id that already exists (LLM consolidation is later)
        if catalog.card_path(lesson.id).exists():
            return []
        catalog.write(lesson)
        return [lesson]
