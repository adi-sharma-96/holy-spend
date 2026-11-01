import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.pat_verification import VerifyCode
from scripts import manage_pat

USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TOKEN_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeResult:
    def __init__(self, row: dict[str, Any] | None = None, rowcount: int = 1) -> None:
        self.row = row
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class FakeAdminConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        if "from profiles" in sql:
            return FakeResult({"id": USER_ID})
        if "insert into personal_access_tokens" in sql:
            return FakeResult({"id": TOKEN_ID})
        return FakeResult(rowcount=1)

    def commit(self) -> None:
        self.commits += 1


class FakeConnectionContext:
    def __init__(self, conn: FakeAdminConn) -> None:
        self.conn = conn

    def __enter__(self) -> FakeAdminConn:
        return self.conn

    def __exit__(self, *_args: object) -> None:
        return None


def test_pat_creation_stores_only_hash_and_approved_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeAdminConn()
    monkeypatch.setattr(manage_pat, "generate_pat", lambda: "det_raw-secret")
    monkeypatch.setattr(manage_pat, "hash_pat", lambda token: f"hash-of-{token[:3]}")

    created = manage_pat.create_pat(
        conn,
        USER_ID,
        "Private GPT",
        ["taxonomy:read", "analytics:read"],
        30,
    )
    insert_params = next(params for sql, params in conn.calls if "insert into personal_access_tokens" in sql)

    assert created.raw_token == "det_raw-secret"
    assert created.token_id == TOKEN_ID
    assert insert_params["token_hash"] == "hash-of-det"
    assert insert_params["scopes"] == ["taxonomy:read", "analytics:read"]
    assert "det_raw-secret" not in repr(insert_params)
    assert isinstance(created.expires_at, datetime)
    assert created.expires_at is not None and created.expires_at.tzinfo == UTC


def test_pat_scope_allowlist_rejects_admin_scope() -> None:
    with pytest.raises(ValueError, match="Unsupported PAT scopes"):
        manage_pat.validate_scopes(["taxonomy:read", "admin:write"])


def test_revoke_pat_marks_only_selected_users_token() -> None:
    conn = FakeAdminConn()

    assert manage_pat.revoke_pat(conn, USER_ID, TOKEN_ID) is True
    sql, params = conn.calls[0]
    assert "revoked_at = coalesce(revoked_at, now())" in sql
    assert "user_id = %(user_id)s" in sql
    assert params == {"token_id": TOKEN_ID, "user_id": USER_ID}


def test_cli_prints_raw_pat_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    conn = FakeAdminConn()
    monkeypatch.setenv("PAT_ADMIN_DATABASE_URL", "postgresql://admin.example/test")
    monkeypatch.setattr(
        "scripts.manage_pat.psycopg.connect",
        lambda *_args, **_kwargs: FakeConnectionContext(conn),
    )
    monkeypatch.setattr(manage_pat, "generate_pat", lambda: "det_only-once")
    monkeypatch.setattr(manage_pat, "hash_pat", lambda _token: "hashed")

    exit_code = manage_pat.main(
        [
            "create",
            "--user-id",
            str(USER_ID),
            "--name",
            "Private GPT",
            "--scope",
            "taxonomy:read",
            "--skip-verification",
            "--verify-url",
            "http://127.0.0.1:8765",
            "--allow-loopback-http",
            "--allow-development-pepper",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == VerifyCode.CREATED_UNVERIFIED
    assert output.count("det_only-once") == 1
    assert conn.commits == 1


def test_remote_target_rejects_default_pepper_before_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PAT_ADMIN_DATABASE_URL", "postgresql://sentinel-db-secret@localhost/test")
    monkeypatch.setattr(manage_pat, "get_settings", lambda: Settings(pat_pepper=SecretStr("dev-only-change-me")))
    monkeypatch.setattr("scripts.manage_pat.psycopg.connect", lambda *_a, **_k: pytest.fail("database touched"))
    result = manage_pat.main(
        [
            "create",
            "--user-id",
            str(USER_ID),
            "--name",
            "remote",
            "--verify-url",
            "https://api.example.test",
        ]
    )
    output = capsys.readouterr()
    assert result == VerifyCode.CONFIGURATION_ERROR
    assert "sentinel-db-secret" not in output.out + output.err


def test_skip_with_default_pepper_needs_explicit_loopback_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manage_pat, "get_settings", lambda: Settings(pat_pepper=SecretStr("dev-only-change-me")))
    monkeypatch.setattr("scripts.manage_pat.psycopg.connect", lambda *_a, **_k: pytest.fail("database touched"))
    result = manage_pat.main(["create", "--user-id", str(USER_ID), "--name", "offline", "--skip-verification"])
    assert result == VerifyCode.CONFIGURATION_ERROR


def test_cli_emits_safe_failure_event_without_logging_override(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PAT_ADMIN_DATABASE_URL", "postgresql://sentinel-db-secret@localhost/test")
    monkeypatch.setattr(manage_pat, "get_settings", lambda: Settings(pat_pepper=SecretStr("safe-local-pepper")))
    monkeypatch.setattr(
        "scripts.manage_pat.psycopg.connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sentinel-exception-secret")),
    )
    result = manage_pat.main(
        [
            "create",
            "--user-id",
            str(USER_ID),
            "--name",
            "offline",
            "--skip-verification",
        ]
    )
    output = capsys.readouterr()
    assert result == VerifyCode.CONFIGURATION_ERROR
    assert "sentinel-db-secret" not in output.err
    assert "sentinel-exception-secret" not in output.err
    event = json.loads(output.err.splitlines()[0])
    assert (event["event"], event["outcome"], event["reason"]) == (
        "pat_issuance",
        "failed",
        "database_error",
    )
