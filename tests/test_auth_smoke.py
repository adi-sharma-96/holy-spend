import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.pat_verification import VerifyCode, VerifyResult
from scripts import auth_smoke

OWNER = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
CREATED_PAT = UUID("11111111-1111-1111-1111-111111111111")
OAUTH_PAT = UUID("22222222-2222-2222-2222-222222222222")
REFRESH = UUID("33333333-3333-3333-3333-333333333333")


def test_preflight_rejects_remote_http_before_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SMOKE_ADMIN_DATABASE_URL", "postgresql://sentinel-db-secret@localhost/test")
    monkeypatch.setattr("scripts.auth_smoke.psycopg.connect", lambda *_args, **_kwargs: pytest.fail("database touched"))
    result = auth_smoke.run(["--base-url", "http://remote.example", "--user-id", str(OWNER)])
    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output)["stages"]["preflight"] == "CONFIGURATION_ERROR"
    assert "sentinel-db-secret" not in output


def test_existing_token_mode_requires_id_and_never_touches_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("scripts.auth_smoke.psycopg.connect", lambda *_args, **_kwargs: pytest.fail("database touched"))
    result = auth_smoke.run(
        [
            "--base-url",
            "https://example.test",
            "--user-id",
            str(OWNER),
            "--existing-token-stdin",
        ]
    )
    assert result == 2
    assert json.loads(capsys.readouterr().out)["stages"]["preflight"] == "CONFIGURATION_ERROR"


class FakeResult:
    def __init__(
        self, *, row: dict[str, object] | None = None, rows: list[dict[str, object]] | None = None, rowcount: int = 1
    ) -> None:
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, object] | None:
        return self.row

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeAdminConnection:
    def __init__(self, refresh_found: bool) -> None:
        self.refresh_found = refresh_found
        self.revoked: list[UUID] = []
        self.commits = 0

    def execute(self, sql: str, params: Any) -> FakeResult:
        if "insert into personal_access_tokens" in sql:
            return FakeResult(row={"id": CREATED_PAT})
        if "select id from oauth_refresh_tokens" in sql:
            assert params == (OAUTH_PAT, OWNER)
            return FakeResult(rows=[{"id": REFRESH}] if self.refresh_found else [])
        if "update personal_access_tokens" in sql or "update oauth_refresh_tokens" in sql:
            assert params[1] == OWNER
            self.revoked.append(params[0])
            return FakeResult(rowcount=1)
        raise AssertionError("unexpected SQL")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeHttpClient:
    def __init__(self, *, replay_ok: bool, **_kwargs: Any) -> None:
        self.replay_ok = replay_ok
        self.posts = 0

    def __enter__(self) -> "FakeHttpClient":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        if url.endswith("/authorize"):
            return httpx.Response(
                302,
                headers={
                    "location": "https://claude.ai/api/mcp/auth_callback?code=synthetic-code",
                },
            )
        assert not kwargs.get("headers")
        return httpx.Response(401)

    def post(self, _url: str, **_kwargs: Any) -> httpx.Response:
        self.posts += 1
        if self.posts == 1:
            return httpx.Response(400, json={"error": "invalid_grant"})
        if self.posts == 2:
            return httpx.Response(400, json={"error": "invalid_request"})
        if self.posts == 3:
            return httpx.Response(
                200,
                json={
                    "access_token": "server-new-pepper-access",
                    "refresh_token": "server-new-pepper-refresh",
                },
            )
        if self.replay_ok:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(503)


