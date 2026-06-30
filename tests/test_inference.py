"""INFERENCE tests — the subscription-CLI backend and backend selection.

The real `claude` CLI is faked by monkeypatching `subprocess.run` (so these run with
no network and no subscription). One real end-to-end smoke test is included but skips
itself when `claude` is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from pydantic import BaseModel

from precept import inference


class Sample(BaseModel):
    answer: str
    count: int


def _envelope(result: str, *, is_error: bool = False, returncode: int = 0):
    """Build a fake `subprocess.run` that returns a claude -p JSON envelope."""

    def _fake_run(cmd, input=None, text=None, capture_output=None, timeout=None):
        stdout = json.dumps(
            {"type": "result", "subtype": "success", "is_error": is_error, "result": result}
        )
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return _fake_run


def _parse(monkeypatch, fake_run) -> Sample:
    monkeypatch.setattr(subprocess, "run", fake_run)
    client = inference.ClaudeCLIClient()
    resp = client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=256,
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        output_format=Sample,
    )
    return resp.parsed_output


# --- ClaudeCLIClient.messages.parse: happy paths -------------------------------
def test_parse_plain_json(monkeypatch):
    out = _parse(monkeypatch, _envelope('{"answer": "hello", "count": 3}'))
    assert isinstance(out, Sample)
    assert out.answer == "hello" and out.count == 3


def test_parse_fenced_json(monkeypatch):
    fenced = '```json\n{\n  "answer": "hi",\n  "count": 7\n}\n```'
    out = _parse(monkeypatch, _envelope(fenced))
    assert out.answer == "hi" and out.count == 7


def test_parse_prose_wrapped_json(monkeypatch):
    prose = 'Sure! Here is the result: {"answer": "x", "count": 1} — hope that helps.'
    out = _parse(monkeypatch, _envelope(prose))
    assert out.answer == "x" and out.count == 1


def test_parse_nested_braces(monkeypatch):
    # The brace-matcher must not stop at the first nested closing brace.
    text = '{"answer": "a {nested} value", "count": 2}'
    out = _parse(monkeypatch, _envelope(text))
    assert out.answer == "a {nested} value" and out.count == 2


# --- ClaudeCLIClient.messages.parse: failure paths must RAISE -------------------
def test_parse_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _envelope("ignored", returncode=2))
    with pytest.raises(RuntimeError):
        inference.ClaudeCLIClient().messages.parse(
            model="m", messages=[{"role": "user", "content": "x"}], output_format=Sample
        )


def test_parse_raises_on_error_envelope(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _envelope("boom", is_error=True))
    with pytest.raises(RuntimeError):
        inference.ClaudeCLIClient().messages.parse(
            model="m", messages=[{"role": "user", "content": "x"}], output_format=Sample
        )


def test_parse_raises_on_no_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _envelope("there is no object here"))
    with pytest.raises(ValueError):
        inference.ClaudeCLIClient().messages.parse(
            model="m", messages=[{"role": "user", "content": "x"}], output_format=Sample
        )


def test_parse_raises_on_schema_violation(monkeypatch):
    # Valid JSON, but missing a required field -> pydantic validation raises.
    monkeypatch.setattr(subprocess, "run", _envelope('{"answer": "x"}'))
    with pytest.raises(Exception):
        inference.ClaudeCLIClient().messages.parse(
            model="m", messages=[{"role": "user", "content": "x"}], output_format=Sample
        )


def test_parse_raises_on_malformed_envelope(monkeypatch):
    def _bad(cmd, input=None, text=None, capture_output=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json at all", stderr="")

    monkeypatch.setattr(subprocess, "run", _bad)
    with pytest.raises(Exception):
        inference.ClaudeCLIClient().messages.parse(
            model="m", messages=[{"role": "user", "content": "x"}], output_format=Sample
        )


# --- The prompt actually carries system + content + schema ----------------------
def test_prompt_includes_system_content_and_schema(monkeypatch):
    captured = {}

    def _capture(cmd, input=None, text=None, capture_output=None, timeout=None):
        captured["cmd"] = cmd
        captured["input"] = input
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"is_error": False, "result": '{"answer":"a","count":1}'}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _capture)
    inference.ClaudeCLIClient().messages.parse(
        model="claude-haiku-4-5",
        system="SYSTEM-MARKER",
        messages=[{"role": "user", "content": "USER-MARKER"}],
        output_format=Sample,
    )
    assert "--model" in captured["cmd"] and "claude-haiku-4-5" in captured["cmd"]
    assert "-p" in captured["cmd"] and "json" in captured["cmd"]
    assert "SYSTEM-MARKER" in captured["input"]
    assert "USER-MARKER" in captured["input"]
    assert '"count"' in captured["input"]  # the embedded schema


# --- get_client backend selection ----------------------------------------------
def test_get_client_cli_when_claude_present_no_key(monkeypatch):
    monkeypatch.delenv("PRECEPT_INFERENCE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/claude")
    assert isinstance(inference.get_client(), inference.ClaudeCLIClient)


def test_get_client_sdk_when_api_key_set(monkeypatch):
    monkeypatch.delenv("PRECEPT_INFERENCE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/claude")
    sentinel = object()
    monkeypatch.setattr(inference, "_sdk_client", lambda: sentinel)
    assert inference.get_client() is sentinel


def test_get_client_sdk_when_claude_absent(monkeypatch):
    monkeypatch.delenv("PRECEPT_INFERENCE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    sentinel = object()
    monkeypatch.setattr(inference, "_sdk_client", lambda: sentinel)
    assert inference.get_client() is sentinel


def test_get_client_explicit_cli(monkeypatch):
    monkeypatch.setenv("PRECEPT_INFERENCE", "cli")
    # Even with an API key set, explicit cli wins.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(inference.get_client(), inference.ClaudeCLIClient)


def test_get_client_explicit_sdk(monkeypatch):
    monkeypatch.setenv("PRECEPT_INFERENCE", "sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/local/bin/claude")
    sentinel = object()
    monkeypatch.setattr(inference, "_sdk_client", lambda: sentinel)
    assert inference.get_client() is sentinel


# --- Real end-to-end subscription smoke (skipped if claude is unavailable) ------
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_real_cli_end_to_end():
    """Proves the subscription path actually works: a tiny schema round-trips through
    the real `claude -p` and validates. Skipped when the CLI isn't present."""

    class Tiny(BaseModel):
        word: str

    client = inference.ClaudeCLIClient()
    resp = client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=256,
        system="You output only JSON.",
        messages=[{"role": "user", "content": "The word is PONG."}],
        output_format=Tiny,
    )
    assert isinstance(resp.parsed_output, Tiny)
    assert resp.parsed_output.word
