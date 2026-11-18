"""One-use browser launch and the hosted tracker's explicit read surface."""

import base64
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Iterator
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from psycopg.rows import dict_row

from app.analytics import AnalyticsQueryCompiler, AnalyticsRepository
from app.clock import local_today
from app.config import Settings
from app.dashboard import DashboardRepository, dashboard_window
from app.db import user_transaction
from app.errors import NotFoundError
from app.models import (
    AnalyticsFilters,
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    TransactionListFilters,
    TransactionListResponse,
)
from app.nutrition_repository import NutritionRepository
from app.plugin_models import (
    DashboardPeriod,
    ExpenseDashboard,
    ExpenseDashboardRequest,
    ExpenseSnapshot,
    ItemPriceHistory,
    ItemPriceHistoryRequest,
    MerchantBreakdownRequest,
    MerchantBreakdownResponse,
    NutritionSummary,
    NutritionSummaryRequest,
    PersonalBasketIndex,
    PersonalBasketRequest,
    SpendingTransaction,
)
from app.repositories import TransactionRepository
from app.spending import SpendingRepository

LOGGER = logging.getLogger(__name__)
TRACKER_PATH = "/tracker"
COOKIE = "__Host-holy-spend-tracker"
SCOPE = "tracker:read"
LAUNCH_SECONDS = 120
SESSION_SECONDS = 1800
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
WIDGET_BUILD = Path(__file__).resolve().parent.parent / "widget" / "dist" / "index.html"