@pytest.mark.parametrize(
    ("refresh_found", "replay_ok", "fail_first_resolution", "expected_exit", "cleanup"),
    [
        (True, True, False, 0, "PASSED"),
        (True, False, False, 1, "PASSED"),
        (True, True, True, 1, "PASSED"),
        (False, True, False, 1, "FAILED"),
    ],
)
def test_rotation_overlap_cleanup_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    refresh_found: bool,
    replay_ok: bool,
    fail_first_resolution: bool,
    expected_exit: int,
    cleanup: str,
) -> None:
    conn = FakeAdminConnection(refresh_found)
    monkeypatch.setenv("SMOKE_ADMIN_DATABASE_URL", "postgresql://synthetic-admin@localhost/test")
    monkeypatch.setenv("SMOKE_OAUTH_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setattr("scripts.auth_smoke.psycopg.connect", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(auth_smoke, "generate_pat", lambda: "det_synthetic-smoke")

    def old_cli_hash(token: str) -> str:
        assert token == "det_synthetic-smoke", "cleanup must not hash server OAuth tokens with the CLI pepper"
        return "old-pepper-hash"

    monkeypatch.setattr(auth_smoke, "hash_pat", old_cli_hash)
    monkeypatch.setattr(
        auth_smoke, "verify_credential", lambda *_a, **_k: VerifyResult(VerifyCode.VERIFIED, "https://api.example.test")
    )
    resolutions = 0

    def resolve_access(*_args: object, **_kwargs: object) -> UUID:
        nonlocal resolutions
        resolutions += 1
        if fail_first_resolution and resolutions == 1:
            raise RuntimeError("temporary identification failure")
        return OAUTH_PAT

    monkeypatch.setattr(auth_smoke, "oauth_access_id", resolve_access)

    async def no_mcp(_base: str, _token: str) -> None:
        return None

    monkeypatch.setattr(auth_smoke, "check_mcp", no_mcp)

    def complete_without_windows_event_loop(coroutine: Any) -> None:
        coroutine.close()

    monkeypatch.setattr("scripts.auth_smoke.asyncio.run", complete_without_windows_event_loop)
    monkeypatch.setattr(
        "scripts.auth_smoke.httpx.Client", lambda **kwargs: FakeHttpClient(replay_ok=replay_ok, **kwargs)
    )
    result = auth_smoke.run(
        [
            "--base-url",
            "https://api.example.test",
            "--user-id",
            str(OWNER),
            "--oauth-client-id",
            "synthetic-client",
            "--oauth-redirect-uri",
            "https://claude.ai/api/mcp/auth_callback",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert result == expected_exit
    assert summary["success"] is (expected_exit == 0)
    assert summary["stages"]["cleanup"] == cleanup
    assert conn.revoked == ([CREATED_PAT, OAUTH_PAT, REFRESH] if refresh_found else [CREATED_PAT, OAUTH_PAT])
    assert "server-new-pepper-refresh" not in json.dumps(summary)


@pytest.mark.parametrize("failure", ["timeout", "malformed_json", "missing_access"])
def test_unaccounted_exchange_never_reports_cleanup_passed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    conn = FakeAdminConnection(True)
    monkeypatch.setenv("SMOKE_ADMIN_DATABASE_URL", "postgresql://synthetic-admin@localhost/test")
    monkeypatch.setenv("SMOKE_OAUTH_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr("scripts.auth_smoke.psycopg.connect", lambda *_a, **_k: conn)
    monkeypatch.setattr(auth_smoke, "hash_pat", lambda _token: "synthetic-hash")
    monkeypatch.setattr(
        auth_smoke, "verify_credential",
        lambda *_a, **_k: VerifyResult(VerifyCode.VERIFIED, "https://api.example.test"),
    )
    monkeypatch.setattr("scripts.auth_smoke.asyncio.run", lambda coroutine: coroutine.close())

    class UncertainExchangeClient(FakeHttpClient):
        def post(self, _url: str, **_kwargs: Any) -> httpx.Response:
            if self.posts == 2:
                self.posts += 1
                # Model issuance having committed before its response is lost/corrupted.
                if failure == "timeout":
                    raise httpx.ReadTimeout("synthetic lost response")
                if failure == "malformed_json":
                    return httpx.Response(200, content=b"{")
                return httpx.Response(200, json={"refresh_token": "synthetic-refresh"})
            return super().post(_url, **_kwargs)

    monkeypatch.setattr(
        "scripts.auth_smoke.httpx.Client", lambda **kwargs: UncertainExchangeClient(replay_ok=True, **kwargs)
    )
    result = auth_smoke.run([
        "--base-url", "https://api.example.test", "--user-id", str(OWNER),
        "--oauth-client-id", "synthetic-client",
        "--oauth-redirect-uri", "https://claude.ai/api/mcp/auth_callback",
    ])
    summary = json.loads(capsys.readouterr().out)
    assert result == 1
    assert summary["success"] is False
    assert summary["stages"]["oauth_code_exchange_replay"] == "FAILED"
    assert summary["stages"]["cleanup"] == "FAILED"
    assert summary["created_ids"] == {"pat_id": str(CREATED_PAT)}
    assert conn.revoked == [CREATED_PAT]
