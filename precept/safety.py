"""Shared safety primitives. Precept writes into the user's LIVE config and vault,
so a hook killed mid-write must never leave a torn file or a corrupt database.

Two load-bearing utilities, used by every writer:
  - atomic_write_text: temp-in-same-dir -> flush -> fsync -> os.replace -> fsync dir.
    os.replace is atomic on every platform; a reader sees either the old file or
    the whole new file, never a half-written one.
  - connect_db: the WAL + busy_timeout + synchronous=NORMAL preamble every process
    must run, so concurrent short-lived hooks don't hit "database is locked".
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically (re)write a text file. The temp file is created in the SAME
    directory so the rename stays on one filesystem (cross-fs rename isn't atomic)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic
        # best-effort durability of the rename itself
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass  # O_DIRECTORY unavailable (e.g. Windows) — rename already landed
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the derived SQLite index with the safe concurrency preamble.

    WAL + a busy_timeout + synchronous=NORMAL is the documented recipe for many
    short-lived writers. Callers should use `with conn:` and BEGIN IMMEDIATE for
    writes (grab the write lock up front to avoid upgrade deadlocks)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
