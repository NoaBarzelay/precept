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

    Cost: when no credentials resolve, the SDK raises a client-side error BEFORE any
    network call (zero tokens); only a working setup spends ~1 token. So `doctor` can call
    this safely. An injected client (tests) skips the real call entirely."""
    try:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
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
