"""Real PostgreSQL OAuth code tests. Requires a disposable migrated database."""

import asyncio
import base64
import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams, TokenError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import AnyUrl, SecretStr

from app import db, oauth_provider
from app.config import Settings, get_settings
from app.main import create_app
from app.pat_verification import VerifyCode, verify_credential
from app.security import hash_pat
from scripts import manage_pat

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
RUNTIME_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not RUNTIME_URL,
    reason="Set TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL for disposable PostgreSQL tests",
)
OWNER = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
OTHER = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, ConnectionPool]]:
    assert ADMIN_URL and RUNTIME_URL
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        for table in ("oauth_authorization_codes", "oauth_refresh_tokens", "personal_access_tokens"):
            admin.execute(f"delete from {table} where user_id = any(%s)", ([OWNER, OTHER],))
        admin.commit()
        for user_id in (OWNER, OTHER):
            admin.execute(
                "insert into auth.users (id, email) values (%s, %s) on conflict (id) do nothing",
                (user_id, f"{user_id}@example.test"),
            )
        admin.commit()
        with ConnectionPool(RUNTIME_URL, min_size=2, max_size=4, kwargs={"row_factory": dict_row}) as pool:
            monkeypatch.setattr(db, "get_pool", lambda: pool)
            yield admin, pool
        admin.execute("delete from oauth_authorization_codes where user_id = any(%s)", ([OWNER, OTHER],))
        admin.execute("delete from oauth_refresh_tokens where user_id = any(%s)", ([OWNER, OTHER],))
        admin.execute("delete from personal_access_tokens where user_id = any(%s)", ([OWNER, OTHER],))
        admin.execute("delete from auth.users where id = any(%s)", ([OWNER, OTHER],))
        admin.commit()


def provider(owner: UUID = OWNER) -> oauth_provider.SingleOwnerOAuthProvider:
    return oauth_provider.SingleOwnerOAuthProvider(
        Settings(
            owner_user_id=owner,
            oauth_client_id="r1-client",
            oauth_client_secret=SecretStr("r1-secret"),
            oauth_issuer_url="https://gateway.example.test",
            mcp_gateway_upstream_url="http://gateway.internal.test/mcp",
        )
    )


