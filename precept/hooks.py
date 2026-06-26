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
        cc.emit(enforce.evaluate_stop(cc.read_event()))
    except Exception:
        pass  # fail open
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pretooluse_main())
