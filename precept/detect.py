"""DETECT — extract a Lesson from a real correction in a session transcript.

NOT YET IMPLEMENTED (next build step). The locked design:
  - Trigger: Stop / SessionEnd hook, run async + fire-and-forget + timeout-bounded.
  - Read transcript JSONL; PROVENANCE GATE — only consider genuine user-typed turns.
  - Two-phase: cheap cursor-mark on Stop, batched classify on SessionEnd (Batch API).
  - Extraction via `client.messages.parse(model="claude-haiku-4-5", output_format=MaybeLesson)`
    (structured outputs; leading chain_of_thought field; abstain via is_lesson=False).
  - Validate-and-retry: Pydantic validators enforce invariants (a deny policy must
    carry a blockable hook_event; prefer-Y phrasing required).
  - FAIL CLOSED: on any error, mint nothing.
  - At most 1-2 salient corrections per session.
  - Prompt-cache the static system prompt + schema prefix (runs every Stop).

COMPILE then turns each ExtractedLesson into a Lesson (id/status/signals) + Policies,
running LLM-assisted dedup/consolidation against existing cards before COMMIT.
"""

from __future__ import annotations

from .models import MaybeLesson


def detect_from_transcript(transcript_path: str) -> list[MaybeLesson]:  # pragma: no cover
    raise NotImplementedError("DETECT lands in the next build step; see module docstring.")
