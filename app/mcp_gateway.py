from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import fetch_id_token
from starlette.background import BackgroundTask

from app.security import AuthenticatedUser, get_current_user


# Only ever called when MCP_GATEWAY_USE_GOOGLE_ID_TOKEN is set (Cloud Run deployments -
# see docs/gcp-cloud-run-deployment.md), where this metadata-server call is a fast local
# link-local request, not a network round-trip. Minted fresh per request rather than
# cached: correctness over the single-digit milliseconds a cache would save here.
def _google_id_token(audience: str) -> str:
    return str(fetch_id_token(GoogleAuthRequest(), audience))  # type: ignore[no-untyped-call]

# A public-network hop terminates and re-originates the connection, so these
# must never be copied onto the upstream request/response verbatim (RFC 7230
# 6.1), plus Host (recomputed for the upstream target) and Authorization
# (this gateway's own PAT, which the trusted-network upstream never needs).
_EXCLUDED_REQUEST_HEADERS = frozenset(
    {
        "host",
        "authorization",
        "content-length",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
        "proxy-authenticate",
        "proxy-authorization",
    }
)
_EXCLUDED_RESPONSE_HEADERS = frozenset(
    {
        "content-length",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
    }
)

# MCP tool calls can carry receipt-file bytes and trigger downstream storage
# and database work; generous relative to the REST receipt-download timeouts.
UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def new_upstream_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)


async def _drain(upstream_response: httpx.Response) -> AsyncIterator[bytes]:
    async for chunk in upstream_response.aiter_raw():
        yield chunk


def build_gateway_router(
    upstream_url: str,
    client: httpx.AsyncClient,
    use_google_id_token: bool = False,
) -> APIRouter:
    router = APIRouter()

    @router.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def proxy_mcp(
        request: Request,
        _user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> StreamingResponse:
        target = httpx.URL(upstream_url)
        if request.url.query:
            target = target.copy_with(query=request.url.query.encode())

        forwarded_headers = [
            (key, value)
            for key, value in request.headers.items()
            if key.lower() not in _EXCLUDED_REQUEST_HEADERS
        ]
        if use_google_id_token:
            forwarded_headers.append(("authorization", f"Bearer {_google_id_token(upstream_url)}"))
        body = request.stream() if request.method in ("POST", "PUT", "PATCH") else None

        upstream_request = client.build_request(
            request.method,
            target,
            headers=forwarded_headers,
            content=body,
        )
        upstream_response = await client.send(upstream_request, stream=True)

        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in _EXCLUDED_RESPONSE_HEADERS
        }
        return StreamingResponse(
            _drain(upstream_response),
            status_code=upstream_response.status_code,
            headers=response_headers,
            background=BackgroundTask(upstream_response.aclose),
        )

    return router