class TrackerAccessLogFilter(logging.Filter):
    """Keep tracker URL parameters out of Uvicorn's access records."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2].partition("?")[0]
            if path == TRACKER_PATH or path.startswith(TRACKER_PATH + "/"):
                record.args = (*args[:2], path, *args[3:])
        return True


TRACKER_LOG_FILTER = TrackerAccessLogFilter()


def tracker_origin(settings: Settings) -> str:
    return str(settings.hosted_tracker_origin).removesuffix("/")


def _digest(value: str | None) -> bytes | None:
    if value is None or TOKEN_PATTERN.fullmatch(value) is None:
        return None
    return sha256(value.encode("ascii")).digest()


def mint_tracker_launch(owner_id: UUID, settings: Settings) -> str:
    if settings.hosted_tracker_origin is None or owner_id != settings.owner_user_id:
        raise ValueError("Hosted tracker is unavailable")
    token = secrets.token_urlsafe(32)
    audience = tracker_origin(settings)
    with user_transaction(owner_id) as conn:
        for table in ("tracker_launch_credentials", "tracker_browser_sessions"):
            conn.execute(
                f"delete from {table} where user_id = %s and expires_at <= clock_timestamp()",
                (owner_id,),
            )
        conn.execute(
            """insert into tracker_launch_credentials (digest, user_id, audience, scope, expires_at)
            values (%s, %s, %s, %s, clock_timestamp() + make_interval(secs => %s))""",
            (_digest(token), owner_id, audience, SCOPE, LAUNCH_SECONDS),
        )
    return f"{audience}{TRACKER_PATH}#{token}"


def _revoke(conn: Any, digest: bytes | None, owner_id: UUID, audience: str) -> None:
    if digest is not None:
        conn.execute(
            """delete from tracker_browser_sessions where digest = %s
               and user_id = %s and audience = %s and scope = %s""",
            (digest, owner_id, audience, SCOPE),
        )


def _redeem(
    digest: bytes, previous: bytes | None, owner_id: UUID, audience: str,
) -> str:
    session = secrets.token_urlsafe(32)
    with user_transaction(owner_id) as conn:
        credential = conn.execute(
            """delete from tracker_launch_credentials where digest = %s and user_id = %s
               and audience = %s and scope = %s and expires_at > clock_timestamp()
               returning user_id, expires_at""",
            (digest, owner_id, audience, SCOPE),
        ).fetchone()
        if credential is None:
            raise HTTPException(status_code=401, detail="Open a fresh tracker link from your connected chat.")
        # DELETE can wait on a lock after evaluating its WHERE predicate. Check
        # the database clock again once this transaction actually owns the row.
        fresh = conn.execute(
            "select clock_timestamp() < %s as valid", (credential["expires_at"],),
        ).fetchone()
        if fresh is None or not fresh["valid"]:
            raise HTTPException(status_code=401, detail="Open a fresh tracker link from your connected chat.")
        _revoke(conn, previous, owner_id, audience)
        conn.execute(
            """insert into tracker_browser_sessions (digest, user_id, audience, scope, expires_at)
            values (%s, %s, %s, %s, clock_timestamp() + make_interval(secs => %s))""",
            (_digest(session), owner_id, audience, SCOPE, SESSION_SECONDS),
        )
    return session


def _build_csp(html: str) -> str:
    hashes: dict[str, str] = {}
    for tag in ("script", "style"):
        contents = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.DOTALL | re.IGNORECASE)
        if not contents:
            raise ValueError("Tracker bundle must inline its JavaScript and styles")
        hashes[tag] = " ".join(
            f"'sha256-{base64.b64encode(sha256(content.encode('utf-8')).digest()).decode('ascii')}'"
            for content in contents
        )
    return (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; "
        f"script-src {hashes['script']}; style-src {hashes['style']}; "
        "style-src-attr 'unsafe-inline'; connect-src 'self'; img-src data:; font-src data:"
    )


def install_hosted_tracker(app: FastAPI, settings: Settings) -> None:
    if settings.hosted_tracker_read_database_url is None or settings.owner_user_id is None:
        return
    logging.getLogger("uvicorn.access").addFilter(TRACKER_LOG_FILTER)
    owner_id = settings.owner_user_id
    db_url = settings.hosted_tracker_read_database_url.get_secret_value()
    audience = tracker_origin(settings)
    # The gateway container includes the same inlined build as the MCP service.
    html = WIDGET_BUILD.read_text(encoding="utf-8") if WIDGET_BUILD.is_file() else None
    csp = _build_csp(html) if html else "default-src 'none'; frame-ancestors 'none'"
    router = APIRouter(prefix=TRACKER_PATH, include_in_schema=False)

    @app.middleware("http")
    async def tracker_response(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path != TRACKER_PATH and not path.startswith(f"{TRACKER_PATH}/"):
            return await call_next(request)
        response: Response
        origin = request.headers.get("origin")
        request_origin = f"{request.url.scheme}://{request.url.netloc}"
        if request_origin != audience or (origin is not None and origin != audience):
            response = JSONResponse({"detail": "Tracker origin mismatch"}, status_code=403)
        elif request.method == "POST" and origin != audience:
            response = JSONResponse({"detail": "Tracker origin required"}, status_code=403)
        elif path in {TRACKER_PATH, TRACKER_PATH + "/"} and request.url.query:
            response = JSONResponse({"detail": "Open a fresh tracker link from your chat."}, status_code=400)
        else:
            try:
                response = await call_next(request)
                if response.status_code == 422:
                    response = JSONResponse({"detail": "Invalid tracker request"}, status_code=422)
            except Exception as error:
                LOGGER.warning("Hosted tracker request failed (%s)", type(error).__name__)
                response = JSONResponse({"detail": "Tracker is temporarily unavailable"}, status_code=503)
        response.headers.update({
            "Cache-Control": "no-store, private",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Content-Security-Policy": csp,
        })
        return response

    @router.get("")
    def tracker_page() -> Response:
        if html is None:
            return HTMLResponse("The tracker build is unavailable.", status_code=503)
        return HTMLResponse(html)

    @router.post("/session/exchange")
    async def exchange(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/plain":
            raise HTTPException(status_code=400, detail="Invalid launch request")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 43:
                raise HTTPException(status_code=400, detail="Invalid launch request")
            body.extend(chunk)
        digest = _digest(body.decode("ascii", errors="replace"))
        if digest is None:
            raise HTTPException(status_code=400, detail="Invalid launch request")
        session = await run_in_threadpool(_redeem, digest, _digest(request.cookies.get(COOKIE)), owner_id, audience)
        response = Response(status_code=204)
        response.set_cookie(
            COOKIE, session, max_age=SESSION_SECONDS, path="/", secure=True, httponly=True, samesite="strict",
        )
        return response

    @router.post("/session/logout")
    def logout(request: Request) -> Response:
        digest = _digest(request.cookies.get(COOKIE))
        if digest is not None:
            with user_transaction(owner_id) as conn:
                _revoke(conn, digest, owner_id, audience)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return response

    def read_connection(request: Request) -> Iterator[Any]:
        digest = _digest(request.cookies.get(COOKIE))
        if digest is None:
            raise HTTPException(status_code=401, detail="Tracker session expired")
        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=5) as conn, conn.transaction():
            conn.execute("set transaction isolation level repeatable read read only")
            role = conn.execute("select current_user as name").fetchone()
            if role is None or role["name"] != "expense_tracker_reader":
                raise RuntimeError("Tracker reader is misconfigured")
            conn.execute("set local statement_timeout = '10s'")
            conn.execute("select set_config('app.current_user_id', %s, true)", (str(owner_id),))
            session = conn.execute(
                """select user_id from tracker_browser_sessions where digest = %s and user_id = %s
                   and audience = %s and scope = %s and expires_at > clock_timestamp()""",
                (digest, owner_id, audience, SCOPE),
            ).fetchone()
            if session is None:
                raise HTTPException(status_code=401, detail="Tracker session expired")
            yield conn

    read = Depends(read_connection)

    def dashboard_repo(conn: Any) -> DashboardRepository:
        return DashboardRepository(
            conn, owner_id, today=lambda: local_today(settings), fallback_currency=settings.supported_currencies[0],
        )

    @router.get("/read/dashboard")
    def dashboard(request: Annotated[ExpenseDashboardRequest, Query()], conn: Any = read) -> ExpenseDashboard:
        return dashboard_repo(conn).get_dashboard(request)

    @router.get("/read/nutrition")
    def nutrition(request: Annotated[NutritionSummaryRequest, Query()], conn: Any = read) -> NutritionSummary:
        return NutritionRepository(conn, owner_id).get_summary(request, today=lambda: local_today(settings))

    @router.get("/read/transactions")
    def transactions(request: Annotated[TransactionListFilters, Query()], conn: Any = read) -> TransactionListResponse:
        return TransactionRepository(conn, owner_id).list_transactions(request)

    @router.get("/read/transactions/{transaction_id}")
    def expense(transaction_id: UUID, conn: Any = read) -> ExpenseSnapshot:
        try:
            transaction = TransactionRepository(conn, owner_id).get_transaction(transaction_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Transaction not found") from None
        return ExpenseSnapshot(transaction=transaction)

    @router.get("/read/merchants")
    def merchants(request: Annotated[MerchantBreakdownRequest, Query()], conn: Any = read) -> MerchantBreakdownResponse:
        return dashboard_repo(conn).get_merchant_breakdown(request)

    @router.get("/read/basket")
    def basket(request: Annotated[PersonalBasketRequest, Query()], conn: Any = read) -> PersonalBasketIndex:
        return dashboard_repo(conn).get_personal_basket(request)

    @router.get("/read/prices")
    def prices(request: Annotated[ItemPriceHistoryRequest, Query()], conn: Any = read) -> ItemPriceHistory:
        return dashboard_repo(conn).get_item_price_history(request)

    @router.get("/read/spending")
    def spending(
        currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
        period: DashboardPeriod = DashboardPeriod.MONTH,
        interval: Literal["current", "previous"] = "current",
        offset: Annotated[int, Query(ge=0)] = 0,
        conn: Any = read,
    ) -> list[SpendingTransaction]:
        window = dashboard_window(period, local_today(settings))
        start, end = (
            (window.current_start, window.current_end) if interval == "current"
            else (window.previous_start, window.previous_end)
        )
        return SpendingRepository(conn, owner_id).transactions(start, end, currency, 50, offset)

    @router.get("/read/categories")
    def categories(
        currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
        parent: Annotated[str, Query(min_length=1, max_length=512)],
        level: Annotated[int, Query(ge=2, le=6)],
        period: DashboardPeriod = DashboardPeriod.MONTH,
        conn: Any = read,
    ) -> AnalyticsQueryResponse:
        window = dashboard_window(period, local_today(settings))
        filters = AnalyticsFilters(
            start_date=window.current_start, end_date=window.current_end, currency=currency, taxonomy_node_key=parent,
        )
        query = AnalyticsQueryRequest.model_validate({
            "metrics": ["total_spend"], "group_by": ["category"], "taxonomy_rollup_level": level, "filters": filters,
        })
        return AnalyticsRepository(conn, owner_id, AnalyticsQueryCompiler()).query(query)

    app.include_router(router)
