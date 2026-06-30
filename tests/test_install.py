import os

from precept.install import apply_install, strip_precept


def _commands(settings):
    out = []
    for entries in settings.get("hooks", {}).values():
        for e in entries:
            out += [h.get("command") for h in e.get("hooks", [])]
    return out


def _basenames(settings):
    return [os.path.basename(c) for c in _commands(settings)]


def test_install_adds_all_hooks():
    s = apply_install({})
    # install now writes ABSOLUTE paths (item 2), so compare by basename
    names = _basenames(s)
    assert "precept-hook-pretooluse" in names
    assert "precept-hook-stop" in names
    assert "precept-hook-sessionstart" in names  # item 3 surface
    assert "precept-hook-sessionend" in names
    # PreToolUse entry carries a matcher; Stop/SessionEnd don't
    assert s["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert "matcher" not in s["hooks"]["Stop"][0]


def test_install_is_idempotent():
    once = apply_install({})
    twice = apply_install(once)
    assert _commands(once) == _commands(twice)  # no duplicates


def test_install_preserves_foreign_settings():
    base = {
        "model": "claude-opus-4-8",
        "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "other-tool"}]}]},
    }
    out = apply_install(base)
    assert out["model"] == "claude-opus-4-8"
    assert "other-tool" in _commands(out)  # foreign hook kept
    assert "precept-hook-pretooluse" in _basenames(out)


def test_uninstall_is_exact_inverse():
    base = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "keep-me"}]}]}}
    restored = strip_precept(apply_install(base))
    assert restored == base
