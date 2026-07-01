"""INFERENCE — pluggable backend for the model calls the AI seams make.

Precept's AI call sites (DETECT classify, JUDGE verdicts, CAPTURE classify, COMPILE
synthesize) all share one tiny contract: a client object whose
`.messages.parse(model=, max_tokens=, system=, messages=, output_format=)` returns
something with a `.parsed_output` that is a validated instance of the pydantic
`output_format` class. The Anthropic SDK's `messages.parse` already does exactly this.

This module lets those seams run through the local `claude` CLI in headless mode —
which authenticates with the user's Claude subscription — INSTEAD of requiring an
`ANTHROPIC_API_KEY`. `ClaudeCLIClient` re-implements the same `.messages.parse`
contract on top of `claude -p --output-format json`, so every call site is unchanged
beyond swapping the default client constructor.

Backend selection (`get_client`):
  - PRECEPT_INFERENCE=sdk -> the real Anthropic SDK (needs ANTHROPIC_API_KEY).
  - PRECEPT_INFERENCE=cli -> the claude CLI (subscription auth).
  - unset / "auto"      -> CLI when `claude` is on PATH AND no ANTHROPIC_API_KEY is set
                           (the subscription path is the no-key default); else the SDK.

On ANY failure the CLI client RAISES — the call sites are each wrapped in try/except
and fail open or closed, so they handle the error; this module never swallows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

from . import paths

# The model ids precept passes (CLASSIFIER_MODEL / JUDGE_MODEL / SYNTH_MODEL etc.) are
# the bare aliases the claude CLI's --model flag accepts directly (e.g. claude-haiku-4-5).
_CLI_TIMEOUT_SECS = 120


class _ParsedResponse:
    """Mimics the SDK's parsed response: exposes `.parsed_output` (a validated
    instance of the caller's pydantic `output_format` class)."""

    def __init__(self, parsed_output: Any) -> None:
        self.parsed_output = parsed_output


def _extract_json_object(text: str) -> str:
    """Pull the outermost {...} JSON object out of the assistant text, tolerating
    ```json fences and surrounding prose. Brace-matches so nested objects survive."""
    if text is None:
        raise ValueError("no assistant text to parse")
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in assistant text")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unterminated JSON object in assistant text")


class _CLIMessages:
    """The `.messages` namespace of `ClaudeCLIClient` — exposes `.parse`."""

    def parse(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        output_format: Any,
        max_tokens: int = 1024,
        system: str | None = None,
        **_ignored: Any,
    ) -> _ParsedResponse:
        """Run one schema-constrained completion through `claude -p`. Builds a single
        prompt (system + user content + a JSON-only instruction embedding the schema),
        invokes the CLI headless, extracts the assistant text from the JSON envelope,
        pulls the JSON object out of it, and validates it against `output_format`.

        Raises on any failure (bad CLI exit, malformed envelope, unparseable/invalid
        JSON) — the call sites' try/except handle fail-open/closed."""
        schema = json.dumps(output_format.model_json_schema())
        prompt = _build_prompt(system, messages, schema)

        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--model", model],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=_CLI_TIMEOUT_SECS,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or '').strip()[:500]}"
            )

        envelope = json.loads(proc.stdout)
        if not isinstance(envelope, dict):
            raise ValueError("claude CLI envelope was not a JSON object")
        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI reported an error: {envelope.get('result')!r}")
        assistant_text = envelope.get("result")
        if not isinstance(assistant_text, str):
            raise ValueError("claude CLI envelope had no string `result` field")

        json_blob = _extract_json_object(assistant_text)
        parsed = output_format.model_validate_json(json_blob)
        return _ParsedResponse(parsed)


def _content_to_text(content: Any) -> str:
    """Flatten a message `content` (str, or list of text blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type", "text") == "text"
        )
    return str(content)


def _build_prompt(system: str | None, messages: list[dict[str, Any]], schema: str) -> str:
    """One prompt string: optional system, then the concatenated user content, then a
    trailing instruction to emit ONLY a JSON object conforming to the embedded schema."""
    parts: list[str] = []
    if system:
        parts.append(system)
    user_text = "\n\n".join(_content_to_text(m.get("content")) for m in messages)
    if user_text:
        parts.append(user_text)
    parts.append(
        "Respond with ONLY a single JSON object conforming to this JSON Schema. "
        "No prose, no explanation, no markdown code fences — just the raw JSON object:\n"
        + schema
    )
    return "\n\n".join(parts)


class ClaudeCLIClient:
    """A drop-in for `anthropic.Anthropic()` covering the one method precept uses:
    `.messages.parse(...)`. Routes the call through the local `claude` CLI in headless
    mode, which authenticates via the user's Claude subscription (no API key)."""

    def __init__(self) -> None:
        self.messages = _CLIMessages()


