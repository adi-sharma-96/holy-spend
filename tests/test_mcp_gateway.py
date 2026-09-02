import asyncio
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp_gateway import build_gateway_router
from app.security import AuthenticatedUser, get_current_user

UPSTREAM_URL = "http://daily-expense-mcp.railway.internal:8000/mcp"


class _AsyncBytesStream(httpx.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __aiter__(self) -> Any:
        yield self._body


def _streamed_response(
    status_code: int, body: bytes = b"{}", headers: dict[str, str] | None = None
) -> httpx.Response:
    # Mirrors what a real streamed HTTP transport hands back: content not yet
    # read into memory (unlike Response(content=...), which reads eagerly),
    # so the gateway's own aiter_raw() consumption is exercised for real.
    return httpx.Response(status_code, headers=headers, stream=_AsyncBytesStream(body))


def _authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UUID("33333333-3333-3333-3333-333333333333"),
        token_id=UUID("44444444-4444-4444-4444-444444444444"),
        scopes=("*",),
    )


def _build_client(handler: Any, use_google_id_token: bool = False) -> tuple[FastAPI, httpx.AsyncClient]:
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.include_router(build_gateway_router(UPSTREAM_URL, upstream_client, use_google_id_token))
    return app, upstream_client


def test_proxy_rejects_missing_bearer_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called without a valid PAT")

    app, upstream_client = _build_client(handler)
    with TestClient(app) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "ping"})

    assert response.status_code == 401
    asyncio.run(upstream_client.aclose())


def test_proxy_forwards_authenticated_post_and_streams_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = request.read()
        return _streamed_response(
            200,
            body=b'{"jsonrpc": "2.0", "result": {"ok": true}}',
            headers={"content-type": "application/json", "mcp-session-id": "sess-1"},
        )

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=b'{"jsonrpc": "2.0", "method": "tools/call"}',
            headers={
                "Authorization": "Bearer det_should-not-reach-upstream",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": "sess-1",
            },
        )
    asyncio.run(upstream_client.aclose())

    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "result": {"ok": True}}
    assert response.headers["mcp-session-id"] == "sess-1"

    assert captured["method"] == "POST"
    assert captured["url"] == UPSTREAM_URL
    assert captured["body"] == b'{"jsonrpc": "2.0", "method": "tools/call"}'
    assert captured["headers"]["mcp-session-id"] == "sess-1"
    assert captured["headers"]["accept"] == "application/json, text/event-stream"
    assert "authorization" not in captured["headers"]


def test_proxy_strips_hop_by_hop_and_recomputes_host() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _streamed_response(200)

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        client.post(
            "/mcp",
            content=b"{}",
            headers={
                "Authorization": "Bearer det_client-token",
                "Host": "public-gateway.example.com",
                "Connection": "keep-alive",
            },
        )
    asyncio.run(upstream_client.aclose())

    assert captured["headers"]["host"] == "daily-expense-mcp.railway.internal:8000"
    assert "authorization" not in captured["headers"]
    # The upstream connection's own Connection header is httpx's, not a
    # blind copy of the client's; only check we didn't forward "close".
    assert captured["headers"]["connection"] != "close"


def test_proxy_forwards_query_string() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _streamed_response(200)

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        client.post("/mcp?foo=bar", content=b"{}")
    asyncio.run(upstream_client.aclose())

    assert captured["url"] == f"{UPSTREAM_URL}?foo=bar"


def test_proxy_get_request_has_no_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.read()
        return _streamed_response(
            200,
            body=b"event: message\ndata: {}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})
    asyncio.run(upstream_client.aclose())

    assert response.status_code == 200
    assert captured["method"] == "GET"
    assert captured["body"] == b""


def test_proxy_propagates_upstream_error_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _streamed_response(404, body=b'{"detail": "Not Found"}')

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        response = client.post("/mcp", content=b"{}")
    asyncio.run(upstream_client.aclose())

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_proxy_delete_forwards_session_termination() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _streamed_response(200, body=b"")

    app, upstream_client = _build_client(handler)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        response = client.delete("/mcp", headers={"Mcp-Session-Id": "sess-1"})
    asyncio.run(upstream_client.aclose())

    assert response.status_code == 200
    assert captured["method"] == "DELETE"
    assert captured["headers"]["mcp-session-id"] == "sess-1"


def test_proxy_attaches_google_id_token_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _streamed_response(200)

    def fake_id_token(audience: str) -> str:
        captured["audience"] = audience
        return "fake-google-id-token"

    monkeypatch.setattr("app.mcp_gateway._google_id_token", fake_id_token)

    app, upstream_client = _build_client(handler, use_google_id_token=True)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        client.post("/mcp", content=b"{}", headers={"Authorization": "Bearer det_client-token"})
    asyncio.run(upstream_client.aclose())

    assert captured["audience"] == UPSTREAM_URL
    assert captured["headers"]["authorization"] == "Bearer fake-google-id-token"


def test_proxy_omits_authorization_when_google_id_token_disabled() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _streamed_response(200)

    app, upstream_client = _build_client(handler, use_google_id_token=False)
    app.dependency_overrides[get_current_user] = _authenticated_user
    with TestClient(app) as client:
        client.post("/mcp", content=b"{}")
    asyncio.run(upstream_client.aclose())

    assert "authorization" not in captured["headers"]


@pytest.mark.parametrize(
    "mcp_enabled,gateway_url,should_raise",
    [
        (False, None, False),
        (True, None, False),
        (False, "http://daily-expense-mcp.railway.internal:8000/mcp", False),
        (True, "http://daily-expense-mcp.railway.internal:8000/mcp", True),
    ],
)
def test_settings_reject_mcp_enabled_with_gateway_url(
    mcp_enabled: bool, gateway_url: str | None, should_raise: bool
) -> None:
    from app.config import Settings

    kwargs: dict[str, Any] = {"mcp_enabled": mcp_enabled}
    if gateway_url is not None:
        kwargs["mcp_gateway_upstream_url"] = gateway_url

    if should_raise:
        with pytest.raises(ValueError, match="mutually exclusive"):
            Settings(**kwargs)
    else:
        Settings(**kwargs)


def test_settings_reject_google_id_token_without_gateway_url() -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="requires MCP_GATEWAY_UPSTREAM_URL"):
        Settings(mcp_enabled=False, mcp_gateway_use_google_id_token=True)

    Settings(
        mcp_enabled=False,
        mcp_gateway_use_google_id_token=True,
        mcp_gateway_upstream_url="http://holy-spend-mcp-abc.a.run.app/mcp",
    )
