"""Inference health — make the LLM flows' auth/reachability VISIBLE instead of silent.

The five flows (DETECT, COMPILE, the 3 JUDGE verdicts) call the Anthropic SDK and are
each wrapped fail-closed (DETECT abstains) or fail-open (JUDGE returns None) so a model
hiccup never wedges a session. That same wrapper also hides a TOTAL failure: on a
machine with no usable API credentials, every call raises "Could not resolve
authentication method" and the whole self-improving loop goes inert with zero signal.

This module is the thin honesty layer:
  - note_failure(flow, exc): best-effort record of the LAST error per flow (type, message,
    ts, whether it's an auth/config error) to a local health file. Fail-OPEN — recording a
    failure must never add a failure.
  - last_failures(): what `precept doctor` reads to report inference health.
  - probe(): actively test reachability with a minimal call. FREE when creds are missing
    (the SDK raises a client-side TypeError before any network call), ~1 token when they
    resolve — so `doctor` can probe without meaningful spend.

NOTE (2026-06-30): Precept runs on a Claude Code SUBSCRIPTION, which exposes NO
credential to a subprocess (the host holds the OAuth token in memory / keychain and
refreshes it there; the on-disk token is expired and not subprocess-refreshable, and
`claude -p` returns "Not logged in" headless). So today the flows only run when an
ANTHROPIC_API_KEY (or auth_token) is present in the environment. This module surfaces
that state; it does not by itself solve subscription inference.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

from . import paths

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


# ---------------------------------------------------------------------------
# Backend selection: SUBSCRIPTION (via the Claude Code CLI) vs API key (raw SDK).
# ---------------------------------------------------------------------------
# Precept's flows call `client.messages.parse(model, system, messages, output_format)`.
# Two backends satisfy that shape:
#   - "api" -> the raw Anthropic SDK (needs ANTHROPIC_API_KEY / auth_token). Cheapest per
#             call, but DOES NOT work on a bare Claude Code subscription.
#   - "cli" -> shell out to `claude -p ... --json-schema ... --output-format json`, which
#             authenticates on the SUBSCRIPTION (host OAuth, or CLAUDE_CODE_OAUTH_TOKEN from
#             `claude setup-token`) and returns native structured output + usage.
# Selected by PRECEPT_INFERENCE (default "api" — preserves behavior for API-key users).
# The CLI path loads NO user settings (`--setting-sources project`) so Precept's own hooks
# never fire recursively; it also tags the subprocess with a sentinel env var (below) that
# the hook entrypoints check as belt-and-suspenders.

CLI_SUBPROCESS_ENV = "PRECEPT_INFERENCE_SUBPROCESS"  # hook entrypoints no-op when this is set
_CLI_TIMEOUT_S = 120


def mode() -> str:
    """'cli' (subscription via the Claude Code CLI) or 'api' (raw SDK + key). Default 'api'."""
    return (os.environ.get("PRECEPT_INFERENCE") or "api").strip().lower()


class _Usage:
    """A `.usage`-shaped view over the CLI envelope's usage block, so meter.record works
    unchanged across both backends."""

    def __init__(self, u: dict[str, Any]):
        self.input_tokens = int(u.get("input_tokens", 0) or 0)
        self.output_tokens = int(u.get("output_tokens", 0) or 0)
        self.cache_read_input_tokens = int(u.get("cache_read_input_tokens", 0) or 0)
        self.cache_creation_input_tokens = int(u.get("cache_creation_input_tokens", 0) or 0)


class _Parsed:
    """A `.parsed_output` / `.usage` response mirroring the SDK's parse() return."""

    def __init__(self, parsed_output: Any, usage: _Usage):
        self.parsed_output = parsed_output
        self.usage = usage


def _user_text(messages: list[dict[str, Any]]) -> str:
    """Flatten messages into the single prompt `claude -p` takes. Precept sends user turns
    with string content; be defensive about content blocks all the same."""
    parts: list[str] = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.extend(
                b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
            )
    return "\n\n".join(p for p in parts if p)


class _CliMessages:
    """The `.messages` namespace of the CLI client — one `parse` matching the SDK's shape."""

    @staticmethod
    def parse(*, model: str, messages: list[dict[str, Any]], output_format: Any,
              system: str | None = None, max_tokens: int | None = None,
              **_ignored: Any) -> _Parsed:
        exe = shutil.which("claude")
        if exe is None:
            raise RuntimeError("claude CLI not found on PATH (needed for PRECEPT_INFERENCE=cli)")
        cmd = [
            exe, "-p", _user_text(messages),
            "--model", model,
            "--system-prompt", system or "You output structured data per the provided schema.",
            "--json-schema", json.dumps(output_format.model_json_schema()),
            "--output-format", "json",
            "--setting-sources", "project",  # do NOT load user settings -> no recursive hooks
        ]
        env = {**os.environ, CLI_SUBPROCESS_ENV: "1"}  # belt-and-suspenders vs recursion
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT_S, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {(proc.stderr or '')[:300]}")
        try:
            env_obj = json.loads(proc.stdout)
        except ValueError as exc:
            raise RuntimeError(f"claude CLI returned non-JSON: {(proc.stdout or '')[:200]}") from exc
        if env_obj.get("is_error"):
            raise RuntimeError(f"claude CLI error: {str(env_obj.get('result'))[:200]}")
        structured = env_obj.get("structured_output")
        if structured is None:
            raise RuntimeError("claude CLI returned no structured_output (schema not honored)")
        parsed = output_format.model_validate(structured)
        return _Parsed(parsed, _Usage(env_obj.get("usage", {})))


class _CliClient:
    """A minimal client exposing `.messages.parse(...)` over the Claude Code CLI, so the
    flow modules use it exactly like the Anthropic SDK client."""

    messages = _CliMessages()


def make_client() -> Any:
    """The inference client for the active backend: the CLI shim (subscription) when
    PRECEPT_INFERENCE=cli, else the raw Anthropic SDK (API key)."""
    if mode() == "cli":
        return _CliClient()
    import anthropic

    return anthropic.Anthropic()


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

    Probes the ACTIVE backend (make_client): the CLI/subscription when PRECEPT_INFERENCE=cli,
    else the raw SDK. Cost: on the SDK path with no creds, the error is client-side (zero
    tokens); a working call spends ~1 token (CLI path amortizes to a cache read). So `doctor`
    can call this safely. An injected client (tests) skips the real call entirely."""
    try:
        if client is None:
            client = make_client()
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
