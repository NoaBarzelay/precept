"""Console-script entrypoints Claude Code invokes. Thin, fast, and FAIL-OPEN:
any unexpected error emits nothing and exits 0, so Precept can never wedge the
user's session because of its own bug. (A missing/empty policy cache simply
enforces nothing.)
"""

from __future__ import annotations

import sys

from .adapters import claude_code as cc
from . import enforce


def pretooluse_main() -> int:
    event = cc.read_event()
    # Telemetry (item B-1): append one event-log line. Its own try so a logging hiccup can
    # never affect enforcement, and vice versa — both fail open.
    try:
        from . import telemetry

        telemetry.log_event(event)
    except Exception:
        pass  # fail open
    try:
        cc.emit(enforce.evaluate_pretooluse(event))  # also applies context rules (item A)
    except Exception:
        pass  # fail open
    return 0


def stop_main() -> int:
    try:
        event = cc.read_event()
        out = enforce.evaluate_stop(event)
        # If we're not blocking, proactively surface any freshly drafted rules awaiting
        # review (item 3) via additionalContext, so the user is asked in-flow.
        if not out:
            out = _review_injection(cc.stop_context)
        cc.emit(out)
        _spawn_detect(event)  # also kick DETECT off the Stop event, detached
    except Exception:
        pass  # fail open
    return 0


def sessionstart_main() -> int:
    """SessionStart entrypoint. Injects, as one additionalContext block:
      - item 3: any still-unreviewed drafted RULES (so prior-session corrections aren't lost);
      - slice 2: a bounded RETRIEVAL of relevant vault KNOWLEDGE for the session's opening
        context (derived from the last user turn in the transcript, when available).
    Both are FAIL-OPEN; nothing to surface -> emit nothing."""
    try:
        event = cc.read_event()
        parts = [
            p for p in (
                _review_injection_text(),
                _sessionstart_retrieval(event),
                _sessionstart_audit(),
                _sessionstart_health(),
            ) if p
        ]
        if parts:
            cc.emit(cc.sessionstart_context("\n\n".join(parts)))
    except Exception:
        pass  # fail open
    return 0


def userpromptsubmit_main() -> int:
    try:
        cc.emit(enforce.evaluate_userpromptsubmit(cc.read_event()))
    except Exception:
        pass  # fail open
    return 0


def detect_main() -> int:
    """SessionEnd entrypoint: kick DETECT off, detached, and return immediately."""
    try:
        _spawn_detect(cc.read_event())
    except Exception:
        pass
    return 0


def _review_injection(wrap) -> dict:
    """Build the proactive-review additionalContext payload (item 3), or {} when there is
    nothing to surface. `wrap` is the surface-specific adapter (stop_context /
    sessionstart_context). Lazy import keeps the no-pending fast path cheap."""
    ctx = _review_injection_text()
    return wrap(ctx) if ctx else {}


def _review_injection_text() -> str | None:
    """The proactive-review additionalContext STRING (item 3), or None. Lazy import keeps
    the no-pending fast path cheap."""
    from . import review

    return review.review_context()


def _sessionstart_retrieval(event: dict) -> str | None:
    """Slice 2 retrieval at SessionStart: derive a query from the last user turn in the
    session transcript (if any) and surface bounded, relevant vault knowledge. FAIL-OPEN
    (no transcript / no vault / any error -> None)."""
    try:
        from . import detect
        from .knowledge import retrieval

        tp = event.get("transcript_path")
        if not tp:
            return None
        turns = detect._user_turns(cc.read_transcript(tp))
        if not turns:
            return None
        return retrieval.retrieval_context(turns[-1])
    except Exception:
        return None


def _sessionstart_audit() -> str | None:
    """Slice 2 daily integrity audit at SessionStart, THROTTLED to once per calendar day.
    Surfaces a bounded summary of PENDING proposals (rename / placement / missing-frontmatter
    / missing-sources / unfiled-knowledge) — propose, never auto-apply. FAIL-OPEN: no vault /
    already-ran-today / any error -> None."""
    try:
        from .knowledge import config as kconfig
        from .knowledge import ops as kops

        if not kops.should_run_today():
            return None
        try:
            vault = kconfig.resolve_vault()
        except ValueError:
            return None
        props = kops.run_daily(vault)  # stamps today; returns the proposals
        if not props:
            return None
        lines = [
            f"Precept's daily knowledge audit found {len(props)} item(s) to review "
            "(proposals only — nothing was changed):",
        ]
        for p in props[:8]:
            lines.append(f"  - [{p.kind}] {p.path}: {p.detail}")
        if len(props) > 8:
            lines.append(f"  …and {len(props) - 8} more (`precept audit --force`).")
        return "\n".join(lines)
    except Exception:
        return None


def _sessionstart_health() -> str | None:
    """System-health reminder (item B-3) at SessionStart, THROTTLED to once per calendar day.
    Returns a staleness reminder for the CONFIGURED watched files, or None (nothing watched /
    all fresh / already ran today / any error). FAIL-OPEN."""
    try:
        from . import health

        return health.health_reminder()
    except Exception:
        return None


def _spawn_detect(event: dict) -> None:
    """Fire-and-forget: run DETECT (an LLM call) in a detached process so the hook
    never blocks the user's session on classification. Threads the session_id through
    (item 1) so DETECT keys its per-session cursor + lock by the real session."""
    import subprocess
    import sys

    tp = event.get("transcript_path")
    if not tp:
        return
    argv = [sys.executable, "-m", "precept", "detect", tp]
    sid = event.get("session_id")
    if sid:
        argv += ["--session-id", str(sid)]
    cwd = event.get("cwd")
    if cwd:
        argv += ["--cwd", str(cwd)]
    subprocess.Popen(
        argv,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pretooluse_main())
