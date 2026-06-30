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
