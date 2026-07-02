"""The privacy boundary, enforced rather than steered.

Precept separates a public code plane (this repository) from a private data plane
(the user's catalog in ~/.precept, the state dir, the vault). Learned content, the
user's actual rules, style, and knowledge, must never be tracked here. gitignore
states the intent; this test makes it a CI-gated invariant, in line with the
project's own thesis that an invariant should block, not nudge.

Skips cleanly when not running inside a git checkout (e.g. an installed package).
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git unavailable")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in out.stdout.splitlines() if line]


def test_no_populated_catalog_is_tracked():
    # the repo catalog/ may hold only a README and clearly-synthetic examples
    offenders = [
        f for f in _tracked_files()
        if f.startswith("catalog/")
        and Path(f).name != "README.md"
        and not Path(f).name.startswith("example-")
    ]
    assert offenders == [], f"learned catalog content must never be tracked: {offenders}"


def test_no_local_config_or_working_docs_tracked():
    offenders = [
        f for f in _tracked_files()
        if f.startswith(".claude/")
        or Path(f).name.startswith(("HANDOFF", "LAUNCH-CHECKLIST"))
    ]
    assert offenders == [], f"local/session files must never be tracked: {offenders}"


_PERSONAL_MARKERS = re.compile(
    r"/Users/[a-z]+/"          # absolute home paths (machine-specific, may reveal identity)
    r"|\+1-\d{3}-\d{3}-\d{4}"  # US phone numbers
    r"|iCloud~md~obsidian"      # the private vault mount
)

_TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".cfg", ".ini"}


def test_no_personal_markers_in_tracked_text():
    offenders: list[str] = []
    for f in _tracked_files():
        p = REPO / f
        if p.suffix not in _TEXT_SUFFIXES or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _PERSONAL_MARKERS.search(text):
            offenders.append(f)
    assert offenders == [], f"personal markers found in tracked files: {offenders}"
