import json
import subprocess
import sys

import pytest

from app.auth_events import configure_auth_logging, correlation_id, emit_auth_event


def test_event_contract_and_redaction(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "sentinel-pat-secret"
    configure_auth_logging()
    emit_auth_event("pat_auth", "rejected", secret, secret, -1, secret)
    output = capsys.readouterr().err
    record = json.loads(output.strip())
    assert record["event"] == "pat_auth"
    assert record["outcome"] == "rejected"
    assert record["component"] == "unknown"
    assert record["environment"] == "unknown"
    assert record["duration_ms"] == 0
    assert secret not in output


def test_uvicorn_default_logging_emits_after_gateway_startup() -> None:
    code = (
        "import logging.config, os; from uvicorn.config import LOGGING_CONFIG; "
        "os.environ['MCP_GATEWAY_UPSTREAM_URL']='http://127.0.0.1:8766/mcp'; "
        "os.environ['AUTH_MODE']='pat'; "
        "logging.config.dictConfig(LOGGING_CONFIG); "
        "from app.main import create_app; create_app(); "
        "from app.auth_events import emit_auth_event; "
        "emit_auth_event('pat_auth','rejected','api','local',1,reason='credential_unknown')"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    record = json.loads(completed.stderr.strip().splitlines()[-1])
    assert record["event"] == "pat_auth"
    assert record["reason"] == "credential_unknown"


def test_correlation_validation() -> None:
    assert correlation_id("a" * 32) == "a" * 32
    assert correlation_id("evil\nheader") != "evil\nheader"
    assert len(correlation_id("x" * 1000)) == 32
