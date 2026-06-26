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
        cc.emit(enforce.evaluate_stop(event))
        _spawn_detect(event)  # also kick DETECT off the Stop event, detached
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


def _spawn_detect(event: dict) -> None:
    """Fire-and-forget: run DETECT (an LLM call) in a detached process so the hook
    never blocks the user's session on classification."""
    import subprocess
    import sys

    tp = event.get("transcript_path")
    if not tp:
        return
    subprocess.Popen(
        [sys.executable, "-m", "precept", "detect", tp],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pretooluse_main())
