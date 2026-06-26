"""`precept install` / `uninstall` — register Precept's hooks in Claude Code's
settings.json, idempotently and safely.

Safety: we never edit in place. We parse -> transform a copy -> write atomically
(temp -> fsync -> os.replace), keeping a `.bak` of the prior file. Our entries are
identified by their `command` (all start with `precept-hook-`), so we add NO custom
keys Claude Code might reject, and uninstall is an exact inverse.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from . import paths
from .safety import atomic_write_text

_PREFIX = "precept-hook-"

# (event, matcher, command). matcher=None => applies to the whole event.
# PreToolUse uses "*" (guard every tool); per-tool narrowing happens in the policy
# matcher, not the hook matcher, so one hook covers everything.
_ENTRIES = [
    ("PreToolUse", "*", "precept-hook-pretooluse"),
    ("Stop", None, "precept-hook-stop"),
    ("SessionEnd", None, "precept-hook-sessionend"),
]


def _is_precept_entry(entry: dict) -> bool:
    return isinstance(entry, dict) and any(
        isinstance(h, dict) and str(h.get("command", "")).startswith(_PREFIX)
        for h in entry.get("hooks", [])
    )


def strip_precept(settings: dict) -> dict:
    """Return a copy with all Precept hook entries removed (empty events pruned)."""
    out = copy.deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks.keys()):
        kept = [e for e in hooks.get(event, []) if not _is_precept_entry(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        out.pop("hooks", None)
    return out


def apply_install(settings: dict) -> dict:
    """Idempotent: strip any prior Precept entries, then add fresh ones."""
    out = strip_precept(settings)
    hooks = out.setdefault("hooks", {})
    for event, matcher, command in _ENTRIES:
        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        hooks.setdefault(event, []).append(entry)
    return out


def settings_path() -> Path:
    return paths.claude_home() / "settings.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_with_backup(path: Path, settings: dict) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    atomic_write_text(path, json.dumps(settings, indent=2) + "\n")


def install_to_file() -> Path:
    p = settings_path()
    _write_with_backup(p, apply_install(_load(p)))
    return p


def uninstall_from_file() -> Path:
    p = settings_path()
    _write_with_backup(p, strip_precept(_load(p)))
    return p
