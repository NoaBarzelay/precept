"""Inference-health tests — de-silencing the LLM flows. Zero network: the probe is
exercised with injected fake clients, and note_failure writes to a tmp state dir."""

from __future__ import annotations

from precept import inference


# --- auth-vs-transient classification ---------------------------------------

def test_is_auth_error_flags_credential_problems():
    assert inference.is_auth_error(TypeError("Could not resolve authentication method"))
    assert inference.is_auth_error(Exception("401 Unauthorized"))
    assert inference.is_auth_error(Exception("Not logged in · Please run /login"))


def test_is_auth_error_lets_transient_through():
    assert not inference.is_auth_error(Exception("Connection reset by peer"))
    assert not inference.is_auth_error(Exception("overloaded_error"))


# --- note_failure / last_failures round-trip --------------------------------

def test_note_failure_records_per_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    inference.note_failure("detect", TypeError("Could not resolve authentication method"))
    inference.note_failure("judge.verdict", Exception("Connection reset"))
    fails = inference.last_failures()
    assert fails["detect"]["auth_error"] is True
    assert fails["detect"]["error_type"] == "TypeError"
    assert fails["judge.verdict"]["auth_error"] is False


def test_note_failure_is_fail_open_on_unwritable(monkeypatch):
    # Point the health file at an impossible path; note_failure must swallow, not raise.
    monkeypatch.setattr(inference.paths, "inference_health",
                        lambda: __import__("pathlib").Path("/proc/nonexistent/x.json"))
    inference.note_failure("detect", Exception("boom"))  # must not raise


# --- probe (injected clients, no network) -----------------------------------

class _OkUsage:
    input_tokens = 5
    output_tokens = 1
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _OkResp:
    usage = _OkUsage()
    class parsed_output:  # noqa: N801
        ok = True


class _OkClient:
    class messages:  # noqa: N801
        @staticmethod
        def parse(**kwargs):
            return _OkResp()


class _DeadClient:
    class messages:  # noqa: N801
        @staticmethod
        def parse(**kwargs):
            raise TypeError("Could not resolve authentication method")


def test_probe_reports_reachable(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEPT_STATE_DIR", str(tmp_path / "state"))
    ok, detail = inference.probe(client=_OkClient())
    assert ok is True and detail == "reachable"


def test_probe_reports_auth_failure_without_network():
    ok, detail = inference.probe(client=_DeadClient())
    assert ok is False and "auth/config" in detail


# --- backend selection ------------------------------------------------------

def test_mode_defaults_to_api(monkeypatch):
    monkeypatch.delenv("PRECEPT_INFERENCE", raising=False)
    assert inference.mode() == "api"


def test_make_client_returns_cli_shim_when_configured(monkeypatch):
    monkeypatch.setenv("PRECEPT_INFERENCE", "cli")
    assert isinstance(inference.make_client(), inference._CliClient)


def test_make_client_returns_sdk_by_default(monkeypatch):
    monkeypatch.setenv("PRECEPT_INFERENCE", "api")
    assert not isinstance(inference.make_client(), inference._CliClient)


# --- CLI adapter (mocked subprocess; no real claude call) -------------------

from pydantic import BaseModel  # noqa: E402


class _Out(BaseModel):
    ok: bool
    reason: str = ""


class _Completed:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _mock_cli(monkeypatch, returncode=0, envelope=None, stdout=None):
    monkeypatch.setattr(inference.shutil, "which", lambda _: "/usr/bin/claude")
    out = stdout if stdout is not None else __import__("json").dumps(envelope or {})
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env", {})
        return _Completed(returncode, out)

    monkeypatch.setattr(inference.subprocess, "run", fake_run)
    return captured


def test_cli_parse_maps_structured_output_and_usage(monkeypatch):
    env = {
        "is_error": False,
        "structured_output": {"ok": True, "reason": "use pnpm"},
        "usage": {"input_tokens": 10, "output_tokens": 100,
                  "cache_read_input_tokens": 17000, "cache_creation_input_tokens": 0},
    }
    captured = _mock_cli(monkeypatch, envelope=env)
    resp = inference._CliClient().messages.parse(
        model="claude-haiku-4-5", system="sys",
        messages=[{"role": "user", "content": "use pnpm not npm"}], output_format=_Out)
    assert resp.parsed_output.ok is True and resp.parsed_output.reason == "use pnpm"
    assert resp.usage.input_tokens == 10 and resp.usage.cache_read_input_tokens == 17000
    # the recursion sentinel is set on the subprocess, and user settings are not loaded
    assert captured["env"].get(inference.CLI_SUBPROCESS_ENV) == "1"
    assert "--setting-sources" in captured["cmd"] and "project" in captured["cmd"]
    assert "--json-schema" in captured["cmd"]


def test_cli_parse_raises_on_error_envelope(monkeypatch):
    _mock_cli(monkeypatch, envelope={"is_error": True, "result": "Not logged in"})
    try:
        inference._CliClient().messages.parse(
            model="m", system="s", messages=[{"role": "user", "content": "x"}], output_format=_Out)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "Not logged in" in str(e)


def test_cli_parse_raises_on_nonzero_exit(monkeypatch):
    _mock_cli(monkeypatch, returncode=1, stdout="")
    try:
        inference._CliClient().messages.parse(
            model="m", system="s", messages=[{"role": "user", "content": "x"}], output_format=_Out)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "exited 1" in str(e)


def test_user_text_flattens_messages():
    assert inference._user_text([{"role": "user", "content": "a"},
                                 {"role": "user", "content": [{"type": "text", "text": "b"}]}]) == "a\n\nb"
