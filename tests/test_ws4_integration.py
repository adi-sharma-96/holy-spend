"""WS4 acceptance fixtures on disposable PostgreSQL with production-shaped grants."""

import asyncio
import html
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import app.db as db
import app.hosted_tracker as hosted
import app.main as main
import app.mcp_server as mcp
from app.config import Settings, get_settings
from app.dashboard import DashboardRepository
from app.errors import ConflictError
from app.models import TransactionItemUpdate
from app.nutrition_repository import NutritionRepository
from app.plugin_models import (
    CoverageInput,
    ExpenseDashboardRequest,
    NutritionResultInput,
    NutritionSummaryRequest,
    ProteinLabel,
    SpendingReviewInput,
)
from app.repositories import TransactionRepository
from app.security import generate_pat, hash_pat
from app.spending import SpendingRepository

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
RUNTIME_URL = os.getenv("TEST_DATABASE_URL")
READER_URL = os.getenv("TEST_TRACKER_READER_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and RUNTIME_URL and READER_URL), reason="Requires disposable WS4 PostgreSQL roles",
)
TODAY = date(2026, 7, 12)
ORIGIN = "https://tracker.example.test"
LEAF = "food_dining.groceries.produce.fruit.apples_pears.apples"


@dataclass(frozen=True)
class Ledger:
    owner: UUID
    other: UUID
    ordinary: UUID
    apple: UUID
    other_transaction: UUID


def transaction(
    conn: Any, owner: UUID, day: date, amount: int, *,
    kind: str = "expense", currency: str = "CAD", status: str = "confirmed",
    merchant: str = "Synthetic market",
) -> UUID:
    row = conn.execute(
        """insert into transactions
           (user_id, transaction_type, source_type, ingestion_method, transaction_date, currency,
            total_amount, status, confirmed_at, merchant_name_raw)
           values (%s, %s, 'manual', 'manual', %s, %s, %s, %s, now(), %s) returning id""",
        (owner, kind, day, currency, amount, status, merchant),
    ).fetchone()
    return cast(UUID, row["id"])


def item(conn: Any, owner: UUID, tx: UUID, amount: int) -> UUID:
    row = conn.execute(
        """insert into transaction_items
           (user_id, transaction_id, raw_name, normalized_name, taxonomy_node_id,
            measured_value, measured_unit, line_total_amount, product_identity_key, field_provenance)
           select %s, %s, 'Synthetic apple', 'Synthetic apple', id, 500, 'g', %s, 'synthetic.apple',
               '{"identity":{"source":"user_confirmed"},"measured_value":{"source":"observed_receipt"}}'::jsonb
           from taxonomy_nodes where stable_key = %s returning id""",
        (owner, tx, amount, LEAF),
    ).fetchone()
    return cast(UUID, row["id"])


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> Iterator[Ledger]:
    assert ADMIN_URL and RUNTIME_URL
    owner, other = uuid4(), uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        for principal in (owner, other):
            admin.execute(
                "insert into auth.users (id, email) values (%s, %s)", (principal, f"{principal}@example.test"),
            )
            admin.execute("insert into profiles (id, default_currency) values (%s, 'CAD')", (principal,))
        ordinary = transaction(admin, owner, TODAY, 6)
        apple = item(admin, owner, ordinary, 6)
        other_transaction = transaction(admin, other, TODAY, 9999, merchant="Separate owner")
    with ConnectionPool(conninfo=RUNTIME_URL, kwargs={"row_factory": dict_row}, min_size=1) as pool:
        monkeypatch.setattr(db, "get_pool", lambda: pool)
        monkeypatch.setattr(hosted, "local_today", lambda _settings: TODAY)
        monkeypatch.setattr(mcp, "local_today", lambda _settings: TODAY)
        with db.user_transaction(owner) as conn:
            nutrition = NutritionRepository(conn, owner)
            lookup = nutrition.get_queue(10).items[0]
            nutrition.save_result(NutritionResultInput(
                item_id=lookup.id, matched=True, product_name="Synthetic apple",
                source="synthetic label", source_ref="synthetic:fixture", protein_label=ProteinLabel(
                    basis="per_100g", protein_g=Decimal(20), product_identity_key="synthetic.apple",
                ),
            ))
        try:
            yield Ledger(owner, other, ordinary, apple, other_transaction)
        finally:
            with psycopg.connect(ADMIN_URL) as admin:
                admin.execute("delete from auth.users where id in (%s, %s)", (owner, other))


