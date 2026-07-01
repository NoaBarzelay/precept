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
import os
import shutil
import sys
from pathlib import Path

from . import paths
from .safety import atomic_write_text

_PREFIX = "precept-hook-"

# (event, matcher, console-script). matcher=None => applies to the whole event.
# PreToolUse uses "*" (guard every tool); per-tool narrowing happens in the policy
# matcher, not the hook matcher, so one hook covers everything.
_ENTRIES = [
    ("PreToolUse", "*", "precept-hook-pretooluse"),
    ("Stop", None, "precept-hook-stop"),
    ("UserPromptSubmit", None, "precept-hook-userpromptsubmit"),
    ("SessionStart", None, "precept-hook-sessionstart"),
    ("SessionEnd", None, "precept-hook-sessionend"),
]


def resolve_command(script: str) -> str:
    """The ABSOLUTE path Claude Code should invoke for a console script (item 2).

    Claude Code runs hooks with its OWN PATH, which may not include the venv Precept is
    installed in, so a bare `precept-hook-stop` would silently fail to resolve. We write
    the absolute path instead. Resolution order:
      1. a script of that name in the SAME bin dir as the running interpreter (the venv we
         were installed into — the common, reliable case);
      2. anything on PATH (shutil.which);
      3. the bare name as a last resort (no worse than before; keeps install non-fatal)."""
    # NOTE: do NOT resolve() the interpreter symlink — a venv's python is a symlink into
    # the base framework, but the console scripts live next to the SYMLINK in the venv bin.
    bindir = Path(sys.executable).parent
    candidate = bindir / script
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate.resolve()) if candidate.is_symlink() else str(candidate)
    found = shutil.which(script)
    if found:
        return str(Path(found).resolve())
    return script  # fall back to the bare name (install never hard-fails)


def _is_precept_command(command: str) -> bool:
    """True for a Precept hook command whether written as a bare console-script name
    (`precept-hook-stop`) or an absolute path to it (`/venv/bin/precept-hook-stop`, item 2).
    We key on the BASENAME so the prefix-strip stays an exact inverse across both forms."""
    return os.path.basename(str(command)).startswith(_PREFIX)


def _is_precept_entry(entry: dict) -> bool:
    return isinstance(entry, dict) and any(
        isinstance(h, dict) and _is_precept_command(h.get("command", ""))
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
    for event, matcher, script in _ENTRIES:
        # Write the ABSOLUTE path (item 2) so a venv not on Claude Code's PATH still resolves.
        command = resolve_command(script)
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
    settings = strip_managed_permissions(_load(p), _load_manifest())
    _write_with_backup(p, strip_precept(settings))
    _save_manifest({"deny": [], "ask": []})  # we removed all of ours
    from . import convention  # lazy: keep the hot import graph small

    convention.strip_all()  # remove Precept-owned `.claude/rules/*.md` convention files
    return p


# ---------------------------------------------------------------------------
# Marker-managed permissions block (item B)
#
# settings.json permission arrays hold plain Tool(pattern) strings with no room for an
# inline marker, so we track the set of Precept-managed strings in a SIDECAR MANIFEST in
# the local state dir. On each sync we drop ONLY the strings we previously recorded (never
# the user's own), then add the fresh set. This makes the write idempotent, preserves the
# user's rules, and makes uninstall an exact inverse.
# ---------------------------------------------------------------------------
_PERM_BUCKETS = ("deny", "ask")


def _load_manifest() -> dict:
    try:
        data = json.loads(paths.managed_permissions_manifest().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {b: list(data.get(b, []) or []) for b in _PERM_BUCKETS}
    except (OSError, ValueError):
        pass
    return {b: [] for b in _PERM_BUCKETS}


def _save_manifest(managed: dict) -> None:
    paths.ensure_dirs()
    payload = {b: sorted(set(managed.get(b, []) or [])) for b in _PERM_BUCKETS}
    atomic_write_text(
        paths.managed_permissions_manifest(), json.dumps(payload, indent=2) + "\n"
    )


def _sync_permissions(settings: dict, new_managed: dict, old_managed: dict) -> dict:
    """Return a copy of settings whose permission deny/ask arrays drop our PRIOR managed
    strings and add the NEW managed set, leaving every user-authored entry untouched."""
    out = copy.deepcopy(settings)
    perms = out.setdefault("permissions", {})
    if not isinstance(perms, dict):
        perms = out["permissions"] = {}
    for bucket in _PERM_BUCKETS:
        existing = list(perms.get(bucket, []) or [])
        prior = set(old_managed.get(bucket, []) or [])
        kept = [r for r in existing if r not in prior]  # keep the user's, drop only ours
        for rule in sorted(set(new_managed.get(bucket, []) or [])):
            if rule not in kept:  # de-dup; preserve any the user also has
                kept.append(rule)
        if kept:
            perms[bucket] = kept
        else:
            perms.pop(bucket, None)
    if not perms:
        out.pop("permissions", None)
    return out


def strip_managed_permissions(settings: dict, manifest: dict | None = None) -> dict:
    """Remove exactly the Precept-managed permission strings (per the manifest), pruning
    empty arrays and an empty `permissions` key. The exact inverse of a sync."""
    man = manifest if manifest is not None else _load_manifest()
    return _sync_permissions(settings, {b: [] for b in _PERM_BUCKETS}, man)


def write_managed_permissions(perm_rules: dict) -> Path:
    """Sync Precept's managed permission rules into settings.json (idempotent, atomic,
    .bak), then persist the new manifest. `perm_rules` is {"deny": [...], "ask": [...]}."""
    p = settings_path()
    old = _load_manifest()
    new = {b: sorted(set(perm_rules.get(b, []) or [])) for b in _PERM_BUCKETS}
    _write_with_backup(p, _sync_permissions(_load(p), new, old))
    _save_manifest(new)
    return p
