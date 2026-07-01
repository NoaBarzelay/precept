"""Matcher-synthesis tests — the COMPILE step — with a faked model, no network."""

from datetime import date

from precept import synthesize
from precept.models import (
    ArtifactType, CheckKind, Condition, Decision, Determinism, EnforcementTier, HookEvent,
    Lesson, Match, MatchOp, Origin,
)
from precept.synthesize import PolicyDraft, validate_match


class _FakeMessages:
    def __init__(self, parsed=None, raises=False):
        self._parsed, self._raises = parsed, raises

    def parse(self, **kwargs):
        if self._raises:
            raise RuntimeError("down")
        return type("R", (), {"parsed_output": self._parsed})()


class FakeClient:
    def __init__(self, parsed=None, raises=False):
        self.messages = _FakeMessages(parsed, raises)


def _lesson(determinism=Determinism.DETERMINISTIC) -> Lesson:
    return Lesson(
        id="use-pnpm", created=date(2026, 6, 26), origin=Origin.CORRECTION, source_session="s",
        determinism=determinism, trigger="install deps", what_was_wrong="ran npm",
        what_to_do_instead="use pnpm", origin_quote="never npm",
    )


def _ok_draft() -> PolicyDraft:
    return PolicyDraft(
        reasoning="banned command", can_compile=True,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.DENY, message="Use pnpm.",
        match=Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.REGEX, value=r"\bnpm install")]),
    )


def test_synthesizes_hard_policy():
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ok_draft()))
    assert p is not None
    assert p.enforcement_tier == EnforcementTier.HARD
    assert p.match.tool == "Bash"
    assert p.lesson_id == "use-pnpm"


def test_compile_lesson_attaches_policy():
    le = synthesize.compile_lesson(_lesson(), client=FakeClient(_ok_draft()))
    assert len(le.policies) == 1
    assert le.signals.deterministic_by_construction is True


def test_validator_gate_rejects_unknown_tool_and_field():
    assert validate_match(Match(tool="Frobnicate")) is False
    assert validate_match(Match(tool="Bash", conditions=[Condition(field="nope", op=MatchOp.EQUALS, value="x")])) is False
    assert validate_match(Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.EQUALS, value="x")])) is True


def test_cannot_compile_returns_none_and_downgrades_to_soft():
    draft = PolicyDraft(reasoning="stylistic", can_compile=False)
    le = synthesize.compile_lesson(_lesson(), client=FakeClient(draft))
    assert le.policies == []
    assert le.determinism == Determinism.STYLISTIC  # honest downgrade


def test_output_style_judgment_never_compiles_to_hard_gate():
    """A voice / output-style directive labeled 'judgment' must NOT become a HARD Stop gate:
    there is no objective, satisfiable condition for 'use this voice', so a gate would nag
    every turn forever. It stays honestly soft. (Regression for the always-explain loop.)"""
    le = _lesson(Determinism.JUDGMENT)
    le.artifact_type = ArtifactType.OUTPUT_STYLE
    out = synthesize.compile_lesson(le, client=FakeClient(raises=True))  # must not need the model
    assert out.policies == []
    assert out.determinism == Determinism.STYLISTIC
    assert out.signals.deterministic_by_construction is False


def test_knowledge_and_skill_judgment_also_stay_soft():
    for at in (ArtifactType.KNOWLEDGE, ArtifactType.SKILL):
        le = _lesson(Determinism.JUDGMENT)
        le.artifact_type = at
        out = synthesize.compile_lesson(le, client=FakeClient(raises=True))
        assert out.policies == [], at
        assert out.determinism == Determinism.STYLISTIC, at


def test_rule_judgment_still_compiles_to_hard_stop_gate():
    """Regression guard the other way: a gate-able judgment (default RULE artifact, e.g.
    'no stub code') still gets its HARD Stop verdict gate."""
    le = _lesson(Determinism.JUDGMENT)  # artifact_type defaults to RULE
    out = synthesize.compile_lesson(le)  # judgment gate needs no model
    assert len(out.policies) == 1
    assert out.policies[0].hook_event == HookEvent.STOP
    assert out.policies[0].check_kind == CheckKind.JUDGMENT
    assert out.policies[0].enforcement_tier == EnforcementTier.HARD