def test_spending_windows_wallet_exclusions_and_audited_classifications(ledger: Ledger) -> None:
    owner = ledger.owner
    with db.user_transaction(owner) as conn:
        ordinary = ledger.ordinary
        prior = transaction(conn, owner, date(2026, 6, 11), 2)
        exceptional = transaction(conn, owner, TODAY, 1000)
        refund = transaction(conn, owner, TODAY, 2, kind="refund")
        transaction(conn, owner, TODAY, 8, currency="USD")
        transaction(conn, owner, TODAY, 999, status="draft")
        transaction(conn, owner, TODAY, 999, kind="transfer")
        transaction(conn, owner, date(2026, 6, 25), 777)
        for source in ("first wallet entry", "duplicate wallet entry"):
            conn.execute(
                """insert into receipt_document_events (user_id, transaction_id, source_key, event_kind,
                amount, currency) values (%s, %s, %s, 'wallet_use', 8000, 'CAD')""",
                (owner, exceptional, source),
            )
        dashboard = DashboardRepository(conn, owner, today=lambda: TODAY)
        request = ExpenseDashboardRequest(price_change_limit=0)
        result = dashboard.get_dashboard(request)
        cad, usd = result.totals
        assert cad.current_amount == Decimal(1004) and cad.previous_amount == Decimal(2)
        assert cad.delta_percent is None
        assert cad.comparison and cad.comparison.reasons == ["coverage_unknown"]
        assert usd.current_amount == Decimal(8) and usd.delta_percent is None

        repo = SpendingRepository(conn, owner)
        repo.declare(CoverageInput(
            currency="CAD", start_date=date(2026, 6, 1), kind="tracking", reason="Synthetic tracking",
        ))
        rows = repo.transactions(date(2026, 6, 1), TODAY, "CAD", 100, 0)
        assert all(row.recurrence == [] for row in rows)
        rows_by_id = {row.id: row for row in rows}
        assert ledger.other_transaction not in rows_by_id
        for transaction_id in (ordinary, prior, exceptional, refund):
            row = rows_by_id[transaction_id]
            payload = SpendingReviewInput(
                transaction_id=transaction_id, expected_revision=row.revision, expected_review_id=None,
                classification="exceptional" if transaction_id == exceptional else "ordinary",
                reason="Owner reviewed synthetic transaction", explicit_approval=True,
            )
            reviewed = repo.classify(payload)
            assert reviewed.transaction_id == transaction_id
            with pytest.raises(ConflictError, match="classification changed"):
                repo.classify(payload)
        cad = dashboard.get_dashboard(request).totals[0]
        assert cad.delta_percent == Decimal("50100.0")
        assert cad.ordinary_comparison and cad.ordinary_comparison.delta_percent == Decimal("100.0")
        assert [row.current_amount for row in cad.buckets] == [Decimal(4), Decimal(1000), Decimal(0)]
        assert [row.current_count for row in cad.buckets] == [2, 1, 0]
        conn.execute("update transactions set total_amount=7 where id=%s", (ordinary,))
        revised = dashboard.get_dashboard(request).totals[0]
        assert revised.current_amount == Decimal(1005)
        assert revised.buckets[2].current_amount == Decimal(7)
        assert revised.ordinary_comparison and "unreviewed_spend" in revised.ordinary_comparison.reasons


def test_protein_evidence_repeats_corrections_currency_and_refund_allocation(ledger: Ledger) -> None:
    owner = ledger.owner
    with db.user_transaction(owner) as conn:
        second = transaction(conn, owner, TODAY, 10, status="draft")
        second_item = item(conn, owner, second, 10)
        usd_transaction = transaction(conn, owner, TODAY, 4, currency="USD", status="draft")
        item(conn, owner, usd_transaction, 4)
        conn.execute("update transactions set status='confirmed' where id in (%s, %s)", (second, usd_transaction))
        nutrition = NutritionRepository(conn, owner)
        cad = NutritionSummaryRequest(currency="CAD")
        usd = NutritionSummaryRequest(currency="USD")
        summary = nutrition.get_summary(cad, today=lambda: TODAY).protein_cost
        assert summary and summary.groups[0].eligible_count == 2
        assert summary.groups[0].cost_per_100g == Decimal("8.00")
        summary = nutrition.get_summary(usd, today=lambda: TODAY).protein_cost
        assert summary and summary.groups[0].cost_per_100g == Decimal("4.00")

        TransactionRepository(conn, owner).update_item(
            second, second_item,
            TransactionItemUpdate(line_total_amount=Decimal(14), correction_reason="Review amount"),
        )
        summary = nutrition.get_summary(cad, today=lambda: TODAY).protein_cost
        assert summary and summary.groups[0].cost_per_100g == Decimal("6.00")
        assert summary.reasons == {"unverified_measurement": 1}
        assert summary.excluded_spend == Decimal(14)
        conn.execute(
            """insert into receipt_document_events (user_id, transaction_id, source_key, event_kind, amount, currency)
            values (%s, %s, 'synthetic partial refund', 'purchase_refund', 3, 'CAD')""",
            (owner, second),
        )
        summary = nutrition.get_summary(cad, today=lambda: TODAY).protein_cost
        assert summary and summary.reasons == {"refund_allocation_unknown": 1}
        assert summary.groups[0].cost_per_100g == Decimal("6.00")
        assert summary.excluded_spend == Decimal(14)


