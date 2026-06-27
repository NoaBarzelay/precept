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
            import anthropic

            client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=JUDGE_MODEL,
            max_tokens=512,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"RULE: {judgment_prompt}\n\nAGENT FINAL STATE:\n{context}"}],
            output_format=Verdict,
        )
        return resp.parsed_output
    except Exception:
        return None  # fail open
