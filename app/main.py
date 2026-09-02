from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analytics import AnalyticsQueryCompiler, AnalyticsRepository
from app.application import ExpenseApplicationService
from app.clock import local_today
from app.config import Settings, get_settings
from app.dependencies import RequestContext, get_request_context
from app.errors import (
    ConflictError,
    InvalidUploadError,
    NotFoundError,
    StorageConfigurationError,
    StorageObjectNotFoundError,
    StorageOperationError,
    UploadRateLimitError,
    ValidationReferenceError,
)
from app.mcp_gateway import build_gateway_router, new_upstream_client
from app.mcp_server import create_mcp_server
from app.models import (
    AliasResolveRequest,
    AliasResolveResponse,
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    Category,
    HealthResponse,
    ReceiptFileDownloadUrlResponse,
    TaxonomyBranch,
    TaxonomyManifest,
    TaxonomyResponse,
    TaxonomySearchResponse,
    Theme,
    TransactionAdjustment,
    TransactionAdjustmentCreate,
    TransactionAdjustmentUpdate,
    TransactionDetail,
    TransactionDraftCreate,
    TransactionItem,
    TransactionItemCreate,
    TransactionItemUpdate,
    TransactionListFilters,
    TransactionListResponse,
    TransactionPatch,
    TransactionType,
    ValidationResponse,
)
from app.oauth_provider import build_oauth_routes
from app.object_storage import ObjectStorage, UploadRateLimiter
from app.receipt_files import ReceiptFileService, ReceiptRepository
from app.repositories import TaxonomyRepository, TransactionRepository
from app.security import require_scope
from app.storage_dependencies import get_object_storage, get_upload_rate_limiter


