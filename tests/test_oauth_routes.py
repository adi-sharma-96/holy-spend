import base64
import hashlib
import itertools
import secrets as py_secrets
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import oauth_provider
from app.config import Settings
from app.main import create_app
from app.oauth_provider import SingleOwnerOAuthProvider, build_oauth_routes

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
        self._responses = responses or {}

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> FakeResult:
        self.calls.append((sql, params or {}))
        for marker, row in self._responses.items():
            if marker in sql:
                return FakeResult(row)
        return FakeResult(None)

    def commit(self) -> None:
        pass


class FakeConnCtx:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> FakeConn:
        return self._conn

    def __exit__(self, *_args: object) -> None:
        return None


def patch_db(monkeypatch: pytest.MonkeyPatch, conn: FakeConn) -> None:
    monkeypatch.setattr(oauth_provider, "connection", lambda: FakeConnCtx(conn))
    monkeypatch.setattr(oauth_provider, "user_transaction", lambda _user_id: FakeConnCtx(conn))


def make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        owner_user_id=OWNER_USER_ID,
        oauth_client_id="gw-client",
        oauth_client_secret=SecretStr("gw-secret"),
        oauth_issuer_url="https://gateway.example.test",
        mcp_gateway_upstream_url="http://daily-expense-mcp.railway.internal:8000/mcp",
        mcp_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_pkce_pair() -> tuple[str, str]:
    verifier = py_secrets.token_urlsafe(43)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def authorize_query(challenge: str, state: str = "xyz") -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": "gw-client",
        "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }


def test_gateway_app_has_no_oauth_routes_when_unconfigured() -> None:
    # This mirrors what's actually deployed today: MCP_GATEWAY_UPSTREAM_URL
    # set, no OAuth vars. Confirms adding OAuth support is additive and does
    # not disturb the PAT-only gateway already in production.
    with TestClient(create_app()) as client:
        response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 404


def test_oauth_metadata_discovery() -> None:
    settings = make_settings()
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings))

    with TestClient(app) as client:
        auth_meta = client.get("/.well-known/oauth-authorization-server")
        resource_meta = client.get("/.well-known/oauth-protected-resource/mcp")

    assert auth_meta.status_code == 200
    auth_data = auth_meta.json()
    assert auth_data["authorization_endpoint"] == "https://gateway.example.test/authorize"
    assert auth_data["token_endpoint"] == "https://gateway.example.test/token"
    assert auth_data["code_challenge_methods_supported"] == ["S256"]
    assert auth_data.get("registration_endpoint") is None

    assert resource_meta.status_code == 200
    resource_data = resource_meta.json()
    assert resource_data["resource"] == "https://gateway.example.test/mcp"
    assert resource_data["authorization_servers"] == ["https://gateway.example.test/"]


def test_authorize_rejects_unknown_client() -> None:
    settings = make_settings()
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings))
    _verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        response = client.get(
            "/authorize", params={**authorize_query(challenge), "client_id": "someone-else"}, follow_redirects=False
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_authorize_rejects_unregistered_redirect_uri() -> None:
    settings = make_settings()
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings))
    _verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        response = client.get(
            "/authorize",
            params={**authorize_query(challenge), "redirect_uri": "https://attacker.example/callback"},
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_full_authorization_code_and_refresh_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(
        responses={
            "app.authenticate_oauth_refresh_token": {
                "refresh_token_id": REFRESH_TOKEN_ID,
                "user_id": OWNER_USER_ID,
                "pat_token_id": PAT_TOKEN_ID,
            },
        }
    )
    patch_db(monkeypatch, conn)
    counter = itertools.count()
    monkeypatch.setattr(oauth_provider, "generate_pat", lambda: f"det_access-{next(counter)}")
    monkeypatch.setattr(oauth_provider, "generate_refresh_token", lambda: f"opaque-{next(counter)}")

    settings = make_settings()
    provider = SingleOwnerOAuthProvider(settings)
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings, provider=provider))
    verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        authorize_response = client.get("/authorize", params=authorize_query(challenge), follow_redirects=False)
        assert authorize_response.status_code == 302
        location = authorize_response.headers["location"]
        query = parse_qs(urlsplit(location).query)
        assert query["state"] == ["xyz"]
        code = query["code"][0]

        token_response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "client_id": "gw-client",
                "client_secret": "gw-secret",
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200, token_response.text
        tokens = token_response.json()
        assert tokens["access_token"].startswith("det_access-")
        assert tokens["token_type"] == "Bearer"
        first_refresh_token = tokens["refresh_token"]

        refresh_response = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first_refresh_token,
                "client_id": "gw-client",
                "client_secret": "gw-secret",
            },
        )
        assert refresh_response.status_code == 200, refresh_response.text
        rotated = refresh_response.json()
        assert rotated["access_token"] != tokens["access_token"]
        assert rotated["refresh_token"] != first_refresh_token

    revoke_calls = [c for c in conn.calls if "update personal_access_tokens" in c[0]]
    assert len(revoke_calls) == 1
    assert revoke_calls[0][1]["id"] == PAT_TOKEN_ID


def test_token_exchange_rejects_wrong_client_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, FakeConn())
    settings = make_settings()
    provider = SingleOwnerOAuthProvider(settings)
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings, provider=provider))
    verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        authorize_response = client.get("/authorize", params=authorize_query(challenge), follow_redirects=False)
        code = parse_qs(urlsplit(authorize_response.headers["location"]).query)["code"][0]

        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "client_id": "gw-client",
                "client_secret": "wrong-secret",
                "code_verifier": verifier,
            },
        )

    assert response.status_code == 401


def test_token_exchange_rejects_wrong_code_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, FakeConn())
    settings = make_settings()
    provider = SingleOwnerOAuthProvider(settings)
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings, provider=provider))
    _verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        authorize_response = client.get("/authorize", params=authorize_query(challenge), follow_redirects=False)
        code = parse_qs(urlsplit(authorize_response.headers["location"]).query)["code"][0]

        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "client_id": "gw-client",
                "client_secret": "gw-secret",
                "code_verifier": "totally-wrong-verifier",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_token_exchange_rejects_expired_code(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_db(monkeypatch, FakeConn())
    settings = make_settings()
    provider = SingleOwnerOAuthProvider(settings)
    app = FastAPI()
    app.router.routes.extend(build_oauth_routes(settings, provider=provider))
    verifier, challenge = make_pkce_pair()

    with TestClient(app) as client:
        authorize_response = client.get("/authorize", params=authorize_query(challenge), follow_redirects=False)
        code = parse_qs(urlsplit(authorize_response.headers["location"]).query)["code"][0]
        provider._pending_codes[code].expires_at = 0.0

        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth_provider.CLAUDE_REDIRECT_URI,
                "client_id": "gw-client",
                "client_secret": "gw-secret",
                "code_verifier": verifier,
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
