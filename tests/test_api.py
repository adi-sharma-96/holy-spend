from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import RequestContext, get_request_context
from app.main import create_app
from app.security import AuthenticatedUser


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeTaxonomyConn:
    def execute(self, query: str, params: dict[str, Any] | None = None) -> FakeResult:
        if "from categories" in query:
            return FakeResult(
                [
                    {
                        "id": UUID("11111111-1111-1111-1111-111111111111"),
                        "slug": "grocery",
                        "parent_id": None,
                        "name": "Grocery & Everyday Retail",
                        "depth": 0,
                        "path_slug": "grocery",
                        "sort_order": 10,
                        "is_assignable": False,
                    }
                ]
            )
        if "from themes" in query:
            return FakeResult(
                [
                    {
                        "id": UUID("22222222-2222-2222-2222-222222222222"),
                        "slug": "fresh",
                        "name": "Fresh",
                        "description": "Fresh or refrigerated item.",
                    }
                ]
            )
        return FakeResult([])


class FakeTransactionListConn:
    def execute(self, query: str, params: dict[str, Any] | None = None) -> FakeResult:
        if query.strip().startswith("select count(*) as total"):
            return FakeResult([{"total": 0}])
        return FakeResult([])


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def authenticated_user(scopes: tuple[str, ...] = ("taxonomy:read",)) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=UUID("33333333-3333-3333-3333-333333333333"),
        token_id=UUID("44444444-4444-4444-4444-444444444444"),
        scopes=scopes,
    )


def request_context(scopes: tuple[str, ...] = ("taxonomy:read",)) -> RequestContext:
    return RequestContext(user=authenticated_user(scopes), conn=FakeTaxonomyConn())


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": get_settings().app_name,
        "environment": get_settings().environment,
    }


def test_cors_allows_claude_and_rejects_an_unlisted_origin(client: TestClient) -> None:
    # A web-based connector (Claude) issues /mcp and /authorize as real
    # cross-origin browser fetches, unlike a server-side one (ChatGPT) - without
    # this, the browser's own preflight silently fails before the bearer token
    # is ever checked, which looks identical to "can't reach the server" from
    # the user's side. Regression coverage for that gap.
    allowed = client.options(
        "/health",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "https://claude.ai"

    disallowed = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in disallowed.headers


def test_obsolete_receipt_upload_routes_are_removed(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])

    assert "/v1/receipts/drafts" not in paths
    assert "/v1/receipts/{receipt_id}/files/upload-target" not in paths
    assert "/v1/receipts/{receipt_id}/files/confirm" not in paths
    assert "/v1/receipts/{receipt_id}/files/upload" not in paths
    assert "/v1/receipts/{receipt_id}/files/{file_id}/download-url" in paths
    assert "/v2/taxonomy/manifest" in paths
    assert "/v2/taxonomy/branches/{stable_key}" in paths
    assert "/v2/taxonomy/search" in paths


def test_taxonomy_requires_auth(client: TestClient) -> None:
    response = client.get("/v1/taxonomy")

    assert response.status_code == 401
    assert client.get("/v2/taxonomy/manifest").status_code == 401
    assert client.get("/v2/taxonomy/search?q=apple").status_code == 401


def test_taxonomy_returns_categories_and_themes(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_request_context] = request_context

    response = client.get("/v1/taxonomy", headers={"Authorization": "Bearer test"})

    assert response.status_code == 200
    body = response.json()
    assert body["categories"][0]["slug"] == "grocery"
    assert body["categories"][0]["is_assignable"] is False
    assert body["themes"][0]["slug"] == "fresh"


def test_taxonomy_scope_is_required(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_request_context] = lambda: request_context(scopes=())

    response = client.get("/v1/taxonomy", headers={"Authorization": "Bearer test"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required scope: taxonomy:read"


def test_analytics_endpoint_returns_confirmed_only_response(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_request_context] = lambda: request_context(scopes=("analytics:read",))

    response = client.post(
        "/v1/analytics/query",
        headers={"Authorization": "Bearer test"},
        json={"metrics": ["total_spend"], "filters": {"relative_days": 25}},
    )

    assert response.status_code == 200
    assert response.json() == {"rows": [], "confirmed_only": True}


def test_analytics_endpoint_rejects_non_allowlisted_metric(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_request_context] = lambda: request_context(scopes=("analytics:read",))

    response = client.post(
        "/v1/analytics/query",
        headers={"Authorization": "Bearer test"},
        json={"metrics": ["run_sql"]},
    )

    assert response.status_code == 422


def test_transaction_list_query_model_and_scope(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    context = RequestContext(
        user=authenticated_user(("transactions:read",)),
        conn=FakeTransactionListConn(),
    )
    app.dependency_overrides[get_request_context] = lambda: context

    response = client.get(
        "/v1/transactions?status=confirmed&limit=10&offset=0",
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    assert response.json() == {"transactions": [], "total": 0, "limit": 10, "offset": 0}
