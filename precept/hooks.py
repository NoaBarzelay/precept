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
    try:
        cc.emit(enforce.evaluate_pretooluse(cc.read_event()))
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
    """SessionStart entrypoint (item 3): inject any still-unreviewed drafted rules at the
    top of a new session, so corrections from a prior session aren't silently forgotten."""
    try:
        cc.read_event()  # consume stdin per the contract (payload currently unused)
        cc.emit(_review_injection(cc.sessionstart_context))
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
    from . import review

    ctx = review.review_context()
    return wrap(ctx) if ctx else {}


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