def test_cli_verification_against_real_auth_and_disposable_postgres(
    database: tuple[Any, ConnectionPool], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, _pool = database
    settings = Settings(pat_pepper=SecretStr("r2-local-pepper"))
    admin.execute("insert into profiles (id) values (%s) on conflict (id) do nothing", (OWNER,))
    admin.commit()
    monkeypatch.setattr(manage_pat, "hash_pat", lambda token: hash_pat(token, settings))
    created = manage_pat.create_pat(admin, OWNER, "r2-local", ["taxonomy:read"], 1)
    admin.commit()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:

        def handler(request: httpx.Request) -> httpx.Response:
            response = client.get(request.url.path, headers={"Authorization": request.headers.get("authorization", "")})
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        transport = httpx.MockTransport(handler)

        def check() -> VerifyCode:
            return verify_credential(
                "https://local.example.test",
                created.raw_token,
                OWNER,
                created.token_id,
                {"taxonomy:read"},
                transport=transport,
            ).code

        assert check() == VerifyCode.VERIFIED
        app.dependency_overrides[get_settings] = lambda: Settings(pat_pepper=SecretStr("wrong-pepper"))
        assert check() == VerifyCode.AUTH_REJECTED
        app.dependency_overrides[get_settings] = lambda: settings
        admin.execute("update personal_access_tokens set revoked_at = now() where id = %s", (created.token_id,))
        admin.commit()
        assert check() == VerifyCode.AUTH_REJECTED


def test_previous_pepper_authenticates_access_and_refresh_under_runtime_role(
    database: tuple[Any, ConnectionPool],
) -> None:
    admin, _pool = database
    old = Settings(pat_pepper=SecretStr("old-local-pepper"))
    raw_access = "det_r2_previous_access"
    raw_refresh = "r2_previous_refresh"
    row = admin.execute(
        """insert into personal_access_tokens (user_id, token_hash, name, scopes, expires_at)
           values (%s, %s, %s, %s, now() + interval '1 day') returning id""",
        (OWNER, hash_pat(raw_access, old), "r2-old-access", ["taxonomy:read"]),
    ).fetchone()
    assert row is not None
    pat_id = row["id"]
    admin.execute(
        """insert into oauth_refresh_tokens (user_id, token_hash, pat_token_id, expires_at)
           values (%s, %s, %s, now() + interval '1 day')""",
        (OWNER, hash_pat(raw_refresh, old), pat_id),
    )
    admin.commit()
    settings = Settings(
        pat_pepper=SecretStr("new-local-pepper"),
        pat_pepper_version="v2",
        pat_previous_pepper=SecretStr("old-local-pepper"),
        pat_previous_pepper_version="v1",
        pat_previous_pepper_retire_at=datetime.now(UTC) + timedelta(minutes=10),
        owner_user_id=OWNER,
        oauth_client_id="r2-client",
        oauth_client_secret=SecretStr("r2-secret"),
        oauth_issuer_url="https://gateway.example.test",
        mcp_gateway_upstream_url="http://gateway.internal.test/mcp",
    )
    p = oauth_provider.SingleOwnerOAuthProvider(settings)
    assert p._load_access_token(raw_access) is not None
    assert p._load_refresh_token(raw_refresh) is not None
    expired_settings = settings.model_copy(
        update={"pat_previous_pepper_retire_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    expired_provider = oauth_provider.SingleOwnerOAuthProvider(expired_settings)
    assert expired_provider._load_access_token(raw_access) is None
    assert expired_provider._load_refresh_token(raw_refresh) is None
    admin.execute("update personal_access_tokens set revoked_at = now() where id = %s", (pat_id,))
    admin.execute("update oauth_refresh_tokens set revoked_at = now() where pat_token_id = %s", (pat_id,))
    admin.commit()
    assert p._load_access_token(raw_access) is None
    assert p._load_refresh_token(raw_refresh) is None


def issue(p: oauth_provider.SingleOwnerOAuthProvider) -> tuple[str, Any, Any]:
    client = asyncio.run(p.get_client("r1-client"))
    assert client is not None
    redirect = asyncio.run(
        p.authorize(
            client,
            AuthorizationParams(
                state="state",
                scopes=None,
                code_challenge="challenge",
                redirect_uri=AnyUrl(oauth_provider.CLAUDE_REDIRECT_URI),
                redirect_uri_provided_explicitly=True,
                resource="https://gateway.example.test/mcp",
            ),
        )
    )
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    loaded = asyncio.run(p.load_authorization_code(client, code))
    assert loaded is not None
    return code, client, loaded


def counts(admin: Any) -> tuple[int, int, int]:
    row = admin.execute(
        """select (select count(*) from oauth_authorization_codes where user_id = %s) as codes,
                  (select count(*) from personal_access_tokens where user_id = %s) as pats,
                  (select count(*) from oauth_refresh_tokens where user_id = %s) as refreshes""",
        (OWNER, OWNER, OWNER),
    ).fetchone()
    admin.commit()
    return row["codes"], row["pats"], row["refreshes"]


def test_cross_instance_restart_replay_and_digest(database: tuple[Any, ConnectionPool]) -> None:
    admin, _pool = database
    original = provider()
    code, client, loaded = issue(original)
    row = admin.execute("select code_hash from oauth_authorization_codes where user_id = %s", (OWNER,)).fetchone()
    assert row["code_hash"] == oauth_provider.hash_authorization_code(code)
    assert code not in str(row)
    admin.commit()
    del original
    replacement = provider()
    assert asyncio.run(replacement.load_authorization_code(client, code)) is not None
    token = asyncio.run(replacement.exchange_authorization_code(client, loaded))
    assert token.access_token and token.refresh_token
    assert counts(admin) == (0, 1, 1)
    assert asyncio.run(replacement.load_authorization_code(client, code)) is None
    with pytest.raises(TokenError) as replay:
        asyncio.run(replacement.exchange_authorization_code(client, loaded))
    assert replay.value.error == "invalid_grant"
    assert counts(admin) == (0, 1, 1)


def test_expiry_binding_owner_and_rollback(
    database: tuple[Any, ConnectionPool], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, pool = database
    p = provider()
    code, client, loaded = issue(p)
    assert asyncio.run(provider(OTHER).load_authorization_code(client, code)) is None
    with pytest.raises(psycopg.errors.InsufficientPrivilege), admin.transaction():
        admin.execute("set local role authenticated")
        admin.execute("select code_hash from oauth_authorization_codes")
    admin.rollback()
    with pool.connection() as conn, conn.transaction():
        conn.execute("select set_config('app.current_user_id', %s, true)", (str(OTHER),))
        own_count = conn.execute("select count(*) as n from oauth_authorization_codes").fetchone()
        assert isinstance(own_count, dict) and own_count["n"] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), pool.connection() as conn:
        conn.execute("update oauth_authorization_codes set expires_at = now()")
    forged = loaded.model_copy(update={"resource": "https://wrong.example/mcp"})
    with pytest.raises(TokenError):
        asyncio.run(p.exchange_authorization_code(client, forged))
    assert counts(admin) == (1, 0, 0)

    original_insert = p._insert_tokens

    def fail_after_pat(conn: Any, scopes: list[str]) -> Any:
        conn.execute(
            """insert into personal_access_tokens (id, user_id, token_hash, name, scopes)
               values (gen_random_uuid(), %s, %s, 'failed R1 test', %s)""",
            (OWNER, "f" * 64, scopes),
        )
        raise RuntimeError("injected insert failure")

    monkeypatch.setattr(p, "_insert_tokens", fail_after_pat)
    with pytest.raises(RuntimeError, match="injected"):
        asyncio.run(p.exchange_authorization_code(client, loaded))
    assert counts(admin) == (1, 0, 0)
    monkeypatch.setattr(p, "_insert_tokens", original_insert)
    asyncio.run(p.exchange_authorization_code(client, loaded))
    assert counts(admin) == (0, 1, 1)

    expired, _client, expired_loaded = issue(p)
    admin.execute(
        """update oauth_authorization_codes
                     set issued_at = now() - interval '2 minutes', expires_at = now() - interval '1 second'
                     where code_hash = %s""",
        (oauth_provider.hash_authorization_code(expired),),
    )
    admin.commit()
    assert asyncio.run(p.load_authorization_code(client, expired)) is None
    with pytest.raises(TokenError):
        asyncio.run(p.exchange_authorization_code(client, expired_loaded))
    assert counts(admin) == (1, 1, 1)


def test_commit_failure_rolls_back_code_and_tokens_then_allows_retry(
    database: tuple[Any, ConnectionPool], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, _pool = database
    p = provider()
    code, client, loaded = issue(p)
    inserted = False
    original_insert = p._insert_tokens

    def record_completed_inserts(conn: Any, scopes: list[str]) -> Any:
        nonlocal inserted
        result = original_insert(conn, scopes)
        inserted = True
        return result

    monkeypatch.setattr(p, "_insert_tokens", record_completed_inserts)
    # A deferred constraint trigger fails at COMMIT, after both INSERTs finish.
    # Keep the injection scoped to the synthetic owner in this disposable DB.
    admin.execute(
        """create function public.r1_test_fail_commit() returns trigger
           language plpgsql as $$
           begin
               raise exception 'injected R1 commit failure';
           end;
           $$;
           create constraint trigger r1_test_fail_commit
           after insert on public.oauth_refresh_tokens
           deferrable initially deferred for each row
           when (new.user_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'::uuid)
           execute function public.r1_test_fail_commit();"""
    )
    admin.commit()
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected R1 commit failure"):
            asyncio.run(p.exchange_authorization_code(client, loaded))
        assert inserted, "Failure must occur after both token INSERTs complete"
        assert counts(admin) == (1, 0, 0)
        assert asyncio.run(p.load_authorization_code(client, code)) is not None
    finally:
        admin.rollback()
        admin.execute(
            """drop trigger r1_test_fail_commit on public.oauth_refresh_tokens;
               drop function public.r1_test_fail_commit();"""
        )
        admin.commit()

    token = asyncio.run(p.exchange_authorization_code(client, loaded))
    assert token.access_token and token.refresh_token
    assert counts(admin) == (0, 1, 1)
    with pytest.raises(TokenError) as replay:
        asyncio.run(p.exchange_authorization_code(client, loaded))
    assert replay.value.error == "invalid_grant"
    assert counts(admin) == (0, 1, 1)


def test_concurrent_redemption_uses_separate_connections(
    database: tuple[Any, ConnectionPool], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, _pool = database
    p = provider()
    _code, client, loaded = issue(p)
    first_deleted = Event()
    release_first = Event()
    original_insert = p._insert_tokens

    def held_insert(conn: Any, scopes: list[str]) -> Any:
        first_deleted.set()
        assert release_first.wait(timeout=10)
        return original_insert(conn, scopes)

    monkeypatch.setattr(p, "_insert_tokens", held_insert)
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(p._redeem_authorization_code, client, loaded)
        assert first_deleted.wait(timeout=10)
        loser = executor.submit(p._redeem_authorization_code, client, loaded)
        # The second transaction is blocked by the first transaction's row lock.
        # Verify this through PostgreSQL rather than relying on a sleep.
        for _ in range(100):
            waiting = admin.execute(
                """select count(*) as n from pg_stat_activity
                   where datname = current_database() and wait_event_type = 'Lock'
                     and query like 'delete from oauth_authorization_codes%'"""
            ).fetchone()["n"]
            admin.commit()
            if waiting:
                break
            Event().wait(0.01)
        assert waiting == 1
        release_first.set()
        assert winner.result(timeout=10).access_token
        with pytest.raises(TokenError):
            loser.result(timeout=10)
    assert counts(admin) == (0, 1, 1)


def test_expiry_after_row_lock_wait(database: tuple[Any, ConnectionPool]) -> None:
    admin, _pool = database
    p = provider()
    code, client, loaded = issue(p)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with admin.transaction():
            row = admin.execute(
                """update oauth_authorization_codes
                   set expires_at = clock_timestamp() + interval '1 second'
                   where code_hash = %s returning expires_at""",
                (oauth_provider.hash_authorization_code(code),),
            ).fetchone()
            assert row is not None
            expires_at = row["expires_at"]
            # Prime an activity snapshot before the worker starts. Polling in
            # this same lock-holding transaction must explicitly refresh it.
            admin.execute("select count(*) from pg_stat_activity").fetchone()
            pending = executor.submit(p._redeem_authorization_code, client, loaded)
            waiting = 0
            for _ in range(200):
                admin.execute("select pg_stat_clear_snapshot()")
                waiting = admin.execute(
                    """select count(*) as n from pg_stat_activity
                       where datname = current_database() and wait_event_type = 'Lock'
                         and query like 'delete from oauth_authorization_codes%'"""
                ).fetchone()["n"]
                if waiting:
                    break
                Event().wait(0.01)
            assert waiting == 1
            expired = False
            for _ in range(200):
                expired = admin.execute("select clock_timestamp() >= %s as expired", (expires_at,)).fetchone()[
                    "expired"
                ]
                if expired:
                    break
                Event().wait(0.01)
            assert expired
        with pytest.raises(TokenError) as result:
            pending.result(timeout=10)
        assert result.value.error == "invalid_grant"
    assert counts(admin) == (1, 0, 0)


def test_real_sdk_routes_validate_bindings(database: tuple[Any, ConnectionPool]) -> None:
    admin, _pool = database
    p = provider()
    app = FastAPI()
    app.router.routes.extend(oauth_provider.build_oauth_routes(p._settings, provider=p))
    verifier = "r1-valid-verifier-" + "x" * 40
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with TestClient(app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "r1-client",
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "https://gateway.example.test/mcp",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "r1-client",
            "client_secret": "r1-secret",
            "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
            "code_verifier": verifier,
        }
        wrong_verifier = client.post("/token", data={**payload, "code_verifier": "bad-verifier"})
        assert wrong_verifier.status_code == 400 and wrong_verifier.json()["error"] == "invalid_grant"
        wrong_redirect = client.post("/token", data={**payload, "redirect_uri": "https://wrong.example/callback"})
        assert wrong_redirect.status_code == 400 and wrong_redirect.json()["error"] == "invalid_request"
        wrong_resource = client.post("/token", data={**payload, "resource": "https://wrong.example/mcp"})
        assert wrong_resource.status_code == 400 and wrong_resource.json()["error"] == "invalid_grant"
        empty_resource = client.post("/token", data={**payload, "resource": ""})
        assert empty_resource.status_code == 400 and empty_resource.json()["error"] == "invalid_grant"
        duplicate_grant = client.post(
            "/token",
            content=urlencode(
                [*payload.items(), ("grant_type", "authorization_code"), ("resource", "https://wrong.example/mcp")]
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert duplicate_grant.status_code == 400 and duplicate_grant.json()["error"] == "invalid_request"
        multipart = client.post("/token", data=payload, files={"resource": (None, "https://wrong.example/mcp")})
        assert multipart.status_code == 400 and multipart.json()["error"] == "invalid_request"
        wrong_secret = client.post("/token", data={**payload, "client_secret": "wrong-secret"})
        assert wrong_secret.status_code == 401
        assert counts(admin) == (1, 0, 0)
        success = client.post("/token", data={**payload, "resource": "https://gateway.example.test/mcp"})
        assert success.status_code == 200, success.text
        assert counts(admin) == (0, 1, 1)

        # The SDK permits omitting redirect_uri at both endpoints when the
        # registered client has exactly one callback. Preserve that contract.
        optional = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "r1-client",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert optional.status_code == 302
        optional_code = parse_qs(urlsplit(optional.headers["location"]).query)["code"][0]
        optional_payload = {key: value for key, value in payload.items() if key != "redirect_uri"}
        omitted_redirect = client.post("/token", data={**optional_payload, "code": optional_code})
        assert omitted_redirect.status_code == 200, omitted_redirect.text
        assert counts(admin) == (0, 2, 2)


def test_authorize_storage_failure_has_no_code_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    p = provider()
    app = FastAPI()
    app.router.routes.extend(oauth_provider.build_oauth_routes(p._settings, provider=p))

    def unavailable(*_args: Any) -> None:
        raise psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(p, "_store_authorization_code", unavailable)
    with TestClient(app) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "r1-client",
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    assert response.status_code in (302, 500)
    assert "code=" not in response.headers.get("location", "")
