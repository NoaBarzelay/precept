"""Bootstrap tests — importing existing setup, all offline."""

import json

from precept import bootstrap, enforce
from precept.bootstrap import lesson_from_permission, parse_permission_rule
from precept.models import ArtifactType, Decision, Origin, Status


def test_parse_permission_rule():
    assert parse_permission_rule("Bash(rm -rf *)") == ("Bash", "rm -rf *")
    assert parse_permission_rule("Read(.env)") == ("Read", ".env")
    assert parse_permission_rule("WebSearch") == ("WebSearch", None)


def test_permission_rule_compiles_to_enforcing_policy():
    le = lesson_from_permission("Bash(rm -rf *)", Decision.DENY)
    assert le is not None and le.status == Status.PENDING and le.origin == Origin.BOOTSTRAP
    assert len(le.policies) == 1
    # the imported rule actually matches a dangerous command
    pol = le.policies[0].model_dump(mode="json", exclude_none=True)
    assert enforce._matches(pol["match"], "Bash", {"command": "rm -rf /tmp/data"}) is True
    assert enforce._matches(pol["match"], "Bash", {"command": "ls"}) is False


def test_unknown_tool_is_skipped():
    assert lesson_from_permission("Frobnicate(x)", Decision.DENY) is None


def test_claude_md_import_skips_junk():
    from precept.bootstrap import import_claude_md

    text = (
        "# Heading (skip)\n"
        "- Always run the tests before committing\n"
        "1. Read the profile at the start of every session\n"
        "- [Title](https://example.com) accessed 2026-05-28\n"  # citation -> skip
        "```\n- this is inside a code fence, skip\n```\n"
        "| a | b |\n"  # table -> skip
        "- ok\n"  # too short -> skip
    )
    lessons = import_claude_md(text)
    triggers = [le.trigger for le in lessons]
    assert "Always run the tests before committing" in triggers
    assert "Read the profile at the start of every session" in triggers
    assert len(lessons) == 2  # the citation, code-fence, table, and short lines are all skipped


def test_bootstrap_imports_permissions_and_claude_md(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_HOME", str(tmp_path / "home"))
    ch = tmp_path / "claude"
    ch.mkdir()
    (ch / "settings.json").write_text(json.dumps({
        "permissions": {"deny": ["Bash(rm -rf *)", "Read(.env)"], "ask": ["Bash(git push *)"]}
    }))
    (ch / "CLAUDE.md").write_text("# Rules\n- Always run the tests before committing\n- Prefer pnpm over npm\n")

    minted = bootstrap.bootstrap(claude_home=ch)
    assert all(le.status == Status.PENDING and le.origin == Origin.BOOTSTRAP for le in minted)
    hard = [le for le in minted if le.policies]
    soft = [le for le in minted if not le.policies]
    assert len(hard) == 3  # 2 deny + 1 ask, all compiled to policies
    assert all(le.artifact_type == ArtifactType.CLAUDE_MD for le in soft)
    assert len(soft) == 2  # 2 CLAUDE.md bullets
