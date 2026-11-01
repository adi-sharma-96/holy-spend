"""Small, allowlisted authentication event envelope."""

import json
import logging
import re
import sys
from contextlib import suppress
from uuid import uuid4

_logger = logging.getLogger("holy_spend.auth")
_HANDLER_NAME = "holy_spend_auth_events"
_SAFE_ID = re.compile(r"^[0-9a-fA-F]{32}$")
COMPONENTS = frozenset({"api", "database", "oauth", "gateway", "cli", "smoke"})
ENVIRONMENTS = frozenset({"local", "test", "ci", "development", "staging", "production"})
EVENTS = frozenset({"pat_auth", "pat_verification", "pat_issuance", "oauth_redemption", "mcp_upstream", "smoke_stage"})
OUTCOMES = frozenset({"accepted", "rejected", "denied", "unavailable", "incompatible", "failed", "succeeded"})
REASONS = frozenset(
    {
        "none",
        "missing_credential",
        "credential_unknown",
        "database_error",
        "code_invalid",
        "upstream_error",
        "verify_pat",
        "create_pat",
        "mcp_exchange",
        "oauth_exchange",
        "cleanup",
    }
)


def configure_auth_logging() -> None:
    """Install one stderr JSON handler, even under Uvicorn's default config."""
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    for previous in tuple(_logger.handlers):
        if previous.get_name() == _HANDLER_NAME:
            _logger.removeHandler(previous)
            previous.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)


def correlation_id(value: str | None = None) -> str:
    return value if value is not None and _SAFE_ID.fullmatch(value) else uuid4().hex


def emit_auth_event(
    event: str,
    outcome: str,
    component: str,
    environment: str,
    duration_ms: int,
    correlation: str | None = None,
    reason: str = "none",
) -> None:
    """Never accept arbitrary exception text, URL, token or request data."""
    if event not in EVENTS or outcome not in OUTCOMES:
        return
    safe_component = component if component in COMPONENTS else "unknown"
    safe_environment = environment if environment in ENVIRONMENTS else "unknown"
    record = {
        "event": event,
        "outcome": outcome,
        "component": safe_component,
        "environment": safe_environment,
        "duration_ms": max(0, min(duration_ms, 600_000)),
        "correlation_id": correlation_id(correlation),
        "reason": reason if reason in REASONS else "unknown",
    }
    with suppress(Exception):
        _logger.info(json.dumps(record, separators=(",", ":")))
