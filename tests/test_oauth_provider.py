from typing import Any
from uuid import UUID

import pytest
from mcp.server.auth.provider import AuthorizationParams
from pydantic import AnyUrl, SecretStr

from app import oauth_provider
from app.config import Settings
from app.oauth_provider import SingleOwnerOAuthProvider

OWNER_USER_ID = UUID("55555555-5555-5555-5555-555555555555")
PAT_TOKEN_ID = UUID("66666666-6666-6666-6666-666666666666")
REFRESH_TOKEN_ID = UUID("77777777-7777-7777-7777-777777777777")


class FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class FakeConn:
    def __init__(self, responses: dict[str, dict[str, Any] | None] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self._responses = responses or {}

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> FakeResult:
        self.calls.append((sql, params or {}))
        for marker, row in self._responses.items():
            if marker in sql:
                return FakeResult(row)
        return FakeResult(None)

    def commit(self) -> None:
        self.commits += 1


class FakeConnCtx:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> FakeConn:
        return self._conn

    def __exit__(self, *_args: object) -> None:
        return None


def make_settings() -> Settings:
    return Settings(
        owner_user_id=OWNER_USER_ID,
        oauth_client_id="gw-client",
        oauth_client_secret=SecretStr("gw-secret"),
        oauth_issuer_url="https://gateway.example.test",
        mcp_gateway_upstream_url="http://daily-expense-mcp.railway.internal:8000/mcp",
        mcp_enabled=False,
    )


def patch_db(monkeypatch: pytest.MonkeyPatch, conn: FakeConn) -> None:
    monkeypatch.setattr(oauth_provider, "connection", lambda: FakeConnCtx(conn))
    monkeypatch.setattr(oauth_provider, "user_transaction", lambda _user_id: FakeConnCtx(conn))


def make_params(**overrides: Any) -> AuthorizationParams:
    defaults: dict[str, Any] = dict(
        state="xyz",
        scopes=None,
        code_challenge="challenge-abc",
        redirect_uri=AnyUrl(oauth_provider.CLAUDE_REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
        resource="https://gateway.example.test/mcp",
    )
    defaults.update(overrides)
    return AuthorizationParams(**defaults)


def test_provider_requires_owner_user_id() -> None:
    settings = make_settings().model_copy(update={"owner_user_id": None})
    with pytest.raises(ValueError, match="OWNER_USER_ID"):
        SingleOwnerOAuthProvider(settings)


def test_provider_requires_oauth_credentials() -> None:
    settings = make_settings().model_copy(update={"oauth_client_id": None})
    with pytest.raises(ValueError, match="OAUTH_CLIENT_ID"):
        SingleOwnerOAuthProvider(settings)


@pytest.mark.anyio
async def test_get_client_matches_only_the_configured_client_id() -> None:
    provider = SingleOwnerOAuthProvider(make_settings())

    assert (await provider.get_client("gw-client")) is not None
    assert (await provider.get_client("someone-else")) is None


@pytest.mark.anyio
async def test_client_accepts_claude_and_configured_additional_redirect_uris() -> None:
    settings = make_settings().model_copy(
        update={"oauth_additional_redirect_uris": "https://chatgpt.com/connector/oauth/dbnT04doIBhY"}
    )
    provider = SingleOwnerOAuthProvider(settings)
    client = await provider.get_client("gw-client")

    assert client is not None
    assert client.redirect_uris is not None
    redirect_uris = {str(uri) for uri in client.redirect_uris}
    assert oauth_provider.CLAUDE_REDIRECT_URI in redirect_uris
    assert "https://chatgpt.com/connector/oauth/dbnT04doIBhY" in redirect_uris


def test_additional_oauth_redirect_uris_rejects_non_absolute_http_urls() -> None:
    settings = make_settings().model_copy(update={"oauth_additional_redirect_uris": "not-a-url"})

    with pytest.raises(ValueError, match="OAUTH_ADDITIONAL_REDIRECT_URIS"):
        settings.additional_oauth_redirect_uris()


@pytest.mark.anyio
async def test_register_client_is_disabled() -> None:
    provider = SingleOwnerOAuthProvider(make_settings())
    client = await provider.get_client("gw-client")
    assert client is not None

    with pytest.raises(NotImplementedError):
        await provider.register_client(client)


@pytest.mark.anyio
async def test_authorize_stores_pending_code_and_redirects_with_state() -> None:
    provider = SingleOwnerOAuthProvider(make_settings())
    client = await provider.get_client("gw-client")
    assert client is not None
    params = make_params()

    redirect_url = await provider.authorize(client, params)

    assert redirect_url.startswith(oauth_provider.CLAUDE_REDIRECT_URI)
    assert "state=xyz" in redirect_url
    assert "code=" in redirect_url
    assert len(provider._pending_codes) == 1
    pending = next(iter(provider._pending_codes.values()))
    assert pending.code_challenge == "challenge-abc"
    assert pending.scopes == list(oauth_provider.FULL_SCOPES)


@pytest.mark.anyio
async def test_load_authorization_code_returns_none_for_unknown_code() -> None:
    provider = SingleOwnerOAuthProvider(make_settings())
    client = await provider.get_client("gw-client")
    assert client is not None

    assert await provider.load_authorization_code(client, "does-not-exist") is None


@pytest.mark.anyio
async def test_exchange_authorization_code_mints_pat_and_refresh_row_then_consumes_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    patch_db(monkeypatch, conn)
    monkeypatch.setattr(oauth_provider, "generate_pat", lambda: "det_minted-access")
    monkeypatch.setattr(oauth_provider, "generate_refresh_token", lambda: "minted-refresh")

    provider = SingleOwnerOAuthProvider(make_settings())
    client = await provider.get_client("gw-client")
    assert client is not None
    await provider.authorize(client, make_params())
    code = next(iter(provider._pending_codes))
    auth_code = await provider.load_authorization_code(client, code)
    assert auth_code is not None

    token = await provider.exchange_authorization_code(client, auth_code)

    assert code not in provider._pending_codes
    assert token.access_token == "det_minted-access"
    assert token.refresh_token == "minted-refresh"
    assert token.expires_in == oauth_provider.ACCESS_TOKEN_TTL_SECONDS
    assert token.scope == " ".join(oauth_provider.FULL_SCOPES)

    pat_sql, pat_params = next(c for c in conn.calls if "insert into personal_access_tokens" in c[0])
    assert pat_params["user_id"] == OWNER_USER_ID
    assert pat_params["scopes"] == list(oauth_provider.FULL_SCOPES)
    assert "id" in pat_sql

    refresh_sql, refresh_params = next(c for c in conn.calls if "insert into oauth_refresh_tokens" in c[0])
    # No `returning id` under RLS with a revoked SELECT grant (see comment in
    # _mint_tokens); the two inserts must instead agree on a client-generated id.
    assert refresh_params["pat_token_id"] == pat_params["id"]
    assert refresh_params["user_id"] == OWNER_USER_ID


@pytest.mark.anyio
async def test_load_refresh_token_returns_none_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, FakeConn())
    provider = SingleOwnerOAuthProvider(make_settings())

    assert await provider.load_refresh_token(None, "bogus") is None  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_load_refresh_token_returns_linked_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(
        responses={
            "app.authenticate_oauth_refresh_token": {
                "refresh_token_id": REFRESH_TOKEN_ID,
                "user_id": OWNER_USER_ID,
                "pat_token_id": PAT_TOKEN_ID,
            }
        }
    )
    patch_db(monkeypatch, conn)
    provider = SingleOwnerOAuthProvider(make_settings())

    result = await provider.load_refresh_token(None, "raw-refresh-token")  # type: ignore[arg-type]

    assert result is not None
    assert result.pat_token_id == PAT_TOKEN_ID
    assert result.refresh_token_row_id == REFRESH_TOKEN_ID
    assert result.subject == str(OWNER_USER_ID)


@pytest.mark.anyio
async def test_exchange_refresh_token_revokes_old_rows_then_mints_new(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    patch_db(monkeypatch, conn)
    monkeypatch.setattr(oauth_provider, "generate_pat", lambda: "det_new-access")
    monkeypatch.setattr(oauth_provider, "generate_refresh_token", lambda: "new-refresh")

    provider = SingleOwnerOAuthProvider(make_settings())
    old = oauth_provider._RefreshToken(
        token="old-raw",
        client_id="gw-client",
        scopes=list(oauth_provider.FULL_SCOPES),
        subject=str(OWNER_USER_ID),
        pat_token_id=PAT_TOKEN_ID,
        refresh_token_row_id=REFRESH_TOKEN_ID,
    )

    new_tokens = await provider.exchange_refresh_token(None, old, list(oauth_provider.FULL_SCOPES))  # type: ignore[arg-type]

    assert new_tokens.access_token == "det_new-access"
    assert new_tokens.refresh_token == "new-refresh"

    revoke_pat_call = next(
        c
        for c in conn.calls
        if "update personal_access_tokens" in c[0] and c[1].get("id") == PAT_TOKEN_ID
    )
    assert revoke_pat_call[1]["user_id"] == OWNER_USER_ID
    revoke_refresh_call = next(
        c
        for c in conn.calls
        if "update oauth_refresh_tokens" in c[0] and c[1].get("id") == REFRESH_TOKEN_ID
    )
    assert revoke_refresh_call[1]["user_id"] == OWNER_USER_ID


@pytest.mark.anyio
async def test_load_access_token_returns_none_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, FakeConn())
    provider = SingleOwnerOAuthProvider(make_settings())

    assert await provider.load_access_token("not-a-real-token") is None


@pytest.mark.anyio
async def test_load_access_token_returns_scopes_from_db(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(
        responses={
            "app.authenticate_pat": {
                "token_id": PAT_TOKEN_ID,
                "user_id": OWNER_USER_ID,
                "scopes": ["transactions:read"],
            }
        }
    )
    patch_db(monkeypatch, conn)
    provider = SingleOwnerOAuthProvider(make_settings())

    result = await provider.load_access_token("det_some-token")

    assert result is not None
    assert result.pat_token_id == PAT_TOKEN_ID
    assert result.scopes == ["transactions:read"]
    assert result.subject == str(OWNER_USER_ID)


@pytest.mark.anyio
async def test_revoke_token_for_access_token_only_revokes_pat(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    patch_db(monkeypatch, conn)
    provider = SingleOwnerOAuthProvider(make_settings())
    access_token = oauth_provider._AccessToken(
        token="det_x", client_id="gw-client", scopes=[], subject=str(OWNER_USER_ID), pat_token_id=PAT_TOKEN_ID
    )

    await provider.revoke_token(access_token)

    assert len(conn.calls) == 1
    assert "update personal_access_tokens" in conn.calls[0][0]


@pytest.mark.anyio
async def test_revoke_token_for_refresh_token_revokes_both_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    patch_db(monkeypatch, conn)
    provider = SingleOwnerOAuthProvider(make_settings())
    refresh_token = oauth_provider._RefreshToken(
        token="raw",
        client_id="gw-client",
        scopes=list(oauth_provider.FULL_SCOPES),
        subject=str(OWNER_USER_ID),
        pat_token_id=PAT_TOKEN_ID,
        refresh_token_row_id=REFRESH_TOKEN_ID,
    )

    await provider.revoke_token(refresh_token)

    tables_touched = {
        "personal_access_tokens" if "personal_access_tokens" in sql else "oauth_refresh_tokens"
        for sql, _ in conn.calls
    }
    assert tables_touched == {"personal_access_tokens", "oauth_refresh_tokens"}
