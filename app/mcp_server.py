import logging
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from app.analytics import AnalyticsQueryCompiler, AnalyticsRepository
from app.application import ExpenseApplicationService
from app.clock import local_today
from app.config import Settings
from app.dashboard import DashboardRepository
from app.db import user_transaction
from app.email_ingestion_repository import EmailIngestionRepository
from app.errors import (
    ConflictError,
    ExternalLookupError,
    InvalidUploadError,
    NotFoundError,
    PrincipalConfigurationError,
    StorageConfigurationError,
    StorageObjectNotFoundError,
    StorageOperationError,
    UploadRateLimitError,
    ValidationReferenceError,
)
from app.models import (
    AdjustmentType,
    AliasResolveItem,
    AliasResolveResponse,
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    OpenAIFileInput,
    TaxonomyBranch,
    TaxonomyManifest,
    TaxonomySearchResponse,
    TransactionListFilters,
    TransactionListResponse,
    TransactionType,
)
from app.nutrition_external_lookup import (
    get_open_food_facts_by_barcode,
    get_usda_food_detail,
    new_off_client,
    new_usda_client,
    search_open_food_facts,
    search_usda_foods,
)
from app.nutrition_repository import NutritionRepository
from app.plugin_models import (
    CheckEmailProcessedRequest,
    CheckEmailProcessedResponse,
    CheckEmailsProcessedRequest,
    CheckEmailsProcessedResponse,
    ClaimEmailForProcessingRequest,
    ClaimEmailForProcessingResponse,
    ExpenseCorrectionRequest,
    ExpenseDashboard,
    ExpenseDashboardRequest,
    ExpenseDraftInput,
    ExpenseDraftSaveRequest,
    ExpenseSnapshot,
    ExpenseTaxonomy,
    ExpenseValidationResult,
    ItemPriceHistory,
    ItemPriceHistoryRequest,
    MerchantBreakdownRequest,
    MerchantBreakdownResponse,
    MutationResult,
    NutritionQueueRequest,
    NutritionQueueResponse,
    NutritionResultInput,
    NutritionResultResponse,
    NutritionSummary,
    NutritionSummaryRequest,
    OpenFoodFactsSearchResponse,
    OperationResult,
    PersonalBasketIndex,
    PersonalBasketRequest,
    ReceiptDownloadPublic,
    ReceiptFileRequirements,
    RecordEmailProcessedRequest,
    SearchKnownItemsRequest,
    SearchKnownItemsResponse,
    SearchNutritionLookupsRequest,
    SearchNutritionLookupsResponse,
    UsdaFoodCandidate,
    UsdaFoodSearchResponse,
    WidgetView,
)
from app.principal import SingleUserPrincipalResolver
from app.receipt_commit import ReceiptCommitSaga
from app.receipt_downloads import RemoteReceiptDownloader
from app.receipt_extraction import ReceiptCommitRequest, ReceiptCommitResult
from app.receipt_files import ALLOWED_RECEIPT_TYPES, ReceiptFileService, ReceiptRepository
from app.receipt_normalization import normalize_receipt_savings
from app.reconciliation import has_blocking_issues
from app.repositories import TaxonomyRepository, TransactionRepository
from app.storage_dependencies import get_object_storage, get_upload_rate_limiter

logger = logging.getLogger(__name__)

# ChatGPT treats UI resource URIs as cache keys. A schema prefix handles changes
# to resource semantics; the content digest prevents changed bundles from ever
# being published under a stale URI.
WIDGET_SCHEMA_VERSION = "v40"
WIDGET_BUILD_PATH = Path(__file__).resolve().parent.parent / "widget" / "dist" / "index.html"


def _widget_content_version(path: Path = WIDGET_BUILD_PATH) -> str:
    if not path.exists():
        return f"{WIDGET_SCHEMA_VERSION}-source"
    digest = sha256(path.read_bytes()).hexdigest()[:12]
    return f"{WIDGET_SCHEMA_VERSION}-{digest}"


WIDGET_VERSION = _widget_content_version()
WIDGET_URI = f"ui://holy-spend/app-{WIDGET_VERSION}.html"
WIDGET_MIME_TYPE = "text/html;profile=mcp-app"
EXPECTED_ERRORS = (
    ConflictError,
    ExternalLookupError,
    InvalidUploadError,
    NotFoundError,
    PrincipalConfigurationError,
    StorageConfigurationError,
    StorageObjectNotFoundError,
    StorageOperationError,
    UploadRateLimitError,
    ValidationReferenceError,
)


def _safe[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except EXPECTED_ERRORS as error:
        raise ValueError(str(error)) from None
    except Exception:
        logger.exception("Unexpected MCP tool failure")
        raise RuntimeError("The expense tracker could not complete that request") from None


def _hidden_result(
    structured: Any,
    message: str,
    hidden_meta: dict[str, Any],
) -> CallToolResult:
    structured_content = structured.model_dump(mode="json") if hasattr(structured, "model_dump") else structured
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structuredContent=structured_content,
        _meta=hidden_meta,
    )


def _render_result(
    view: WidgetView,
) -> CallToolResult:
    return _hidden_result(
        view,
        f"Rendered {view.title}.",
        {
            "ui": {"resourceUri": WIDGET_URI},
            "openai/outputTemplate": WIDGET_URI,
        },
    )


