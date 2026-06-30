"""Item 2 — robust hook command paths + `precept doctor`: install writes ABSOLUTE,
reachable paths, the prefix-strip still recognizes them, and doctor flags a broken
or mis-wired hook."""

import os

from precept import doctor, install


def test_install_writes_absolute_reachable_paths():
    s = install.apply_install({})
    cmds = [
        h["command"]
        for entries in s["hooks"].values() for e in entries for h in e["hooks"]
    ]
    assert cmds, "expected hook commands"
    for c in cmds:
        # In this repo's venv every console script resolves to an absolute path; if a
        # script were somehow not installed, resolve_command falls back to the bare name
        # (still non-fatal) — so assert at least the basename is a precept hook.
        assert os.path.basename(c).startswith("precept-hook-")
    # the sessionstart surface (item 3) is now registered too
    assert any(os.path.basename(c) == "precept-hook-sessionstart" for c in cmds)


def test_absolute_paths_are_still_recognized_as_precept_entries():
    # uninstall must strip our entries whether bare OR absolute (basename-keyed).
    installed = install.apply_install({"model": "x"})
    restored = install.strip_precept(installed)
    assert restored == {"model": "x"}  # exact inverse despite absolute commands


def test_doctor_passes_on_a_clean_install():
    settings = install.apply_install({})
    checks = doctor.check_hooks(settings)
    # every expected event present and reachable in this venv
    assert {c.event for c in checks} == set(doctor.EXPECTED)
    assert doctor.all_ok(checks)


def test_doctor_detects_a_broken_path():
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "/nonexistent/bin/precept-hook-stop"}]}
            ]
        }
    }
    checks = doctor.check_hooks(settings)
    stop = next(c for c in checks if c.event == "Stop")
    assert stop.command == "/nonexistent/bin/precept-hook-stop"
    assert not stop.reachable
    assert not doctor.all_ok(checks)
    # a missing event is also a failure
    pre = next(c for c in checks if c.event == "PreToolUse")
    assert pre.command is None and not pre.ok


def test_doctor_detects_a_miswired_command():
    # settings.json points the Stop event at the WRONG precept script.
    settings = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "precept-hook-pretooluse"}]}
            ]
        }
    }
    stop = next(c for c in doctor.check_hooks(settings) if c.event == "Stop")
    assert not stop.ok
    assert "expected precept-hook-stop" in stop.detail