def get_client() -> Any:
    """Select the inference backend (see module docstring).

    Returns an object exposing `.messages.parse(...)` with the SDK contract — either a
    real `anthropic.Anthropic()` or a `ClaudeCLIClient`."""
    mode = os.environ.get("PRECEPT_INFERENCE", "auto").strip().lower()
    if mode == "sdk":
        return _sdk_client()
    if mode == "cli":
        return ClaudeCLIClient()
    # auto / unset: prefer the subscription CLI when it's available and no key is set.
    if shutil.which("claude") and not os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeCLIClient()
    return _sdk_client()


def _sdk_client() -> Any:
    import anthropic

    return anthropic.Anthropic()


# ---------------------------------------------------------------------------
# Inference health — de-silence the LLM flows' auth/reachability (option C).
#
# The five flows (DETECT, COMPILE, the 3 JUDGE verdicts) are each wrapped fail-closed
# (DETECT abstains) or fail-open (JUDGE returns None) so a model hiccup never wedges a
# session. That same wrapper also HIDES a total failure: on a machine with no usable
# credentials every call raises "Could not resolve authentication method" and the whole
# self-improving loop goes inert with zero signal. These helpers are the honesty layer —
# `note_failure` records the last error per flow, `last_failures`/`probe` are what
# `precept doctor` reads to surface inference health. All best-effort and FAIL-OPEN.
# ---------------------------------------------------------------------------

# Substrings that mark a PERSISTENT auth/config problem (worth flagging loudly) vs a
# transient model/network error (a blip). Matched against the exception text, lowercased.
_AUTH_MARKERS = (
    "could not resolve authentication",
    "authentication",
    "x-api-key",
    "api_key",
    "auth_token",
    "401",
    "unauthorized",
    "not logged in",
)


def is_auth_error(exc: BaseException) -> bool:
    """True if `exc` looks like a credentials/config problem (persistent) rather than a
    transient model or network error. Used to classify the failure for the operator."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(m in text for m in _AUTH_MARKERS)


def note_failure(flow: str, exc: BaseException) -> None:
    """Record the last inference failure for `flow`. Best-effort, FAIL-OPEN — any error
    here is swallowed; recording a failure must never create one. Local/derived state."""
    try:
        path = paths.inference_health()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[flow] = {
            "ts": time.time(),
            "error_type": type(exc).__name__,
            "message": str(exc)[:300],
            "auth_error": is_auth_error(exc),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        return  # fail-open


def last_failures() -> dict[str, Any]:
    """The recorded per-flow last-failure map (empty if none / unreadable)."""
    try:
        data = json.loads(paths.inference_health().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def probe(client: Any | None = None) -> tuple[bool, str]:
    """Actively test that inference is reachable. Returns (ok, detail).

    Probes the ACTIVE backend (get_client): the CLI/subscription default when `claude` is
    on PATH and no key is set, else the raw SDK. Cost: on the SDK path with no creds, the
    error is client-side (zero tokens); a working call spends ~1 token. So `doctor` can
    call this safely. An injected client (tests) skips backend selection."""
    try:
        if client is None:
            client = get_client()
        from pydantic import BaseModel

        class _Ping(BaseModel):
            ok: bool

        resp = client.messages.parse(
            model="claude-haiku-4-5",
            max_tokens=8,
            messages=[{"role": "user", "content": "reply ok=true"}],
            output_format=_Ping,
        )
        # Record usage if the meter is wired (a successful probe is a real call).
        try:
            from . import meter

            meter.record("probe", "claude-haiku-4-5", resp)
        except Exception:
            pass
        return True, "reachable"
    except Exception as exc:  # noqa: BLE001 — report any failure as the detail
        kind = "auth/config" if is_auth_error(exc) else "transient"
        return False, f"{kind}: {type(exc).__name__}: {str(exc)[:160]}"