def translate_error(error: Exception) -> HTTPException:
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, ValidationReferenceError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    if isinstance(error, InvalidUploadError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    if isinstance(error, StorageConfigurationError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, StorageObjectNotFoundError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, StorageOperationError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    if isinstance(error, UploadRateLimitError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error")


def create_app() -> FastAPI:
    # Deployed on both api (gateway) and mcp (server) - which role this
    # process takes is decided entirely by settings.
    settings = get_settings()
    mcp_server = create_mcp_server(settings) if settings.mcp_enabled else None
    mcp_asgi = mcp_server.streamable_http_app() if mcp_server is not None else None
    gateway_upstream_url = (
        str(settings.mcp_gateway_upstream_url) if settings.mcp_gateway_upstream_url is not None else None
    )
    gateway_client = new_upstream_client() if gateway_upstream_url is not None else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # mcp_server and gateway_client are never both set: Settings rejects
        # MCP_ENABLED and MCP_GATEWAY_UPSTREAM_URL together.
        if gateway_client is not None:
            try:
                yield
            finally:
                await gateway_client.aclose()
            return
        if mcp_server is None:
            yield
            return
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Holy Spend API",
        version="0.6.0",
        description="Self-hosted personal spending and receipt intelligence backend.",
        lifespan=lifespan,
    )

    # Browser-enforced CORS for the public gateway's /mcp, /authorize, and /token
    # endpoints - a web-based connector (unlike a server-side one) issues these as
    # real cross-origin fetches from the client's own browser, which silently fail
    # a preflight without this regardless of whether the bearer token itself is
    # valid. allow_headers is wildcarded since headers carry no origin-trust risk;
    # allow_origins stays an explicit allowlist, the actual security boundary.
    cors_origins = settings.allowed_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.exception_handler(StorageConfigurationError)
    def storage_configuration_error_handler(_request: object, error: StorageConfigurationError) -> JSONResponse:
        translated = translate_error(error)
        return JSONResponse(status_code=translated.status_code, content={"detail": translated.detail})

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
        return HealthResponse(status="ok", app=settings.app_name, environment=settings.environment)

    @app.get("/v1/taxonomy", response_model=TaxonomyResponse, tags=["taxonomy"])
    def taxonomy(ctx: Annotated[RequestContext, Depends(get_request_context)]) -> TaxonomyResponse:
        require_scope(ctx.user, "taxonomy:read")
        repo = TaxonomyRepository(ctx.conn)
        return TaxonomyResponse(categories=repo.list_categories(), themes=repo.list_themes())

    @app.get("/v1/taxonomy/categories", response_model=list[Category], tags=["taxonomy"])
    def categories(ctx: Annotated[RequestContext, Depends(get_request_context)]) -> list[Category]:
        require_scope(ctx.user, "taxonomy:read")
        return TaxonomyRepository(ctx.conn).list_categories()

    @app.get("/v1/taxonomy/themes", response_model=list[Theme], tags=["taxonomy"])
    def themes(ctx: Annotated[RequestContext, Depends(get_request_context)]) -> list[Theme]:
        require_scope(ctx.user, "taxonomy:read")
        return TaxonomyRepository(ctx.conn).list_themes()

    @app.get("/v2/taxonomy/manifest", response_model=TaxonomyManifest, tags=["taxonomy"])
    def taxonomy_manifest(
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        transaction_type: Annotated[TransactionType | None, Query()] = None,
    ) -> TaxonomyManifest:
        require_scope(ctx.user, "taxonomy:read")
        return TaxonomyRepository(ctx.conn).manifest(
            transaction_type=transaction_type.value if transaction_type is not None else None
        )

    @app.get(
        "/v2/taxonomy/branches/{stable_key:path}",
        response_model=TaxonomyBranch,
        tags=["taxonomy"],
    )
    def taxonomy_branch(
        stable_key: str,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TaxonomyBranch:
        require_scope(ctx.user, "taxonomy:read")
        try:
            return TaxonomyRepository(ctx.conn).branch(stable_key)
        except Exception as error:
            raise translate_error(error) from error

    @app.get("/v2/taxonomy/search", response_model=TaxonomySearchResponse, tags=["taxonomy"])
    def taxonomy_search(
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        q: str = Query(min_length=1, max_length=120),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> TaxonomySearchResponse:
        require_scope(ctx.user, "taxonomy:read")
        return TaxonomyRepository(ctx.conn).search(q, limit=limit)

    @app.post(
        "/v1/transactions/drafts",
        response_model=TransactionDetail,
        status_code=status.HTTP_201_CREATED,
        tags=["transactions"],
    )
    def create_draft(
        payload: TransactionDraftCreate,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionDetail:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).create_draft(payload)
        except Exception as error:
            raise translate_error(error) from error

    @app.get(
        "/v1/receipts/{receipt_id}/files/{file_id}/download-url",
        response_model=ReceiptFileDownloadUrlResponse,
        tags=["receipts"],
    )
    def create_receipt_download_url(
        receipt_id: UUID,
        file_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
        storage: Annotated[ObjectStorage, Depends(get_object_storage)],
        rate_limiter: Annotated[UploadRateLimiter, Depends(get_upload_rate_limiter)],
    ) -> ReceiptFileDownloadUrlResponse:
        require_scope(ctx.user, "transactions:read")
        try:
            service = ReceiptFileService(
                ReceiptRepository(ctx.conn, ctx.user.user_id), storage, rate_limiter, settings
            )
            return service.create_download_url(receipt_id, file_id)
        except Exception as error:
            raise translate_error(error) from error

    @app.delete(
        "/v1/receipts/{receipt_id}/files/{file_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["receipts"],
    )
    def delete_receipt_file(
        receipt_id: UUID,
        file_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
        storage: Annotated[ObjectStorage, Depends(get_object_storage)],
        rate_limiter: Annotated[UploadRateLimiter, Depends(get_upload_rate_limiter)],
    ) -> Response:
        require_scope(ctx.user, "transactions:write")
        try:
            service = ReceiptFileService(
                ReceiptRepository(ctx.conn, ctx.user.user_id), storage, rate_limiter, settings
            )
            deleted = service.delete_file(receipt_id, file_id)
        except Exception as error:
            raise translate_error(error) from error
        return Response(
            status_code=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_202_ACCEPTED,
            headers={} if deleted else {"Retry-After": "60"},
        )

    @app.delete(
        "/v1/receipts/{receipt_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["receipts"],
    )
    def delete_receipt(
        receipt_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
        storage: Annotated[ObjectStorage, Depends(get_object_storage)],
        rate_limiter: Annotated[UploadRateLimiter, Depends(get_upload_rate_limiter)],
    ) -> Response:
        require_scope(ctx.user, "transactions:write")
        try:
            service = ReceiptFileService(
                ReceiptRepository(ctx.conn, ctx.user.user_id), storage, rate_limiter, settings
            )
            deleted = service.delete_receipt(receipt_id)
        except Exception as error:
            raise translate_error(error) from error
        return Response(
            status_code=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_202_ACCEPTED,
            headers={} if deleted else {"Retry-After": "60"},
        )

    @app.get("/v1/transactions/{transaction_id}", response_model=TransactionDetail, tags=["transactions"])
    def get_transaction(
        transaction_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionDetail:
        require_scope(ctx.user, "transactions:read")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).get_transaction(transaction_id)
        except Exception as error:
            raise translate_error(error) from error

    @app.get("/v1/transactions", response_model=TransactionListResponse, tags=["transactions"])
    def list_transactions(
        filters: Annotated[TransactionListFilters, Query()],
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionListResponse:
        require_scope(ctx.user, "transactions:read")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).list_transactions(filters)
        except Exception as error:
            raise translate_error(error) from error

    @app.patch("/v1/transactions/{transaction_id}", response_model=TransactionDetail, tags=["transactions"])
    def update_transaction(
        transaction_id: UUID,
        payload: TransactionPatch,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionDetail:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).update_transaction(transaction_id, payload)
        except Exception as error:
            raise translate_error(error) from error

    @app.post(
        "/v1/transactions/{transaction_id}/items",
        response_model=TransactionItem,
        status_code=status.HTTP_201_CREATED,
        tags=["transactions"],
    )
    def add_item(
        transaction_id: UUID,
        payload: TransactionItemCreate,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionItem:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).add_item(transaction_id, payload)
        except Exception as error:
            raise translate_error(error) from error

    @app.patch(
        "/v1/transactions/{transaction_id}/items/{item_id}",
        response_model=TransactionItem,
        tags=["transactions"],
    )
    def update_item(
        transaction_id: UUID,
        item_id: UUID,
        payload: TransactionItemUpdate,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionItem:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).update_item(
                transaction_id,
                item_id,
                payload,
            )
        except Exception as error:
            raise translate_error(error) from error

    @app.delete(
        "/v1/transactions/{transaction_id}/items/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["transactions"],
    )
    def delete_item(
        transaction_id: UUID,
        item_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> Response:
        require_scope(ctx.user, "transactions:write")
        try:
            TransactionRepository(ctx.conn, ctx.user.user_id).delete_item(transaction_id, item_id)
        except Exception as error:
            raise translate_error(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/v1/transactions/{transaction_id}/validate",
        response_model=ValidationResponse,
        tags=["transactions"],
    )
    def validate_transaction(
        transaction_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> ValidationResponse:
        require_scope(ctx.user, "transactions:write")
        try:
            return ExpenseApplicationService(ctx.conn, ctx.user.user_id, settings).validate(transaction_id)
        except Exception as error:
            raise translate_error(error) from error

    @app.post(
        "/v1/transactions/{transaction_id}/adjustments",
        response_model=TransactionAdjustment,
        status_code=status.HTTP_201_CREATED,
        tags=["transactions"],
    )
    def add_transaction_adjustment(
        transaction_id: UUID,
        payload: TransactionAdjustmentCreate,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionAdjustment:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).add_adjustment(transaction_id, payload)
        except Exception as error:
            raise translate_error(error) from error

    @app.patch(
        "/v1/transactions/{transaction_id}/adjustments/{adjustment_id}",
        response_model=TransactionAdjustment,
        tags=["transactions"],
    )
    def update_transaction_adjustment(
        transaction_id: UUID,
        adjustment_id: UUID,
        payload: TransactionAdjustmentUpdate,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> TransactionAdjustment:
        require_scope(ctx.user, "transactions:write")
        try:
            return TransactionRepository(ctx.conn, ctx.user.user_id).update_adjustment(
                transaction_id, adjustment_id, payload
            )
        except Exception as error:
            raise translate_error(error) from error

    @app.delete(
        "/v1/transactions/{transaction_id}/adjustments/{adjustment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["transactions"],
    )
    def delete_transaction_adjustment(
        transaction_id: UUID,
        adjustment_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        correction_reason: str | None = Query(default=None, max_length=500),
    ) -> Response:
        require_scope(ctx.user, "transactions:write")
        try:
            TransactionRepository(ctx.conn, ctx.user.user_id).delete_adjustment(
                transaction_id, adjustment_id, correction_reason
            )
        except Exception as error:
            raise translate_error(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/transactions/{transaction_id}/confirm", response_model=TransactionDetail, tags=["transactions"])
    def confirm_transaction(
        transaction_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> TransactionDetail:
        require_scope(ctx.user, "transactions:write")
        try:
            return ExpenseApplicationService(ctx.conn, ctx.user.user_id, settings).confirm(
                transaction_id,
                explicit_approval=True,
            )
        except Exception as error:
            raise translate_error(error) from error

    @app.delete(
        "/v1/transactions/{transaction_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["transactions"],
    )
    def delete_transaction(
        transaction_id: UUID,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
        settings: Annotated[Settings, Depends(get_settings)],
        storage: Annotated[ObjectStorage, Depends(get_object_storage)],
        rate_limiter: Annotated[UploadRateLimiter, Depends(get_upload_rate_limiter)],
    ) -> Response:
        require_scope(ctx.user, "transactions:write")
        try:
            service = ReceiptFileService(
                ReceiptRepository(ctx.conn, ctx.user.user_id), storage, rate_limiter, settings
            )
            deleted = service.delete_transaction(transaction_id)
        except Exception as error:
            raise translate_error(error) from error
        return Response(
            status_code=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_202_ACCEPTED,
            headers={} if deleted else {"Retry-After": "60"},
        )

    @app.post("/v1/aliases/resolve", response_model=AliasResolveResponse, tags=["aliases"])
    def resolve_aliases(
        payload: AliasResolveRequest,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> AliasResolveResponse:
        require_scope(ctx.user, "aliases:read")
        repo = TransactionRepository(ctx.conn, ctx.user.user_id)
        return AliasResolveResponse(
            resolutions=repo.resolve_aliases(payload.merchant_normalized, payload.items)
        )

    @app.post("/v1/analytics/query", response_model=AnalyticsQueryResponse, tags=["analytics"])
    def query_analytics(
        payload: AnalyticsQueryRequest,
        ctx: Annotated[RequestContext, Depends(get_request_context)],
    ) -> AnalyticsQueryResponse:
        require_scope(ctx.user, "analytics:read")
        compiler = AnalyticsQueryCompiler(today=lambda: local_today(settings))
        return AnalyticsRepository(ctx.conn, ctx.user.user_id, compiler).query(payload)

    if mcp_asgi is not None:
        # Keep the existing REST/OpenAPI routes authoritative, then delegate
        # the exact /mcp path to the SDK's Streamable HTTP ASGI application.
        app.mount("/", mcp_asgi)
    if gateway_upstream_url is not None and gateway_client is not None:
        app.include_router(
            build_gateway_router(
                gateway_upstream_url,
                gateway_client,
                use_google_id_token=settings.mcp_gateway_use_google_id_token,
            )
        )
    if settings.oauth_client_id is not None:
        app.router.routes.extend(build_oauth_routes(settings))
    return app


app = create_app()