def test_stylistic_lesson_never_calls_model():
    # raises=True would blow up if the client were used; stylistic short-circuits first
    le = synthesize.compile_lesson(_lesson(Determinism.STYLISTIC), client=FakeClient(raises=True))
    assert le.policies == []


# --- REWRITE-by-default for clean substitutions (item A) --------------------
def _rewrite_draft(rewrite_to=None) -> PolicyDraft:
    return PolicyDraft(
        reasoning="clean substitution", can_compile=True,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=Decision.REWRITE, message="Use pnpm.",
        rewrite_to=rewrite_to,
        match=Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.EQUALS, value="npm install")]),
    )


def test_substitution_draft_compiles_to_rewrite():
    p = synthesize.synthesize_policy(
        _lesson(), client=FakeClient(_rewrite_draft({"command": "pnpm install"}))
    )
    assert p is not None
    assert p.decision == Decision.REWRITE
    assert p.rewrite_to == {"command": "pnpm install"}


def test_rewrite_draft_without_rewrite_to_is_rejected():
    # The model validator requires rewrite_to for REWRITE -> fail closed (no policy).
    assert synthesize.synthesize_policy(_lesson(), client=FakeClient(_rewrite_draft(None))) is None


# --- Shape classifier: hook vs native permission rule (item B) --------------
def _ban_draft(match, decision=Decision.DENY) -> PolicyDraft:
    return PolicyDraft(
        reasoning="ban", can_compile=True,
        hook_event=HookEvent.PRE_TOOL_USE, check_kind=CheckKind.SINGLE_CALL,
        decision=decision, message="blocked", match=match,
    )


def test_clean_path_ban_classified_as_permission_rule():
    m = Match(tool="Read", conditions=[Condition(field="file_path", op=MatchOp.GLOB, value=".env")])
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ban_draft(m)))
    assert p is not None and p.permission_rule == "Read(.env)"


def test_bash_arg_ban_stays_hook():
    # CC ignores Bash arg-patterns -> must stay a hook (permission_rule is None).
    m = Match(tool="Bash", conditions=[Condition(field="command", op=MatchOp.REGEX, value=r"\brm -rf")])
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ban_draft(m)))
    assert p is not None and p.permission_rule is None


def test_webfetch_domain_ban_to_permission_rule():
    m = Match(tool="WebFetch", conditions=[Condition(field="url", op=MatchOp.EQUALS, value="evil.com")])
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ban_draft(m)))
    assert p is not None and p.permission_rule == "WebFetch(domain:evil.com)"


def test_whole_tool_ban_to_bare_permission_rule():
    p = synthesize.synthesize_policy(
        _lesson(), client=FakeClient(_ban_draft(Match(tool="WebFetch", conditions=[])))
    )
    assert p is not None and p.permission_rule == "WebFetch"


def test_regex_path_ban_does_not_convert():
    # A regex path op can't be safely translated to a gitignore spec -> stay a hook.
    m = Match(tool="Read", conditions=[Condition(field="file_path", op=MatchOp.REGEX, value=r"\.env")])
    p = synthesize.synthesize_policy(_lesson(), client=FakeClient(_ban_draft(m)))
    assert p is not None and p.permission_rule is None


def test_permission_rule_excluded_from_hook_cache():
    from precept import compile as compile_mod
    from precept.models import Status

    m = Match(tool="Read", conditions=[Condition(field="file_path", op=MatchOp.GLOB, value=".env")])
    le = synthesize.compile_lesson(_lesson(), client=FakeClient(_ban_draft(m)))
    le.status = Status.ACTIVE
    assert compile_mod._runtime_policies(le) == []  # not in the hook interpreter's cache
    rules = compile_mod._permission_rules(le)
    assert rules["deny"] == ["Read(.env)"]