def settings_for(ledger: Ledger, origin: str = ORIGIN, **overrides: Any) -> Settings:
    return Settings.model_validate({
        "owner_user_id": ledger.owner, "hosted_tracker_origin": origin, "database_url": RUNTIME_URL,
        **overrides,
    })


def test_protein_cost_excludes_discount_adjustments_missing_from_line_fields(ledger: Ledger) -> None:
    with db.user_transaction(ledger.owner) as conn:
        tx = transaction(conn, ledger.owner, TODAY, 4, status="draft")
        product = item(conn, ledger.owner, tx, 6)
        conn.execute(
            """insert into transaction_adjustments
               (user_id, transaction_id, item_id, type, amount, affects_total)
               values (%s, %s, %s, 'coupon', 2, true)""", (ledger.owner, tx, product),
        )
        conn.execute("update transactions set status='confirmed' where id=%s", (tx,))
        summary = NutritionRepository(conn, ledger.owner).get_summary(
            NutritionSummaryRequest(currency="CAD"), today=lambda: TODAY,
        ).protein_cost
        assert summary is not None
        assert summary.reasons == {"discount_allocation_unknown": 1}
        assert summary.groups[0].eligible_count == 1


def exchange(client: Any, token: str, origin: str = ORIGIN) -> httpx.Response:
    return cast(httpx.Response, client.post(
        "/tracker/session/exchange", content=token,
        headers={"Origin": origin, "Content-Type": "text/plain;charset=UTF-8"},
    ))


def mint(settings: Settings, owner: UUID) -> str:
    return hosted.mint_tracker_launch(owner, settings).split("#", 1)[1]


def test_tracker_launch_cannot_expire_during_lock_wait(ledger: Ledger) -> None:
    assert ADMIN_URL
    token = mint(settings_for(ledger), ledger.owner)
    digest = hosted._digest(token)
    assert digest is not None
    with psycopg.connect(ADMIN_URL, row_factory=dict_row, autocommit=True) as admin:
        row = admin.execute(
            """update tracker_launch_credentials set expires_at = clock_timestamp() + interval '3 seconds'
               where digest = %s returning expires_at""", (digest,),
        ).fetchone()
        assert row is not None
        with ThreadPoolExecutor(max_workers=1) as executor:
            with admin.transaction():
                admin.execute("select digest from tracker_launch_credentials where digest = %s for update", (digest,))
                pending = executor.submit(hosted._redeem, digest, None, ledger.owner, ORIGIN)
                waiting = False
                for _ in range(300):
                    admin.execute("select pg_stat_clear_snapshot()")
                    activity = admin.execute(
                        """select exists(select from pg_stat_activity where datname=current_database()
                           and wait_event_type='Lock'
                           and query like 'delete from tracker_launch_credentials%') as waiting""",
                    ).fetchone()
                    waiting = bool(activity and activity["waiting"])
                    if waiting:
                        break
                    time.sleep(0.01)
                assert waiting, "Redemption did not reach the row lock"
                for _ in range(500):
                    clock = admin.execute("select clock_timestamp() >= %s as expired", (row["expires_at"],)).fetchone()
                    if clock and clock["expired"]:
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("Local database clock did not reach expiry")
            with pytest.raises(HTTPException) as rejected:
                pending.result(timeout=10)
            assert rejected.value.status_code == 401
        count = admin.execute(
            "select count(*) as n from tracker_browser_sessions where user_id=%s", (ledger.owner,),
        ).fetchone()
        assert count is not None and count["n"] == 0
        assert admin.execute(
            "select digest from tracker_launch_credentials where digest=%s", (digest,),
        ).fetchone() is not None


