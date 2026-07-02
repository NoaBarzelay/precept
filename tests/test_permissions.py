"""Marker-managed permissions block (item B): idempotent, preserves user rules,
exact-inverse uninstall, atomic .bak — all isolated to a temp state/home via env."""

import json

import pytest

from precept import install


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "claude"
    home.mkdir()
    state = tmp_path / "state"
    monkeypatch.setenv("PRECEPT_CLAUDE_HOME", str(home))
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(state))
    return home


def _settings():
    return json.loads(install.settings_path().read_text(encoding="utf-8"))


def test_managed_permissions_idempotent(isolated):
    rules = {"deny": ["Read(.env)", "WebFetch(domain:evil.com)"], "ask": []}
    install.write_managed_permissions(rules)
    first = install.settings_path().read_text(encoding="utf-8")
    install.write_managed_permissions(rules)
    assert install.settings_path().read_text(encoding="utf-8") == first  # byte-for-byte


def test_managed_permissions_preserve_user_rules(isolated):
    install.settings_path().write_text(
        json.dumps({"permissions": {"deny": ["Bash(sudo *)"]}}), encoding="utf-8"
    )
    install.write_managed_permissions({"deny": ["Read(.env)"], "ask": []})
    deny = _settings()["permissions"]["deny"]
    assert "Bash(sudo *)" in deny  # the user's own rule survives
    assert "Read(.env)" in deny  # ours added


def test_managed_permissions_uninstall_exact_inverse(isolated):
    base = {"model": "x", "permissions": {"deny": ["Bash(sudo *)"]}}
    install.settings_path().write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    install.write_managed_permissions({"deny": ["Read(.env)"], "ask": []})
    # strip exactly our managed strings -> the user's permissions are restored
    restored = install.strip_managed_permissions(_settings())
    assert restored == base


def test_managed_permissions_writes_bak(isolated):
    install.settings_path().write_text(json.dumps({"permissions": {}}), encoding="utf-8")
    install.write_managed_permissions({"deny": ["Read(.env)"], "ask": []})
    assert install.settings_path().with_name("settings.json.bak").exists()


def test_uninstall_removes_managed_permissions_and_hooks(isolated):
    install.write_managed_permissions({"deny": ["Read(.env)"], "ask": []})
    install.install_to_file()
    install.uninstall_from_file()
    s = _settings()
    # no precept hooks and no managed permission left
    assert "hooks" not in s or all(
        not any(str(h.get("command", "")).startswith("precept-hook-")
                for h in e.get("hooks", []))
        for entries in s.get("hooks", {}).values() for e in entries
    )
    assert "Read(.env)" not in s.get("permissions", {}).get("deny", [])
