import asyncio
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult

import app.mcp_server as mcp_server_module
from app.config import Settings, get_settings
from app.dashboard import DashboardRepository
from app.main import create_app
from app.mcp_server import (
    WIDGET_MIME_TYPE,
    WIDGET_URI,
    _hidden_result,
    _widget_content_version,
    create_mcp_server,
)
from app.plugin_models import ExpenseDashboard, OperationResult
from app.principal import SingleUserPrincipalResolver

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")


def mcp_settings(**overrides: Any) -> Settings:
    values = {
        "owner_user_id": OWNER_ID,
        "mcp_allowed_hosts": "testserver,127.0.0.1:*,localhost:*",
        **overrides,
    }
    return Settings.model_validate(values)


def test_single_user_principal_is_server_owned() -> None:
    principal = SingleUserPrincipalResolver(mcp_settings()).resolve()

    assert principal.user_id == OWNER_ID
    assert principal.auth_mode == "single_user"


def test_widget_resource_version_changes_with_built_content(tmp_path: Path) -> None:
    widget = tmp_path / "index.html"
    widget.write_text("<html>first build</html>", encoding="utf-8")
    first = _widget_content_version(widget)
    widget.write_text("<html>second build</html>", encoding="utf-8")
    second = _widget_content_version(widget)

    assert first.startswith("v40-")
    assert second.startswith("v40-")
    assert first != second


def test_single_resource_and_tool_surface_contract() -> None:
    server = create_mcp_server(mcp_settings())
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert len(tools) == 33
    assert {
        "get_expense_taxonomy",
        "get_taxonomy_manifest",
        "get_taxonomy_branch",
        "search_taxonomy",
        "resolve_expense_aliases",
        "list_expenses",
        "get_expense",
        "get_expense_analytics",
        "get_expense_dashboard",
        "get_item_price_history",
        "search_known_items",
        "get_personal_basket_index",
        "get_merchant_breakdown",
        "get_nutrition_queue",
        "save_nutrition_result",
        "search_nutrition_lookups",
        "get_nutrition_summary",
        "check_email_processed",
        "check_emails_processed",
        "claim_email_for_processing",
        "record_email_processed",
        "nutrition_lookup_usda",
        "nutrition_lookup_usda_detail",
        "nutrition_lookup_off",
        "create_receipt_draft_from_file",
        "save_expense_draft",
        "correct_confirmed_expense",
        "validate_expense",
        "confirm_expense",
        "delete_expense",
        "get_receipt_download_url",
        "delete_receipt_file",
        "open_expense_tracker",
    } == names
    assert {
        "prepare_receipt_file",
        "get_receipt_attempt_status",
        "commit_receipt_draft",
        "create_receipt_draft",
        "ingest_receipt_file",
        "create_receipt_upload_target",
        "confirm_receipt_upload",
        "open_expense_editor",
        "open_spending_dashboard",
    }.isdisjoint(names)

    for tool in tools:
        assert tool.description and tool.description.startswith("Use this when")
        assert tool.inputSchema is not None
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is not None
        assert tool.annotations.destructiveHint is not None
        assert tool.annotations.idempotentHint is not None
        assert tool.annotations.openWorldHint is not None

    resources = asyncio.run(server.list_resources())
    assert [str(resource.uri) for resource in resources] == [WIDGET_URI]
    assert resources[0].mimeType == WIDGET_MIME_TYPE


def test_external_nutrition_lookup_tools_are_read_only_and_open_world() -> None:
    tools = asyncio.run(create_mcp_server(mcp_settings()).list_tools())
    external_tools = {
        tool.name: tool
        for tool in tools
        if tool.name in {"nutrition_lookup_usda", "nutrition_lookup_usda_detail", "nutrition_lookup_off"}
    }

    assert set(external_tools) == {"nutrition_lookup_usda", "nutrition_lookup_usda_detail", "nutrition_lookup_off"}
    for tool in external_tools.values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is True


@pytest.mark.parametrize("arguments", [{}, {"query": "paneer", "barcode": "0627985001008"}])
def test_off_lookup_requires_exactly_one_of_query_or_barcode(arguments: dict[str, str]) -> None:
    with pytest.raises(Exception, match="exactly one of query or barcode"):
        asyncio.run(create_mcp_server(mcp_settings()).call_tool("nutrition_lookup_off", arguments))