def _widget_html() -> str:
    if WIDGET_BUILD_PATH.exists():
        return WIDGET_BUILD_PATH.read_text(encoding="utf-8")
    return """<!doctype html>
<html><body><main>
<h1>Holy Spend widget is not built</h1>
<p>Run <code>npm install</code> and <code>npm run build</code> in <code>widget/</code>.</p>
</main></body></html>"""


def create_mcp_server(settings: Settings) -> FastMCP[None]:
    resolver = SingleUserPrincipalResolver(settings)
    usda_client = new_usda_client(settings.nutrition_lookup_timeout_seconds)
    off_client = new_off_client(settings.nutrition_lookup_timeout_seconds)
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_mcp_hosts()),
        allowed_origins=list(settings.allowed_mcp_origins()),
    )
    server: FastMCP[None] = FastMCP(
        "Holy Spend",
        instructions=(
            "Private single-owner expense tracker. ChatGPT visually reads receipts; the backend never runs OCR. "
            "For an attached receipt, visually extract it and call create_receipt_draft_from_file once with the "
            "native file parameter and complete candidate. The tool verifies, normalizes, reconciles, stores, and "
            "returns the saved draft without opening UI. Never store or repeat temporary download URLs. "
            "On a host with no native hosted-URL file parameter for the attachment (e.g. Claude), do not call "
            "create_receipt_draft_from_file at all; instead extract the same complete candidate and call "
            "save_expense_draft directly, and explicitly tell the user in the same reply that every extracted "
            "detail was saved but the original receipt image or PDF itself could not be stored on this host. "
            "Always parse a package size, weight, volume, or count directly from the item's own printed text "
            "(e.g. '4 L', '500 g', '2 x 340 g', '12 ct', '30 ct', '8 = 24 Regular Rolls') into "
            "measured_value/measured_unit or package_value/package_unit, even when no separate per-unit price "
            "line is printed on the receipt, and even when the count or size is embedded inside a longer "
            "product description rather than sitting on its own; only leave those fields null when no size is "
            "visible anywhere for that line. "
            "Capture brand whenever the receipt text shows a manufacturer or store brand distinct from the "
            "generic product name (e.g. 'Tide', 'Kirkland Signature', 'Great Value'), including a private-label "
            "store brand that reads like a plain descriptive phrase rather than a typical brand name (e.g. "
            "'Your Fresh Market', 'No Name', 'President's Choice', or the store's own name prefixing a generic "
            "item); never guess one that isn't legible. Dairy, eggs, other non-produce packaged food and drink "
            "(pantry, snacks, bakery, beverages, meat/seafood, grains, frozen), and household paper or cleaning "
            "goods almost always carry a real brand, so a missing one there needs the same follow-up treatment "
            "as a missing size. Fresh produce is the exception: most of it has no manufacturer brand at all, so "
            "capture one only when it is actually printed (including a store produce brand like the examples "
            "above) and otherwise leave it null without asking. "
            "Always populate normalized_name for every purchase-role grocery or household item, a clean readable "
            "version of the product name (lightly cleaned raw text is fine, e.g. lowercased and de-abbreviated; "
            "it does not need to be reworded). Never leave it null - an item with no normalized_name is silently "
            "invisible to nutrition lookups and price-history tracking even though it saves and confirms "
            "successfully with no error, so this is easy to miss without a dedicated check. "
            "For a weighable or countable grocery or "
            "household item whose size cannot be determined at all, or a non-produce food/drink item or "
            "household paper/cleaning good whose brand cannot be determined at all, ask the user one combined "
            "follow-up question listing every such item before finalizing the draft, so later unit-price and "
            "per-brand comparisons stay meaningful; do not ask for one-time or service lines, or for produce "
            "brand, where the answer would not be meaningful anyway. This follow-up question is mandatory even "
            "when the user's own request already pre-authorized saving and confirming in the same turn (e.g. "
            "'add and confirm this receipt') — that authorization covers the confirmation step itself, never a "
            "reason to skip asking about a genuinely undeterminable size, brand, or quantity first. "
            "When an item's name, brand, or product code is only partially legible or abbreviated past "
            "recognition, look it up online to identify what the fragment actually refers to (a SKU, barcode, "
            "or abbreviated store code resolving to its real product or brand name); this is for genuinely "
            "illegible or ambiguous fragments only, never a substitute for carefully re-reading text that is "
            "already legible on the receipt, and never look up or infer a price, weight, size, or count that is "
            "not itself printed on the receipt, since a wrong guessed number silently baked into unit-price math "
            "is worse than an honest blank or a follow-up question, and label any value resolved this way as "
            "looked-up rather than presenting it as receipt-verbatim. "
            "Before finalizing, saving, or confirming a receipt draft — whether or not it is ever shown to the "
            "user first — run one explicit pass over every item, not a casual re-read: for each line, confirm a "
            "size value is captured or the line is a genuine exception (produce with no printed size, or a "
            "one-time/service line), confirm brand is captured or the line is a genuine exception (produce "
            "with no printed brand), and confirm normalized_name is set for every purchase-role line without "
            "exception. An item silently missing any of these three fields with no stated reason is a contract "
            "violation to fix before saving, not something to leave for next time; this check runs even in a "
            "same-turn add-and-confirm flow where no draft is ever presented for review. "
            "For a grocery or household item that looks like a repeat staple (produce, dairy, pantry goods, "
            "anything the owner plausibly buys again and again) rather than a clearly one-off purchase, check "
            "whether they already have something matching the same real product before finalizing this item's "
            "normalized_name and brand: call search_known_items with a short generic query (e.g. 'milk', not the "
            "full candidate name) and look through every result, not just the first. Do this even when the owner "
            "tells you outright it's the same as a prior purchase ('same as always', 'same brand as last time') — "
            "that confirms a match should exist, it doesn't excuse skipping the lookup, since the exact stored "
            "text is what actually needs reusing and cannot be safely guessed from memory alone. Do not use "
            "get_item_price_history for this discovery step: its 'name:' identity match requires the exact "
            "stored text and returns nothing for a plausible guess, so an empty result there proves nothing about "
            "whether a matching purchase exists — only search_known_items's substring search can answer that. If "
            "a result's brand and product type are clearly the same real product, reuse that existing purchase's "
            "normalized_name and brand text verbatim for this item too, even when this receipt's own printed text "
            "differs (abbreviated, reordered, or scanned with more or less detail) — matching text is what lets "
            "the app group repeat purchases into one item with a purchase count and automatically reuse whatever "
            "nutrition data was already found for it, instead of creating a disconnected second copy that "
            "silently fragments the purchase history and needs its own separate nutrition lookup. If a result is "
            "only plausibly the same product (different size, ambiguous brand, or genuinely unclear), fold it "
            "into the same combined follow-up question already used for missing size/brand, asking the owner to "
            "confirm whether it's the same item as the existing purchase or a different one — don't silently "
            "guess either way. "
            "Call open_expense_tracker only when the user explicitly asks to open, review, edit, or browse the "
            "interactive tracker; receipt save, validation, and confirmation otherwise remain chat-only. "
            "Uploading, analyzing, or saving a draft is not approval; confirm only after explicit user approval. "
            "Classify every semantic line with an assignable Taxonomy v2 stable key. Use taxonomy search for "
            "candidate leaves and branch lookup for local context; never invent or embed category lists. "
            "Use whole_bill mode for a single service/bill line and itemized mode for receipt products. "
            "Record cross-cutting attributes as facets rather than taxonomy branches. "
            "Never ask for or accept a user ID. "
            "Open the tracker at Overview unless the user explicitly requests another route or transaction. "
            "Analytics is confirmed-only and always separated by currency."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )

    def resource_meta(description: str) -> dict[str, Any]:
        return {
            "ui": {
                "prefersBorder": False,
                "csp": {
                    "connectDomains": list(settings.widget_connect_domains()),
                    "resourceDomains": list(settings.widget_resource_domains()),
                },
            },
            "openai/widgetDescription": description,
            "openai/widgetPrefersBorder": False,
            "openai/widgetCSP": {
                "connect_domains": list(settings.widget_connect_domains()),
                "resource_domains": list(settings.widget_resource_domains()),
            },
        }

    @server.resource(
        WIDGET_URI,
        name="holy-spend-app",
        title="Holy Spend",
        description="Versioned mobile-first expense tracker, editor, history, and price browser.",
        mime_type=WIDGET_MIME_TYPE,
        meta=resource_meta(
            "A mobile-first expense tracker with swipeable inline highlights and focused fullscreen "
            "screens for Overview, Activity, Price Watch, and receipt/manual review."
        ),
    )
    def app_resource() -> str:
        return _widget_html()

    @server.tool(
        title="Get expense taxonomy",
        description=(
            "Use this when you need the allowed categories and themes before classifying receipt or manual items."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_expense_taxonomy() -> ExpenseTaxonomy:
        def action() -> ExpenseTaxonomy:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                repository = TaxonomyRepository(conn)
                manifest = repository.manifest()
                return ExpenseTaxonomy(
                    version=manifest.version,
                    roots=manifest.roots,
                    assignable_nodes=manifest.assignable_nodes,
                    facets=manifest.facets,
                    categories=repository.list_categories(),
                    themes=repository.list_themes(),
                    adjustment_types=list(AdjustmentType),
                    supported_currencies=list(settings.supported_currencies),
                    receipt_files=ReceiptFileRequirements(
                        allowed_mime_types=sorted(set(ALLOWED_RECEIPT_TYPES.values())),
                        max_file_bytes=settings.max_receipt_file_bytes,
                    ),
                )

        return _safe(action)

    @server.tool(
        title="Get taxonomy manifest",
        description=(
            "Use this when you need the active Taxonomy v2 version, six reporting levels, root domains, "
            "assignable leaves, and orthogonal facets for initialization or a complete taxonomy refresh."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_taxonomy_manifest(
        transaction_type: TransactionType | None = None,
    ) -> TaxonomyManifest:
        def action() -> TaxonomyManifest:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return TaxonomyRepository(conn).manifest(
                    transaction_type=transaction_type.value if transaction_type is not None else None
                )

        return _safe(action)

    @server.tool(
        title="Get taxonomy branch",
        description=(
            "Use this when a broad domain has been identified and you need one Taxonomy v2 node, "
            "all descendants, and their complete reporting paths."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_taxonomy_branch(stable_key: str) -> TaxonomyBranch:
        def action() -> TaxonomyBranch:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return TaxonomyRepository(conn).branch(stable_key)

        return _safe(action)

    @server.tool(
        title="Search taxonomy",
        description=(
            "Use this when an expense line is ambiguous: search assignable Taxonomy v2 leaves by "
            "stable key, display name, and synonyms instead of guessing a key."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_taxonomy(query: str, limit: int = 20) -> TaxonomySearchResponse:
        def action() -> TaxonomySearchResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return TaxonomyRepository(conn).search(query, limit=max(1, min(limit, 50)))

        return _safe(action)

    @server.tool(
        title="Resolve expense aliases",
        description=(
            "Use this when extracted merchant or item names may match the owner's previously confirmed classifications."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def resolve_expense_aliases(
        items: list[AliasResolveItem],
        merchant_normalized: str | None = None,
    ) -> AliasResolveResponse:
        def action() -> AliasResolveResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                resolutions = TransactionRepository(conn, principal.user_id).resolve_aliases(
                    merchant_normalized,
                    items,
                )
                return AliasResolveResponse(resolutions=resolutions)

        return _safe(action)

    @server.tool(
        title="List expenses",
        description=(
            "Use this when you need paginated expense history filtered by status, date, merchant, category, source, "
            "transaction type, or currency."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def list_expenses(filters: TransactionListFilters | None = None) -> TransactionListResponse:
        def action() -> TransactionListResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return TransactionRepository(conn, principal.user_id).list_transactions(
                    filters or TransactionListFilters()
                )

        return _safe(action)

    @server.tool(
        title="Get expense",
        description=(
            "Use this when you need one complete expense draft or confirmed record, including receipt metadata."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_expense(transaction_id: UUID) -> ExpenseSnapshot:
        def action() -> ExpenseSnapshot:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return ExpenseApplicationService(conn, principal.user_id, settings).get_expense(transaction_id)

        return _safe(action)

    @server.tool(
        title="Get expense analytics",
        description=(
            "Use this when you need confirmed-only spending totals, counts, quantities, averages, discounts, taxes, "
            "fees, or refunds; monetary results are never combined across currencies."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_expense_analytics(query: AnalyticsQueryRequest) -> AnalyticsQueryResponse:
        def action() -> AnalyticsQueryResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                compiler = AnalyticsQueryCompiler(today=lambda: local_today(settings))
                return AnalyticsRepository(conn, principal.user_id, compiler).query(query)

        return _safe(action)

    @server.tool(
        title="Get expense dashboard",
        description=(
            "Use this when you need the owner's focused spending overview, including period comparisons, "
            "categories, review queue, recent transactions, and trustworthy unit-price changes."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_expense_dashboard(
        request: ExpenseDashboardRequest | None = None,
    ) -> ExpenseDashboard:
        def action() -> ExpenseDashboard:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return DashboardRepository(
                    conn,
                    principal.user_id,
                    today=lambda: local_today(settings),
                    fallback_currency=settings.supported_currencies[0],
                ).get_dashboard(request or ExpenseDashboardRequest())

        return _safe(action)

    @server.tool(
        title="Get item price history",
        description=(
            "Use this when you need comparable confirmed purchase prices for one product identity; results stay "
            "separated by currency and normalized mass, volume, or count unit."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_item_price_history(request: ItemPriceHistoryRequest) -> ItemPriceHistory:
        def action() -> ItemPriceHistory:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return DashboardRepository(conn, principal.user_id).get_item_price_history(request)

        return _safe(action)

    @server.tool(
        title="Search known items",
        description=(
            "Use this when finalizing normalized_name/brand on a repeat-staple grocery or household receipt "
            "line, to check whether the owner already has a matching purchase under different wording. Does a "
            "real substring search (e.g. query='milk' matches 'Sealtest Partly Skimmed Milk 4 L') - unlike "
            "get_item_price_history's 'name:' identity match, which requires the exact stored text and returns "
            "nothing for a plausible guess, so it cannot answer 'has anything like this been bought before'. "
            "Returns every distinct normalized_name/brand combination matching the query, with purchase_count "
            "and last purchase date, so you can pick the right one to reuse verbatim or confirm none exist."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_known_items(request: SearchKnownItemsRequest) -> SearchKnownItemsResponse:
        def action() -> SearchKnownItemsResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return DashboardRepository(conn, principal.user_id).search_known_items(request)

        return _safe(action)

    @server.tool(
        title="Get personal basket index",
        description=(
            "Use this when the owner wants to know whether their own repeat grocery purchases are costing more "
            "over time. Compares exact products (same name, brand, unit, AND store - never blended varieties "
            "like Price Watch, and never blended across merchants either, since the same product can be "
            "priced differently store to store), weighted by recent spend, with sample size and coverage "
            "always included."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_personal_basket_index(request: PersonalBasketRequest) -> PersonalBasketIndex:
        def action() -> PersonalBasketIndex:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return DashboardRepository(conn, principal.user_id).get_personal_basket(request)

        return _safe(action)

    @server.tool(
        title="Get merchant breakdown",
        description=(
            "Use this when the owner wants to know which merchants they spent at, ranked by spend, with the same "
            "period-over-period comparison as the categories view. Rows only include merchants with spend in the "
            "current period; a merchant with no current-period visits is omitted rather than shown at zero."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_merchant_breakdown(request: MerchantBreakdownRequest) -> MerchantBreakdownResponse:
        def action() -> MerchantBreakdownResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return DashboardRepository(
                    conn,
                    principal.user_id,
                    today=lambda: local_today(settings),
                ).get_merchant_breakdown(request)

        return _safe(action)

    @server.tool(
        title="Get nutrition queue",
        description=(
            "Use this when running the scheduled nutrition lookup task. Queues any newly confirmed grocery items "
            "not already tracked, then returns a small batch of pending items awaiting a nutrition lookup. For "
            "each item, search nutrition_lookup_usda and nutrition_lookup_off first - they return structured, "
            "pre-normalized data through this server directly rather than scraped web pages, and reject "
            "internally-impossible source data automatically; fall back to general web search only for a "
            "product neither one covers. Call save_nutrition_result for each item returned before requesting "
            "another batch."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def get_nutrition_queue(request: NutritionQueueRequest | None = None) -> NutritionQueueResponse:
        def action() -> NutritionQueueResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return NutritionRepository(conn, principal.user_id).get_queue(
                    (request or NutritionQueueRequest()).limit
                )

        return _safe(action)

    @server.tool(
        title="Save nutrition result",
        description=(
            "Use this when running the scheduled nutrition lookup task, once for each item returned by "
            "get_nutrition_queue, after searching for its nutrition facts - or to correct an item that's already "
            "matched but wrong or thin (e.g. only a source-stated grade with no real macros behind it); look it "
            "up first with search_nutrition_lookups to get its id, since already-matched items never appear in "
            "get_nutrition_queue again. item_id must be copied exactly from the id field of a real "
            "get_nutrition_queue or search_nutrition_lookups result - never invent, guess, or reuse an id from a "
            "different run or a different item; if you're not looking at a real id from one of those two tools, "
            "call one of them again rather than fabricating one. "
            "Only report a matched result grounded "
            "in an actual source you found; report nutriments only for values that source actually gave, never a "
            "recalled or estimated number - this applies to every nutrient field (energy, protein, fat, saturated "
            "and trans fat, carbohydrates, sugars, added sugars, fiber, sodium, cholesterol, potassium, calcium, "
            "iron) without exception, and added_sugars_g is a different number from sugars_g, not a duplicate of "
            "it - only report it when the source states it separately. When the source shows an explicit "
            "serving-based breakdown (e.g. \"2 tbsp (30 mL)\", \"1 slice (28g)\"), report serving_label using the "
            "source's own wording alongside serving_size_g - never invent one for a source that only gives "
            "per-100g values. Report nutriscore_grade only when the "
            "source itself states it (e.g. an Open Food Facts page showing a Nutri-Score badge); the app computes "
            "its own deterministic grade from macros server-side and prefers that when it can, so a source-stated "
            "grade is used only as a fallback. nova_group is the one field where estimation is allowed: if the "
            "source states a NOVA group, report it with nova_group_estimated=false; if no source states one but "
            "you can model it yourself from the product's ingredient list (additives, degree of industrial "
            "processing), report your best estimate with nova_group_estimated=true so the app can label it as "
            "estimated rather than sourced. When no trustworthy source was found for the product at all, report "
            "a no-match instead of a low-confidence guess."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def save_nutrition_result(payload: NutritionResultInput) -> NutritionResultResponse:
        def action() -> NutritionResultResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return NutritionRepository(conn, principal.user_id).save_result(payload)

        return _safe(action)

    @server.tool(
        title="Search nutrition lookups",
        description=(
            "Use this when you need to find an existing nutrition_lookups row regardless of status - most "
            "importantly to correct an already-matched item, since get_nutrition_queue only ever returns "
            "pending or no_match rows and an item that's already matched (even with wrong, thin, or missing "
            "data) never appears there again. Does a real substring search on product name and brand and returns "
            "each match's id, status, current source/grade, and attempts, so you can review what's actually "
            "stored before deciding whether it needs fixing with save_nutrition_result."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def search_nutrition_lookups(request: SearchNutritionLookupsRequest) -> SearchNutritionLookupsResponse:
        def action() -> SearchNutritionLookupsResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return NutritionRepository(conn, principal.user_id).search_lookups(request)

        return _safe(action)

    @server.tool(
        title="Check email processed",
        description=(
            "Use this when running the scheduled email-receipt-ingestion task to check a single email, mainly for "
            "correcting or re-checking one message on its own - for the normal top-of-loop pass over an inbox "
            "listing, call check_emails_processed with every message id from that listing in one batch instead, "
            "it's the same check without one round-trip per email. Pass Gmail's own message id (not the subject, "
            "not a derived key). Returns whether this email has already been looked at in a prior run, and if so, "
            "what happened to it (drafted/flagged/not_a_receipt, plus the transaction_id if one was created). If "
            "processed is true, skip this email entirely - do not re-read it, re-classify it, or call "
            "save_expense_draft again for it."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def check_email_processed(request: CheckEmailProcessedRequest) -> CheckEmailProcessedResponse:
        def action() -> CheckEmailProcessedResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return EmailIngestionRepository(conn, principal.user_id).check_processed(request)

        return _safe(action)

    @server.tool(
        title="Check emails processed (batch)",
        description=(
            "Use this when running the scheduled email-receipt-ingestion task, once per run, right after listing "
            "the forwarding inbox - pass every email's Gmail message id from that listing (up to 25) in one call "
            "instead of calling check_email_processed once per email. Returns one result per id, same shape as "
            "check_email_processed, in the same order as the ids you passed in. Only read/classify/draft the ids "
            "that come back with processed: false - anything already processed should be skipped entirely, same "
            "rule as the single-email version."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def check_emails_processed(request: CheckEmailsProcessedRequest) -> CheckEmailsProcessedResponse:
        def action() -> CheckEmailsProcessedResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return EmailIngestionRepository(conn, principal.user_id).check_processed_batch(request)

        return _safe(action)

    @server.tool(
        title="Claim email for processing",
        description=(
            "Use this when running the scheduled email-receipt-ingestion task, once per email, immediately before "
            "doing any real work on an email that check_email_processed/check_emails_processed reported as "
            "processed: false - this is what actually prevents two overlapping runs (or a retry after a crash) "
            "from both drafting a transaction for the same email. Returns claimed: true if you now own this "
            "message_id and should proceed to read/classify/draft it, then call record_email_processed when done. "
            "Returns claimed: false if another attempt already holds it (a finished result, or a claim from "
            "within the last hour) - skip this email entirely for this run, do not process it. A claim you took "
            "but never finalized with record_email_processed expires after an hour and becomes claimable again."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def claim_email_for_processing(
        request: ClaimEmailForProcessingRequest,
    ) -> ClaimEmailForProcessingResponse:
        def action() -> ClaimEmailForProcessingResponse:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return EmailIngestionRepository(conn, principal.user_id).claim_for_processing(request)

        return _safe(action)

    @server.tool(
        title="Record email processed",
        description=(
            "Use this when running the scheduled email-receipt-ingestion task, once per email, immediately after "
            "reaching a real terminal outcome for it - never after a tool call genuinely errors, since an "
            "unrecorded email is retried next run and a wrongly-recorded one never will be. status is 'drafted' when "
            "save_expense_draft succeeded for this email (pass its transaction_id), 'flagged' when it's a real "
            "receipt that needed itemization the email couldn't provide (pass a short note explaining why - no "
            "items shown, a truncated item list, etc), or 'not_a_receipt' when the email wasn't a purchase "
            "confirmation at all. Calling this twice for the same message_id overwrites the prior record rather "
            "than erroring, so a retried call after an uncertain prior attempt is always safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def record_email_processed(request: RecordEmailProcessedRequest) -> OperationResult:
        def action() -> OperationResult:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return EmailIngestionRepository(conn, principal.user_id).record_processed(request)

        return _safe(action)

    @server.tool(
        title="Get nutrition summary",
        description=(
            "Use this when the owner wants to see how healthy their grocery basket is: a spend-weighted "
            "Nutri-Score-style grade, a grade distribution, processing-level signals, and category-grouped "
            "items with full nutrition facts. Only matched items (status='matched') affect the grade; items "
            "still queued for lookup (status='pending') or that a lookup already tried and couldn't match "
            "(status='no_match') are listed too but don't affect the grade."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def get_nutrition_summary(request: NutritionSummaryRequest) -> NutritionSummary:
        def action() -> NutritionSummary:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return NutritionRepository(conn, principal.user_id).get_summary(
                    request, today=lambda: local_today(settings)
                )

        return _safe(action)

    @server.tool(
        title="Search USDA FoodData Central",
        description=(
            "Use this when running the scheduled nutrition lookup task, to search USDA FoodData Central for candidate "
            "matches for a grocery item. Returns several ranked candidates, not a single answer - you must still "
            "evaluate them for plausibility (a generic aggregated entry, an unusually high or low value for the "
            "food type, a mismatched description) before trusting one, exactly as you would a web search result. "
            "Nutrients are already normalized to this app's per-100g units (kcal, g, mg); no conversion needed. "
            "A candidate whose reported macros are internally impossible (e.g. sugars exceeding carbohydrates) "
            "has nutrients_per_100g set to null with data_quality_warning explaining why - don't use that "
            "candidate's numbers. Pass data_types to narrow noisy results, e.g. ['Foundation', 'SR Legacy'] for "
            "a generic whole food or ['Branded'] for a specific packaged product. This tool only searches; call "
            "save_nutrition_result yourself once you've picked a value you trust."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    def nutrition_lookup_usda(
        query: str,
        page_size: int = 10,
        data_types: list[str] | None = None,
    ) -> UsdaFoodSearchResponse:
        def action() -> UsdaFoodSearchResponse:
            return search_usda_foods(
                usda_client,
                settings.usda_fdc_api_key.get_secret_value(),
                query,
                page_size=page_size,
                data_types=data_types,
            )

        return _safe(action)

    @server.tool(
        title="Get USDA FoodData Central detail",
        description=(
            "Use this when nutrition_lookup_usda already found a candidate's fdcId but its abbreviated nutrient "
            "list is missing something you need - fetches that one food's fuller nutrient panel. Same per-100g "
            "normalization and data_quality_warning behavior as nutrition_lookup_usda."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    def nutrition_lookup_usda_detail(fdc_id: int) -> UsdaFoodCandidate:
        def action() -> UsdaFoodCandidate:
            return get_usda_food_detail(usda_client, settings.usda_fdc_api_key.get_secret_value(), fdc_id)

        return _safe(action)

    @server.tool(
        title="Search Open Food Facts",
        description=(
            "Use this when running the scheduled nutrition lookup task, to look up a product on Open Food Facts, "
            "either by barcode (most precise, when a UPC/EAN is already known, e.g. from your own automation "
            "notes) or by free-text query - provide exactly one of the two. Pass brand to narrow a query search "
            "to a specific manufacturer (e.g. brand='Natrel' with query='partly skimmed milk') when the plain "
            "product name alone returns too much noise. Returns candidates with nutrients "
            "normalized to this app's per-100g units. Open Food Facts is community-edited, so still "
            "sanity-check nutriscore_grade, nova_group, and nutrition_data_per yourself (a source stating "
            "'100ml' or an implausible serving_size is a real signal, not noise to ignore) before trusting a "
            "match. A candidate whose reported macros are internally impossible has nutrients_per_100g set to "
            "null with data_quality_warning explaining why - don't use that candidate's numbers."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    def nutrition_lookup_off(
        query: str | None = None,
        barcode: str | None = None,
        page_size: int = 10,
        brand: str | None = None,
    ) -> OpenFoodFactsSearchResponse:
        def action() -> OpenFoodFactsSearchResponse:
            if (query is None) == (barcode is None):
                raise ExternalLookupError("Provide exactly one of query or barcode")
            if barcode is not None:
                return get_open_food_facts_by_barcode(off_client, barcode)
            assert query is not None
            return search_open_food_facts(off_client, query, page_size=page_size, brand=brand)

        return _safe(action)

    @server.tool(
        title="Create receipt draft from file",
        description=(
            "Use this when the user attached one receipt image or PDF and ChatGPT has visually extracted a complete "
            "expense candidate. In one retry-safe operation this verifies the file, normalizes informational savings, "
            "reconciles the draft, and stores the original privately. This data-only tool never opens UI. If the user "
            "explicitly asked to review or edit interactively, call open_expense_tracker afterward with the returned "
            "transaction review route. Never confirm here."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        meta={
            "openai/fileParams": ["file"],
            "openai/toolInvocation/invoking": "Saving receipt draft",
            "openai/toolInvocation/invoked": "Receipt draft saved",
        },
    )
    def create_receipt_draft_from_file(
        file: OpenAIFileInput,
        draft: ExpenseDraftInput,
    ) -> ReceiptCommitResult:
        def action() -> CallToolResult:
            principal = resolver.resolve()
            downloaded = RemoteReceiptDownloader(settings).download(file)
            normalized_draft = normalize_receipt_savings(draft)
            request = ReceiptCommitRequest(
                file_sha256=downloaded.sha256,
                draft=normalized_draft,
                client_request_id=f"sha256:{downloaded.sha256}",
            )
            saga: ReceiptCommitSaga | None = None
            try:
                with user_transaction(principal.user_id) as conn:
                    saga = ReceiptCommitSaga(
                        conn,
                        principal.user_id,
                        settings,
                        get_object_storage(),
                        get_upload_rate_limiter(),
                    )
                    result = saga.commit(request, downloaded)
                saga.compensation_object = None
            except Exception:
                if saga is not None and saga.compensation_object is not None:
                    try:
                        saga.compensate("database_commit_failed")
                    except Exception:
                        logger.exception("Receipt compensation failed")
                raise

            duplicate_message = (
                "This receipt is already saved. Use the returned transaction and validation."
                if result.exact_file_duplicate
                else "Receipt draft saved privately. Use the returned validation before confirmation."
            )
            return CallToolResult(
                content=[TextContent(type="text", text=duplicate_message)],
                structuredContent=result.model_dump(mode="json"),
            )

        return cast(ReceiptCommitResult, _safe(action))

    @server.tool(
        title="Save expense draft",
        description=(
            "Use this when a new or edited receipt/manual expense must be saved atomically before validation; supply "
            "a stable client_request_id and the latest revision for edits."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def save_expense_draft(payload: ExpenseDraftSaveRequest) -> MutationResult:
        def action() -> MutationResult:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return ExpenseApplicationService(conn, principal.user_id, settings).save_draft(payload)

        return _safe(action)

    @server.tool(
        title="Correct confirmed expense",
        description=(
            "Use this when the user explicitly approves a complete correction to an already confirmed "
            "expense. The correction is revision-checked, revalidated atomically, and audited with its reason."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def correct_confirmed_expense(payload: ExpenseCorrectionRequest) -> MutationResult:
        def action() -> MutationResult:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                return ExpenseApplicationService(
                    conn,
                    principal.user_id,
                    settings,
                ).correct_confirmed(payload)

        return _safe(action)

    @server.tool(
        title="Validate expense",
        description=(
            "Use this when a saved draft needs reconciliation and blocking/warning issues persisted before "
            "confirmation."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def validate_expense(transaction_id: UUID) -> ExpenseValidationResult:
        def action() -> ExpenseValidationResult:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                service = ExpenseApplicationService(conn, principal.user_id, settings)
                validation = service.validate(transaction_id)
                transaction = service.transactions.get_transaction(transaction_id)
                computed_total = (
                    transaction.total_amount - validation.reconciliation_delta_amount
                    if validation.reconciliation_delta_amount is not None
                    else None
                )
                return ExpenseValidationResult(
                    transaction_id=transaction_id,
                    reconciliation_delta_amount=validation.reconciliation_delta_amount,
                    computed_total_amount=computed_total,
                    issues=validation.issues,
                    confirmation_eligible=not has_blocking_issues(validation.issues),
                )

        return _safe(action)

    @server.tool(
        title="Confirm expense",
        description=(
            "Use this when validation has no blocking issues and the user explicitly approved converting the draft "
            "into a confirmed expense."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def confirm_expense(transaction_id: UUID, explicit_approval: bool) -> ExpenseSnapshot:
        def action() -> ExpenseSnapshot:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                service = ExpenseApplicationService(conn, principal.user_id, settings)
                service.confirm(transaction_id, explicit_approval)
                return service.get_expense(transaction_id)

        return _safe(action)

    @server.tool(
        title="Delete expense",
        description=(
            "Use this when the user explicitly requests permanent deletion of an expense and any private receipt files."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def delete_expense(transaction_id: UUID, explicit_confirmation: bool) -> OperationResult:
        def action() -> OperationResult:
            if not explicit_confirmation:
                raise ConflictError("Explicit user confirmation is required before deletion")
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                service = ReceiptFileService(
                    ReceiptRepository(conn, principal.user_id),
                    get_object_storage(),
                    get_upload_rate_limiter(),
                    settings,
                )
                deleted = service.delete_transaction(transaction_id)
            if not deleted:
                return OperationResult(
                    ok=False,
                    message=(
                        "Deletion is pending because private Storage cleanup failed. "
                        "The expense remains visible and a retryable cleanup job was recorded."
                    ),
                )
            return OperationResult(message="Expense and owned receipt files were deleted")

        return _safe(action)

    @server.tool(
        title="Get receipt download URL",
        description=(
            "Use this when an uploaded receipt needs a short-lived private download URL; the URL is returned only as "
            "hidden tool metadata."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def get_receipt_download_url(receipt_id: UUID, file_id: UUID) -> ReceiptDownloadPublic:
        def action() -> CallToolResult:
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                service = ReceiptFileService(
                    ReceiptRepository(conn, principal.user_id),
                    get_object_storage(),
                    get_upload_rate_limiter(),
                    settings,
                )
                target = service.create_download_url(receipt_id, file_id)
                public = ReceiptDownloadPublic(file_id=target.file_id, expires_at=target.expires_at)
                return _hidden_result(
                    public,
                    "Created a short-lived private receipt download URL.",
                    {"dailyExpenseTracker": {"downloadUrl": target.download_url}},
                )

        return cast(ReceiptDownloadPublic, _safe(action))

    @server.tool(
        title="Delete receipt file",
        description="Use this when the user explicitly requests deletion of one private receipt file.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def delete_receipt_file(
        receipt_id: UUID,
        file_id: UUID,
        explicit_confirmation: bool,
    ) -> OperationResult:
        def action() -> OperationResult:
            if not explicit_confirmation:
                raise ConflictError("Explicit user confirmation is required before file deletion")
            principal = resolver.resolve()
            with user_transaction(principal.user_id) as conn:
                service = ReceiptFileService(
                    ReceiptRepository(conn, principal.user_id),
                    get_object_storage(),
                    get_upload_rate_limiter(),
                    settings,
                )
                deleted = service.delete_file(receipt_id, file_id)
            if not deleted:
                return OperationResult(
                    ok=False,
                    message=(
                        "Deletion is pending because private Storage cleanup failed. "
                        "The file remains visible and a retryable cleanup job was recorded."
                    ),
                )
            return OperationResult(message="Receipt file was deleted")

        return _safe(action)

    def render_meta(invoking: str, invoked: str) -> dict[str, Any]:
        return {
            "ui": {"resourceUri": WIDGET_URI},
            "openai/outputTemplate": WIDGET_URI,
            "openai/toolInvocation/invoking": invoking,
            "openai/toolInvocation/invoked": invoked,
        }

    def resolve_app_route(route: str | None, transaction_id: UUID | None) -> tuple[str, UUID | None]:
        if transaction_id is not None:
            return route or f"/expenses/{transaction_id}", transaction_id
        resolved = route or "/overview"
        if resolved in {"/overview", "/transactions", "/prices", "/expenses/new"}:
            return resolved, None
        parts = resolved.strip("/").split("/")
        if len(parts) in {2, 3} and parts[0] == "expenses":
            try:
                resolved_id = UUID(parts[1])
            except ValueError as error:
                raise InvalidUploadError("Expense route contains an invalid transaction ID") from error
            if len(parts) == 3 and parts[2] != "review":
                raise InvalidUploadError("Unsupported expense route")
            return resolved, resolved_id
        raise InvalidUploadError("Unsupported tracker route")

    @server.tool(
        title="Open expense tracker",
        description=(
            "Use this when the user explicitly wants to open, review, edit, or browse the interactive expense "
            "tracker, manual entry, analytics, or a saved transaction. For receipt review, pass "
            "/expenses/{transaction_id}/review. Omit route and transactionId to open Overview. This is the only "
            "render tool."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        meta=render_meta("Opening expense tracker", "Expense tracker ready"),
    )
    def open_expense_tracker(
        route: str | None = None,
        transactionId: UUID | None = None,
    ) -> WidgetView:
        def action() -> CallToolResult:
            resolved_route, resolved_id = resolve_app_route(route, transactionId)
            expense = None
            data: dict[str, Any] = {}
            if resolved_id is not None:
                principal = resolver.resolve()
                with user_transaction(principal.user_id) as conn:
                    expense = ExpenseApplicationService(
                        conn,
                        principal.user_id,
                        settings,
                    ).get_expense(resolved_id)
            elif resolved_route in {"/overview", "/transactions", "/prices"}:
                try:
                    dashboard = get_expense_dashboard(ExpenseDashboardRequest())
                    data["dashboard"] = dashboard.model_dump(mode="json")
                except (RuntimeError, ValueError) as error:
                    data["dashboard_error"] = str(error)
            return _render_result(
                WidgetView(
                    route=resolved_route,
                    title="Expense Tracker",
                    expense=expense,
                    stateVersion=expense.revision if expense is not None else None,
                    data=data,
                )
            )

        return cast(WidgetView, _safe(action))

    return server
