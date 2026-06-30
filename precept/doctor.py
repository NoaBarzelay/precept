"""`precept doctor` health checks (item 2): does the install actually WORK?

The failure this guards against: `install` registered a hook command that Claude Code's
own PATH can't resolve (a venv not on PATH), so the hook silently never runs and the user
believes Precept is enforcing when it isn't. We check, for each console-script hook:

  1. settings.json has an entry for the event pointing at a `precept-hook-*` command;
  2. that command is REACHABLE (an absolute path that exists + is executable, or a bare
     name resolvable on PATH).

Pure stdlib + read-only. Returns structured results so the CLI renders them and `--strict`
can gate CI; this module never mutates settings (that's `install`'s job).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import install, paths

# The events Precept registers and the console script each should point at. Mirrors
# install._ENTRIES (kept here independently so doctor is a true external check).
EXPECTED: dict[str, str] = {
    "PreToolUse": "precept-hook-pretooluse",
    "Stop": "precept-hook-stop",
    "UserPromptSubmit": "precept-hook-userpromptsubmit",
    "SessionStart": "precept-hook-sessionstart",
    "SessionEnd": "precept-hook-sessionend",
}


@dataclass
class HookCheck:
    event: str
    expected_script: str
    command: str | None  # the command string found in settings.json (None = missing entry)
    reachable: bool
    detail: str

    @property
    def ok(self) -> bool:
        return self.command is not None and self.reachable


def _command_reachable(command: str) -> tuple[bool, str]:
    """Is this hook command actually invocable? An absolute path must exist + be exec;
    a bare name must resolve on PATH (which is what Claude Code does)."""
    if not command:
        return False, "empty command"
    if os.path.isabs(command):
        p = Path(command)
        if not p.exists():
            return False, f"absolute path does not exist: {command}"
        if not os.access(p, os.X_OK):
            return False, f"not executable: {command}"
        return True, str(p)
    found = shutil.which(command)
    if found:
        return True, f"on PATH -> {found}"
    return False, f"bare name not on PATH: {command}"


def _settings_commands(settings: dict, event: str) -> list[str]:
    cmds: list[str] = []
    for entry in settings.get("hooks", {}).get(event, []) or []:
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []) or []:
            if isinstance(h, dict) and install._is_precept_command(h.get("command", "")):
                cmds.append(str(h.get("command", "")))
    return cmds


def check_hooks(settings: dict | None = None) -> list[HookCheck]:
    """Run the per-event reachability + wiring checks. `settings` is injectable for tests;
    production reads the live settings.json."""
    if settings is None:
        try:
            settings = json.loads(install.settings_path().read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                settings = {}
        except (OSError, ValueError):
            settings = {}
    results: list[HookCheck] = []
    for event, script in EXPECTED.items():
        cmds = _settings_commands(settings, event)
        if not cmds:
            results.append(HookCheck(event, script, None, False, "no Precept hook registered"))
            continue
        # Prefer the command whose basename matches the expected script for this event.
        command = next(
            (c for c in cmds if os.path.basename(c) == script), cmds[0]
        )
        reachable, detail = _command_reachable(command)
        if os.path.basename(command) != script:
            reachable = False
            detail = f"points at {os.path.basename(command)}, expected {script}"
        results.append(HookCheck(event, script, command, reachable, detail))
    return results


def all_ok(checks: list[HookCheck]) -> bool:
    return all(c.ok for c in checks)


def state_dir_is_synced() -> bool:
    """The iCloud-safety invariant: SQLite on a cloud-synced path can corrupt."""
    return any(tok in str(paths.state_dir()) for tok in ("Mobile Documents", "iCloud", "Dropbox"))