def reader_app(ledger: Ledger) -> FastAPI:
    settings = settings_for(ledger, hosted_tracker_read_database_url=READER_URL)
    app = FastAPI()
    hosted.install_hosted_tracker(app, settings)
    return app


def test_reader_grants_and_owner_context(ledger: Ledger) -> None:
    assert READER_URL
    with psycopg.connect(READER_URL, row_factory=dict_row) as conn:
        row = conn.execute("""
            select current_user as role, current_setting('transaction_read_only') as readonly,
                   has_table_privilege(current_user, 'transactions', 'insert,update,delete') as writes,
                   has_table_privilege(current_user, 'tracker_launch_credentials', 'select') as can_read_launch,
                   has_table_privilege(current_user, 'tracker_browser_sessions', 'insert,update,delete')
                       as session_writes,
                   has_function_privilege(current_user, 'app.authenticate_pat(text)', 'execute') as can_authenticate
            """).fetchone()
        assert row == {"role": "expense_tracker_reader", "readonly": "on", "writes": False,
                       "can_read_launch": False, "session_writes": False, "can_authenticate": False}
        conn.execute("select set_config('app.current_user_id', %s, true)", (str(ledger.owner),))
        assert conn.execute("select id from transactions where id=%s", (ledger.other_transaction,)).fetchone() is None
        assert conn.execute("select id from transactions where id=%s", (ledger.ordinary,)).fetchone()


def test_tracker_actual_routes_atomic_exchange_redaction_and_logout(ledger: Ledger) -> None:
    assert ADMIN_URL
    app = reader_app(ledger)
    settings = settings_for(ledger)
    admin_row = """
        update {table} set expires_at = clock_timestamp() - interval '1 second'
        where user_id = %s and digest = %s
    """
    with TestClient(app, base_url=ORIGIN) as client:
        token = mint(settings, ledger.owner)
        assert client.get("/tracker/read/dashboard").status_code == 401
        assert client.get("/tracker/session/exchange").status_code == 405
        page = client.get("/tracker")
        assert page.status_code == 200
        assert token not in page.text and page.headers["Referrer-Policy"] == "no-referrer"
        assert "no-store" in page.headers["Cache-Control"]
        assert client.get("/tracker", headers={"Host": "other.example.test"}).status_code == 403
        assert exchange(client, token, "https://other.example.test").status_code == 403
        wrong_audience = mint(settings_for(ledger, "https://other.example.test"), ledger.owner)
        assert exchange(client, wrong_audience).status_code == 401
        wrong_owner = settings.model_copy(update={"owner_user_id": ledger.other})
        assert exchange(client, mint(wrong_owner, ledger.other)).status_code == 401
        expired = mint(settings, ledger.owner)
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(admin_row.format(table="tracker_launch_credentials"), (ledger.owner, hosted._digest(expired)))
        assert exchange(client, expired).status_code == 401

        invalid = client.post(
            "/tracker/session/exchange", content=token + " surplus", headers={
                "Origin": ORIGIN, "Content-Type": "text/plain",
            },
        )
        assert invalid.status_code == 400 and token not in invalid.text
        assert client.get("/tracker/read/nutrition", params={"currency": token}).status_code == 401

    def attempt() -> tuple[int, str | None]:
        with TestClient(app, base_url=ORIGIN) as candidate:
            response = exchange(candidate, token)
            return response.status_code, response.cookies.get(hosted.COOKIE)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result() for future in [executor.submit(attempt) for _ in range(2)]]
    assert sorted(status for status, _ in outcomes) == [204, 401]
    session = next(cookie for status, cookie in outcomes if status == 204)
    assert session and session != token
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set(hosted.COOKIE, session)
        assert client.get(f"/tracker/read/transactions/{ledger.other_transaction}").status_code == 404
        assert client.get(f"/tracker/read/transactions/{ledger.ordinary}").status_code == 200
        nutr = client.get("/tracker/read/nutrition", params={"currency": "CAD"})
        assert nutr.status_code == 200
        assert nutr.json()["protein_cost"]["groups"][0]["cost_per_100g"] == "6.00"
        for path in ("dashboard", "transactions", "basket?currency=CAD", "merchants?currency=CAD",
                     "categories?currency=CAD&parent=food_dining&level=3", "spending?currency=CAD",
                     "prices?identity_key=product:synthetic.apple&currency=CAD"):
            assert client.get(f"/tracker/read/{path}").status_code == 200, path
        mutation = client.patch(f"/tracker/read/transactions/{ledger.ordinary}", json={"total_amount": 12})
        assert mutation.status_code == 405
        assert client.post("/tracker/session/logout", headers={"Origin": "https://other.test"}).status_code == 403
        assert exchange(client, token).status_code == 401

        # A successful fresh exchange replaces the cookie and revokes its predecessor.
        response = exchange(client, mint(settings, ledger.owner))
        assert response.status_code == 204
        new_session = response.cookies.get(hosted.COOKIE)
        assert new_session and new_session != session
        assert all(attribute in response.headers["Set-Cookie"] for attribute in (
            "HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=1800",
        ))
        assert "Domain=" not in response.headers["Set-Cookie"]
        with TestClient(app, base_url=ORIGIN, cookies={hosted.COOKIE: session}) as old:
            assert old.get("/tracker/read/dashboard").status_code == 401

        client.cookies.clear()
        client.cookies.set(hosted.COOKIE, new_session)
        assert client.post("/tracker/session/logout", headers={"Origin": ORIGIN}).status_code == 204
        with TestClient(app, base_url=ORIGIN, cookies={hosted.COOKIE: new_session}) as replay:
            assert replay.get("/tracker/read/dashboard").status_code == 401

        response = exchange(client, mint(settings, ledger.owner))
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(admin_row.format(table="tracker_browser_sessions"),
                          (ledger.owner, hosted._digest(response.cookies.get(hosted.COOKIE))))
        assert client.get("/tracker/read/dashboard").status_code == 401