def test_atomic_receipt_tool_is_data_only_with_native_file_metadata() -> None:
    tools = asyncio.run(create_mcp_server(mcp_settings()).list_tools())
    descriptor = next(tool for tool in tools if tool.name == "create_receipt_draft_from_file")

    assert descriptor.meta is not None
    assert descriptor.meta["openai/fileParams"] == ["file"]
    assert "ui" not in descriptor.meta
    assert "openai/outputTemplate" not in descriptor.meta
    assert descriptor.meta["openai/toolInvocation/invoked"] == "Receipt draft saved"
    assert descriptor.description is not None
    assert "never opens UI" in descriptor.description
    assert descriptor.annotations is not None
    assert descriptor.annotations.model_dump() == {
        "title": None,
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    file_schema = descriptor.inputSchema["$defs"]["OpenAIFileInput"]
    assert set(file_schema["properties"]) == {
        "download_url",
        "file_id",
        "mime_type",
        "file_name",
    }
    assert file_schema["required"] == ["download_url", "file_id"]
    assert descriptor.outputSchema is not None
    assert set(descriptor.outputSchema["properties"]) == {
        "expense",
        "receipt_file_id",
        "validation",
        "idempotent_replay",
        "exact_file_duplicate",
        "result_version",
    }


def test_open_tracker_is_the_only_ui_linked_tool() -> None:
    tools = asyncio.run(create_mcp_server(mcp_settings()).list_tools())
    ui_linked_tools = {
        tool.name
        for tool in tools
        if tool.meta
        and ("ui" in tool.meta or "openai/outputTemplate" in tool.meta)
    }

    assert ui_linked_tools == {"open_expense_tracker"}


def test_widget_resource_uses_mcp_apps_mime_type_and_narrow_csp() -> None:
    settings = mcp_settings(
        supabase_url="https://project.supabase.co",
        mcp_widget_connect_domains="https://uploads.example.test",
    )
    resource = asyncio.run(create_mcp_server(settings).list_resources())[0]

    assert str(resource.uri) == WIDGET_URI
    assert resource.mimeType == WIDGET_MIME_TYPE
    assert resource.meta is not None
    assert resource.meta["ui"]["csp"]["connectDomains"] == [
        "https://project.supabase.co",
        "https://uploads.example.test",
    ]


def test_hidden_urls_never_enter_model_visible_content() -> None:
    result = _hidden_result(
        OperationResult(message="ready"),
        "Created a private target.",
        {"dailyExpenseTracker": {"downloadUrl": "https://private.example/signed?secret=1"}},
    )
    visible = str(result.structuredContent) + " " + " ".join(
        block.text for block in result.content if hasattr(block, "text")
    )

    assert "private.example" not in visible
    assert result.meta is not None
    assert "private.example" in result.meta["dailyExpenseTracker"]["downloadUrl"]


def dashboard_fixture() -> ExpenseDashboard:
    return ExpenseDashboard.model_validate(
        {
            "display_name": "Adi",
            "default_currency": "CAD",
            "window": {
                "label": "July",
                "current_start": date(2026, 7, 1),
                "current_end": date(2026, 7, 27),
                "previous_start": date(2026, 6, 1),
                "previous_end": date(2026, 6, 27),
            },
            "totals": [],
            "categories": [],
            "insights": [],
            "recent_transactions": [],
            "needs_review_count": 0,
            "price_changes": [],
        }
    )


def test_open_tracker_defaults_to_overview_and_embeds_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server_module, "user_transaction", lambda _user_id: nullcontext(object()))
    monkeypatch.setattr(
        DashboardRepository,
        "get_dashboard",
        lambda _repository, _request: dashboard_fixture(),
    )

    result = asyncio.run(create_mcp_server(mcp_settings()).call_tool("open_expense_tracker", {}))

    assert isinstance(result, CallToolResult)
    assert result.structuredContent is not None
    assert result.structuredContent["route"] == "/overview"
    assert result.structuredContent["data"]["dashboard"]["display_name"] == "Adi"
    assert result.meta is not None
    assert result.meta["ui"]["resourceUri"] == WIDGET_URI


def test_open_tracker_rejects_unsupported_route() -> None:
    with pytest.raises(Exception, match="Unsupported tracker route"):
        asyncio.run(
            create_mcp_server(mcp_settings()).call_tool(
                "open_expense_tracker",
                {"route": "/not-a-real-screen"},
            )
        )


def test_streamable_http_initialize_is_mounted_at_mcp() -> None:
    server = create_mcp_server(mcp_settings())
    app = server.streamable_http_app()
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "Holy Spend"


def test_fastapi_application_exposes_exact_mcp_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest-fastapi", "version": "1.0"},
                    },
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200


def test_fastapi_application_hides_mcp_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
            response = client.post("/mcp", json={})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404


def test_widget_fallback_html_is_safe_when_build_artifact_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path.name == "index.html" and path.parent.name == "dist":
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    contents = list(asyncio.run(create_mcp_server(mcp_settings()).read_resource(WIDGET_URI)))

    assert "widget is not built" in contents[0].content