def make_tls(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    openssl = shutil.which("openssl")
    assert openssl is not None, "OpenSSL is required for the local HTTPS fixture"
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )
    return cert, key


def listener() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


def start_server(app: FastAPI, sock: socket.socket, tls: tuple[Path, Path] | None = None) -> tuple[Any, Any]:
    server = uvicorn.Server(uvicorn.Config(
        app, log_config=None, access_log=True,
        ssl_certfile=str(tls[0]) if tls else None, ssl_keyfile=str(tls[1]) if tls else None,
    ))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(150):
        if server.started:
            return server, thread
        time.sleep(0.05)
    raise AssertionError("Disposable HTTP server did not start")


async def call_mcp(origin: str, pat: str, name: str, arguments: dict[str, Any]) -> Any:
    async with (
        httpx.AsyncClient(verify=False, headers={"Authorization": f"Bearer {pat}"}) as client,
        streamable_http_client(f"{origin}/mcp", http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments=arguments)
    assert not result.isError, f"Test MCP tool failed: {name}"
    return result


def test_real_https_mcp_browser_embedded_and_logout(
    ledger: Ledger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    assert ADMIN_URL and hosted.WIDGET_BUILD.exists(), "Build the widget before the hosted browser test"
    browser_api = pytest.importorskip("playwright.sync_api")
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    servers = []
    try:
        with listener() as upstream, listener() as web:
            origin = f"https://127.0.0.1:{web.getsockname()[1]}"
            upstream_url = f"http://127.0.0.1:{upstream.getsockname()[1]}/mcp"
            private = settings_for(ledger, origin, mcp_enabled=True, mcp_allowed_hosts="127.0.0.1:*")
            monkeypatch.setattr(main, "get_settings", lambda: private)
            servers.append(start_server(main.create_app(), upstream))
            gateway = settings_for(
                ledger, origin, auth_mode="pat", mcp_gateway_upstream_url=upstream_url,
                hosted_tracker_read_database_url=READER_URL,
            )
            monkeypatch.setattr(main, "get_settings", lambda: gateway)
            app = main.create_app()
            app.dependency_overrides[get_settings] = lambda: gateway
            servers.append(start_server(app, web, make_tls(tmp_path)))
            pat, other_pat = generate_pat(), generate_pat()
            with psycopg.connect(ADMIN_URL) as admin:
                for principal, secret in ((ledger.owner, pat), (ledger.other, other_pat)):
                    admin.execute(
                        "insert into personal_access_tokens (user_id, token_hash, name, scopes) values (%s,%s,%s,%s)",
                        (principal, hash_pat(secret, gateway), "synthetic disposable", ["*"]),
                    )
            with httpx.Client(verify=False) as client:
                assert client.post(f"{origin}/mcp").status_code == 401
                assert client.post(f"{origin}/mcp", headers={"Authorization": f"Bearer {other_pat}"}).status_code == 403
            dashboard = asyncio.run(call_mcp(origin, pat, "get_expense_dashboard", {}))
            assert dashboard.structuredContent["totals"][0]["delta_percent"] is None
            assert "coverage_unknown" in dashboard.structuredContent["totals"][0]["comparison"]["reasons"]
            nutrition = asyncio.run(call_mcp(origin, pat, "get_nutrition_summary", {"request": {"currency": "CAD"}}))
            assert nutrition.structuredContent["protein_cost"]["groups"][0]["cost_per_100g"] == "6.00"
            widget = asyncio.run(call_mcp(origin, pat, "open_expense_tracker", {}))
            assert widget.structuredContent["route"] == "/overview"
            assert widget.meta["ui"]["resourceUri"] == mcp.WIDGET_URI
            launch = asyncio.run(call_mcp(origin, pat, "open_hosted_tracker", {"explicit_approval": True}))
            url = launch.content[0].text.split("(", 1)[1].split(")", 1)[0]
            token = url.split("#", 1)[1]

            with browser_api.sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=os.getenv("TEST_TRACKER_BROWSER_CHANNEL") or None)
                context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 800})
                page = context.new_page()
                requests: list[str] = []
                page.on("request", lambda request: requests.append(request.url))
                page.goto(url)
                page.get_by_role("heading", name="Open your tracker").wait_for()
                assert page.url == f"{origin}/tracker"
                assert context.cookies() == []
                assert not any("/session/exchange" in request for request in requests)

                page.get_by_role("button", name="Open tracker", exact=True).click()
                page.get_by_role("tab", name="Overview").wait_for()
                assert page.get_by_text("Tracking coverage is incomplete or undeclared.", exact=False).count() > 0
                page.get_by_role("button", name="Included transactions").click()
                page.get_by_text("Recurrence unknown", exact=False).wait_for()
                page.get_by_role("button", name="Close", exact=True).click()
                page.get_by_role("tab", name="Activity", exact=False).click()
                page.get_by_text("Synthetic market", exact=True).wait_for()
                assert page.get_by_role("button", name="Add", exact=True).count() == 0
                page.get_by_text("Synthetic market", exact=True).click()
                page.get_by_label("Transaction details", exact=True).wait_for()
                assert page.get_by_role("button", name="More actions").count() == 0
                page.get_by_role("button", name="Close transaction details").click()

                page.set_viewport_size({"width": 375, "height": 812})
                page.get_by_role("tab", name="Nutrition", exact=False).click()
                page.get_by_role("heading", name="Cost per 100 g of purchased protein").wait_for()
                assert page.get_by_text("$6.00 per 100 g", exact=False).count() > 0
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert page.evaluate("document.cookie") == ""
                assert page.evaluate("localStorage.length + sessionStorage.length") == 0
                assert not any(token in request for request in requests)
                invalid_url = f"{origin}/tracker?unexpected={token}"
                assert context.request.get(invalid_url).status == 400
                assert "/tracker/session/exchange" in caplog.text
                assert token not in caplog.text

                page.get_by_role("button", name="Sign out").click()
                page.get_by_role("heading", name="Signed out").wait_for()
                assert context.cookies() == []
                assert context.request.get(f"{origin}/tracker/read/dashboard").status == 401
                page.goto(url)
                page.get_by_role("button", name="Open tracker", exact=True).click()
                page.get_by_role("heading", name="Open a fresh tracker link").wait_for()
                assert page.url == f"{origin}/tracker"

                frame_page = context.new_page()
                bootstrap = json.dumps({"displayMode": "inline", "toolOutput": widget.structuredContent})
                srcdoc = hosted.WIDGET_BUILD.read_text(encoding="utf-8").replace(
                    "</head>", f"<script>window.openai={bootstrap};</script></head>", 1,
                )
                frame_page.set_content(f'<iframe title="Embedded tracker" srcdoc="{html.escape(srcdoc)}"></iframe>')
                embedded = frame_page.frame_locator("iframe")
                embedded.get_by_role("heading", name="Good to see you, there.").wait_for()
                embedded.get_by_role("button", name="Add expense").wait_for()
                embedded.get_by_text("Tracking coverage is incomplete or undeclared.", exact=False).wait_for()
                browser.close()
    finally:
        for server, thread in reversed(servers):
            server.should_exit = True
            thread.join(timeout=10)
