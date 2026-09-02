from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    AdjustmentSubtype,
    AdjustmentType,
    Category,
    IngestionMethod,
    PurchaseChannel,
    ReceiptDraft,
    ReceiptFileRecord,
    ReceiptRecord,
    SourceType,
    TaxonomyFacet,
    TaxonomyNode,
    TaxonomyVersion,
    Theme,
    TransactionAdjustmentCreate,
    TransactionClassificationMode,
    TransactionDetail,
    TransactionDraftCreate,
    TransactionItemCreate,
    TransactionSummary,
    TransactionType,
    ValidationIssue,
    normalize_currency,
)


class ExpenseDraftAdjustment(BaseModel):
    """Draft adjustment with a stable item position instead of a database ID."""

    item_index: int | None = Field(default=None, ge=0)
    type: AdjustmentType
    subtype: AdjustmentSubtype | None = None
    amount: Decimal
    description: str | None = None
    raw_label: str | None = None
    affects_total: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_subtype(self) -> ExpenseDraftAdjustment:
        TransactionAdjustmentCreate(
            type=self.type,
            subtype=self.subtype,
            amount=self.amount,
            description=self.description,
            raw_label=self.raw_label,
            affects_total=self.affects_total,
            metadata=self.metadata,
        )
        return self


class ExpenseDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_type: TransactionType = TransactionType.EXPENSE
    source_type: SourceType
    classification_mode: TransactionClassificationMode = TransactionClassificationMode.ITEMIZED
    ingestion_method: IngestionMethod | None = None
    purchase_channel: PurchaseChannel = PurchaseChannel.UNKNOWN
    provider_key: str | None = Field(default=None, max_length=100)
    transaction_date: date
    merchant_name_raw: str | None = None
    merchant_name_normalized: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    currency: str = "CAD"
    subtotal_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    tip_amount: Decimal | None = None
    deposit_amount: Decimal | None = None
    rounding_amount: Decimal | None = None
    total_amount: Decimal
    receipt: ReceiptDraft | None = None
    items: list[TransactionItemCreate] = Field(default_factory=list)
    adjustments: list[ExpenseDraftAdjustment] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return normalize_currency(value)

    def transaction_payload(self) -> TransactionDraftCreate:
        return TransactionDraftCreate(
            **self.model_dump(exclude={"adjustments"}),
            adjustments=[],
        )


class ExpenseDraftSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: ExpenseDraftInput
    transaction_id: UUID | None = None
    expected_revision: datetime | None = None
    client_request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class ExpenseCorrectionRequest(BaseModel):
    """Explicit, audited replacement of a confirmed expense."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    expected_revision: datetime
    draft: ExpenseDraftInput
    correction_reason: str = Field(min_length=3, max_length=500)
    explicit_approval: bool
    client_request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class ReceiptSnapshot(BaseModel):
    receipt: ReceiptRecord
    files: list[ReceiptFileRecord]


class ExpenseSnapshot(BaseModel):
    transaction: TransactionDetail
    receipt: ReceiptSnapshot | None = None

    @property
    def revision(self) -> str | None:
        if self.transaction.updated_at is None:
            return None
        return self.transaction.updated_at.isoformat()


class MutationResult(BaseModel):
    expense: ExpenseSnapshot
    idempotent_replay: bool = False


class ExplicitApproval(BaseModel):
    explicit_approval: bool = Field(
        description="Must be true only after the user explicitly approved this irreversible action."
    )


class WidgetView(BaseModel):
    route: str
    title: str
    expense: ExpenseSnapshot | None = None
    validation: ExpenseValidationResult | None = None
    stateVersion: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ReceiptDownloadPublic(BaseModel):
    file_id: UUID
    expires_at: datetime


class OperationResult(BaseModel):
    ok: bool = True
    message: str


class ReceiptFileRequirements(BaseModel):
    allowed_mime_types: list[str]
    max_file_bytes: int


class ExpenseTaxonomy(BaseModel):
    version: TaxonomyVersion
    roots: list[TaxonomyNode]
    assignable_nodes: list[TaxonomyNode]
    facets: list[TaxonomyFacet]
    # Compatibility aliases for v1 clients; do not use for new classifications.
    categories: list[Category]
    themes: list[Theme]
    adjustment_types: list[AdjustmentType]
    supported_currencies: list[str]
    receipt_files: ReceiptFileRequirements


class ExpenseValidationResult(BaseModel):
    transaction_id: UUID
    reconciliation_delta_amount: Decimal | None
    computed_total_amount: Decimal | None
    issues: list[ValidationIssue]
    confirmation_eligible: bool


class DashboardPeriod(StrEnum):
    MONTH = "month"
    THIRTY_DAYS = "30d"
    NINETY_DAYS = "90d"
    YEAR = "year"


class ExpenseDashboardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: DashboardPeriod = DashboardPeriod.MONTH
    recent_limit: int = Field(default=8, ge=1, le=25)
    category_limit: int = Field(default=12, ge=1, le=30)
    price_change_limit: int = Field(default=12, ge=0, le=30)


class DashboardWindow(BaseModel):
    label: str
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date


class CurrencySpend(BaseModel):
    currency: str
    current_amount: Decimal
    previous_amount: Decimal
    delta_amount: Decimal
    delta_percent: Decimal | None = None


class CategorySpend(BaseModel):
    category_slug: str
    category_name: str
    taxonomy_level: int = 2
    taxonomy_level_name: str = "Group"
    has_children: bool = True
    currency: str
    current_amount: Decimal
    previous_amount: Decimal
    delta_percent: Decimal | None = None
    share_percent: Decimal


class MerchantBreakdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: DashboardPeriod = DashboardPeriod.MONTH
    currency: str = Field(min_length=3, max_length=3)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("currency")
    @classmethod
    def uppercase_merchant_currency(cls, value: str) -> str:
        return normalize_currency(value)


class MerchantSpend(BaseModel):
    merchant_name: str
    currency: str
    current_amount: Decimal
    previous_amount: Decimal
    delta_percent: Decimal | None = None
    share_percent: Decimal
    visit_count: int
    average_amount: Decimal


class MerchantBreakdownResponse(BaseModel):
    window: DashboardWindow
    currency: str
    merchants: list[MerchantSpend] = Field(default_factory=list)


class SpendTrendPoint(BaseModel):
    period_start: date
    label: str
    currency: str
    amount: Decimal


class DailySpend(BaseModel):
    spend_date: date
    currency: str
    amount: Decimal
    transaction_count: int


class PriceChange(BaseModel):
    identity_key: str
    label: str
    taxonomy_key: str | None = None
    currency: str
    normalized_unit: str
    current_price: Decimal
    previous_price: Decimal | None = None
    delta_amount: Decimal | None = None
    delta_percent: Decimal | None = None
    current_date: date
    previous_date: date | None = None
    current_merchant: str | None = None
    previous_merchant: str | None = None
    best_price: Decimal
    best_date: date
    sample_size: int
    best_merchant: str | None = None
    best_quantity_label: str | None = None
    comparison_price: Decimal | None = None
    comparison_merchant: str | None = None
    savings_amount: Decimal = Decimal("0")
    savings_percent: Decimal = Decimal("0")
    recent_prices: list[Decimal] = Field(default_factory=list)


class DashboardInsight(BaseModel):
    kind: str
    title: str
    detail: str
    tone: str = "neutral"


class ExpenseDashboard(BaseModel):
    display_name: str | None = None
    default_currency: str
    window: DashboardWindow
    totals: list[CurrencySpend]
    categories: list[CategorySpend]
    spend_trend: list[SpendTrendPoint] = Field(default_factory=list)
    daily_spend: list[DailySpend] = Field(default_factory=list)
    insights: list[DashboardInsight]
    recent_transactions: list[TransactionSummary]
    needs_review_count: int
    price_changes: list[PriceChange]
    confirmed_only: bool = True


class ItemPriceHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_key: str = Field(
        min_length=6,
        max_length=320,
        pattern=r"^(product|variant|concept|name|basket):.+$",
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    normalized_unit: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Disambiguates a 'product' identity_key that spans more than one unit "
            "(e.g. croissants sold both by weight and by count) to the exact series "
            "that was clicked, rather than an arbitrary one of the matching series."
        ),
    )
    limit: int = Field(default=24, ge=2, le=100)

    @field_validator("currency")
    @classmethod
    def uppercase_history_currency(cls, value: str | None) -> str | None:
        return normalize_currency(value) if value is not None else None

    @model_validator(mode="after")
    def validate_identity_value(self) -> ItemPriceHistoryRequest:
        identity_type, value = self.identity_key.split(":", 1)
        if identity_type in {"variant", "concept"}:
            try:
                UUID(value)
            except ValueError as error:
                raise ValueError(f"{identity_type} identity must contain a UUID") from error
        elif not value.strip():
            raise ValueError(f"{identity_type} identity must not be blank")
        return self


class ItemPricePoint(BaseModel):
    transaction_id: UUID
    transaction_item_id: UUID
    transaction_date: date
    merchant_name: str | None
    display_name: str
    currency: str
    normalized_unit: str
    normalized_unit_price_amount: Decimal
    is_estimated: bool = Field(
        default=False,
        description=(
            "True when normalized_unit_price_amount came from a bare quantity with no "
            "captured unit, printed basis, or package size - treat price comparisons "
            "involving this point with caution, it may be a multi-count pack priced as one."
        ),
    )
    quantity: Decimal | None = None
    unit: str | None = None
    measured_value: Decimal | None = None
    measured_unit: str | None = None
    package_value: Decimal | None = None
    package_unit: str | None = None
    line_total_amount: Decimal


class ItemPriceSeries(BaseModel):
    currency: str
    normalized_unit: str
    points: list[ItemPricePoint]


class KnownItemMatch(BaseModel):
    normalized_name: str
    brand: str | None
    taxonomy_key: str | None
    taxonomy_name: str | None
    purchase_count: int
    last_purchased: date
    last_merchant: str | None


class SearchKnownItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=15, ge=1, le=50)


class SearchKnownItemsResponse(BaseModel):
    query: str
    items: list[KnownItemMatch]


class PersonalBasketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def uppercase_basket_currency(cls, value: str) -> str:
        return normalize_currency(value)


class BasketProduct(BaseModel):
    identity_key: str
    label: str
    merchant_name: str | None = None
    currency: str
    normalized_unit: str
    baseline_price: Decimal
    baseline_date: date
    current_price: Decimal
    current_date: date
    delta_percent: Decimal
    spend_amount: Decimal
    purchase_count: int


class PersonalBasketIndex(BaseModel):
    currency: str
    window_days: int
    overall_delta_percent: Decimal | None = None
    product_count: int
    total_tracked_spend: Decimal
    covered_spend: Decimal
    coverage_percent: Decimal
    confidence: str
    products: list[BasketProduct] = Field(default_factory=list)


class ItemPriceHistory(BaseModel):
    identity_key: str
    label: str
    series: list[ItemPriceSeries]


class NutritionQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=15, ge=1, le=50)


class NutritionQueueItem(BaseModel):
    id: UUID
    product_name: str
    brand: str | None = None


class NutritionQueueResponse(BaseModel):
    enqueued: int
    expired: int = 0
    items: list[NutritionQueueItem]


class NutritionLookupMatch(BaseModel):
    id: UUID
    product_name: str
    brand: str | None = None
    status: str
    category_slug: str | None = None
    matched_product_name: str | None = None
    source: str | None = None
    nutriscore_grade: str | None = None
    attempts: int


class SearchNutritionLookupsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=15, ge=1, le=50)


class SearchNutritionLookupsResponse(BaseModel):
    query: str
    items: list[NutritionLookupMatch]


ROUNDING_TOLERANCE_G = 0.5


class NutrimentsInput(BaseModel):
    """Values exactly as the source states them, in their natural label units (kcal, g,
    mg) - never pre-converted by the caller. `basis` says what amount those values are
    for; per-100g is stored as-is, per-serving is normalized server-side using
    serving_size_g, since that conversion is exact arithmetic on grounded numbers and
    code does it more reliably than asking a model to do it inline."""

    model_config = ConfigDict(extra="forbid")

    basis: Literal["per_100g", "per_serving"]
    serving_size_g: float | None = Field(default=None, gt=0)
    serving_label: str | None = Field(default=None, max_length=100)
    energy_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    trans_fat_g: float | None = None
    carbohydrates_g: float | None = None
    sugars_g: float | None = None
    added_sugars_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None
    cholesterol_mg: float | None = None
    potassium_mg: float | None = None
    calcium_mg: float | None = None
    iron_mg: float | None = None

    @model_validator(mode="after")
    def validate_serving_basis(self) -> NutrimentsInput:
        if self.basis == "per_serving" and self.serving_size_g is None:
            raise ValueError("serving_size_g is required when basis is per_serving")
        return self

    @model_validator(mode="after")
    def validate_macro_consistency(self) -> NutrimentsInput:
        # A part can't exceed its whole - these are arithmetic facts, not source
        # disagreements, so a violation means a misread or mismatched source value.
        # ROUNDING_TOLERANCE_G absorbs legitimate label rounding (e.g. "5g sugars"
        # on a "5g carbs" line where the true values are 4.6 and 4.8).
        for part, whole, part_label, whole_label in (
            (self.sugars_g, self.carbohydrates_g, "sugars_g", "carbohydrates_g"),
            (self.added_sugars_g, self.sugars_g, "added_sugars_g", "sugars_g"),
            (self.saturated_fat_g, self.fat_g, "saturated_fat_g", "fat_g"),
            (self.trans_fat_g, self.fat_g, "trans_fat_g", "fat_g"),
        ):
            if part is not None and whole is not None and part > whole + ROUNDING_TOLERANCE_G:
                raise ValueError(f"{part_label} ({part}) cannot exceed {whole_label} ({whole})")
        return self

    def to_per_100g(self) -> dict[str, float]:
        factor = 1.0 if self.basis == "per_100g" else 100.0 / self.serving_size_g  # type: ignore[operator]
        fields = {
            "energy_kcal_100g": self.energy_kcal,
            "protein_100g": self.protein_g,
            "fat_100g": self.fat_g,
            "saturated_fat_100g": self.saturated_fat_g,
            "trans_fat_100g": self.trans_fat_g,
            "carbohydrates_100g": self.carbohydrates_g,
            "sugars_100g": self.sugars_g,
            "added_sugars_100g": self.added_sugars_g,
            "fiber_100g": self.fiber_g,
            "sodium_mg_100g": self.sodium_mg,
            "cholesterol_mg_100g": self.cholesterol_mg,
            "potassium_mg_100g": self.potassium_mg,
            "calcium_mg_100g": self.calcium_mg,
            "iron_mg_100g": self.iron_mg,
        }
        return {key: round(value * factor, 4) for key, value in fields.items() if value is not None}


NUTRISCORE_REQUIRED_FIELDS = ("energy_kcal", "sugars_g", "saturated_fat_g", "sodium_mg", "fiber_g", "protein_g")
# compute_nutriscore() needs every one of the 6 fields, not a subset - a lower bar here
# just meant "matched" items that could never actually be scored (letting partial data
# through silently produced grade=None downstream). Require all 6 unless the source
# stated a grade directly, so a thin match is rejected up front instead of accepted
# and left permanently ungraded.
MIN_NUTRISCORE_FIELDS_PRESENT = len(NUTRISCORE_REQUIRED_FIELDS)


class NutritionResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    matched: bool
    product_name: str | None = None
    source: str | None = Field(default=None, max_length=100)
    source_ref: str | None = Field(default=None, max_length=2000)
    nutriments: NutrimentsInput | None = None
    nutriscore_grade: Literal["a", "b", "c", "d", "e"] | None = None
    nova_group: int | None = Field(default=None, ge=1, le=4)
    nova_group_estimated: bool = False
    fvl_percent: float | None = Field(default=None, ge=0, le=100)
    contains_nonnutritive_sweeteners: bool = Field(
        default=False,
        description=(
            "Beverages only: whether the source's ingredient list states a non-nutritive "
            "sweetener (e.g. aspartame, sucralose, stevia) is present. Adds a fixed penalty "
            "in the beverage Nutri-Score algorithm; ignored for every other category."
        ),
    )
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_matched_has_provenance(self) -> NutritionResultInput:
        if self.matched and (not self.product_name or not self.source):
            raise ValueError("A matched result requires product_name and source for traceability")
        return self

    @model_validator(mode="after")
    def validate_nova_estimation_flag(self) -> NutritionResultInput:
        if self.nova_group_estimated and self.nova_group is None:
            raise ValueError("nova_group_estimated requires nova_group to be set")
        return self

    @model_validator(mode="after")
    def validate_matched_has_enough_data_to_score(self) -> NutritionResultInput:
        if not self.matched:
            return self
        present = (
            sum(1 for field in NUTRISCORE_REQUIRED_FIELDS if getattr(self.nutriments, field) is not None)
            if self.nutriments is not None
            else 0
        )
        if present < MIN_NUTRISCORE_FIELDS_PRESENT and self.nutriscore_grade is None:
            raise ValueError(
                f"A matched result needs either a source-stated nutriscore_grade or at least "
                f"{MIN_NUTRISCORE_FIELDS_PRESENT} of the 6 core macros used to compute a score "
                f"(energy, sugars, saturated fat, sodium, fiber, protein) - only {present} were "
                "reported and no grade was stated, so this result can't be scored either way. "
                "Keep searching for a more complete source, or report a no-match instead."
            )
        return self


class NutritionResultResponse(BaseModel):
    ok: bool = True
    status: str


class NutritionSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: DashboardPeriod = DashboardPeriod.MONTH
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def uppercase_nutrition_currency(cls, value: str) -> str:
        return normalize_currency(value)


class NutritionItem(BaseModel):
    transaction_item_id: UUID
    identity_key: str
    display_name: str
    brand: str | None = None
    status: Literal["pending", "matched", "no_match", "error"]
    purchase_count: int = 1
    nutriscore_grade: str | None = None
    nutriscore_source: Literal["computed", "source_stated"] | None = None
    nova_group: int | None = None
    nova_group_estimated: bool = False
    source: str | None = None
    source_ref: str | None = None
    spend_amount: Decimal
    energy_kcal_100g: float | None = None
    protein_100g: float | None = None
    fat_100g: float | None = None
    saturated_fat_100g: float | None = None
    trans_fat_100g: float | None = None
    carbohydrates_100g: float | None = None
    sugars_100g: float | None = None
    added_sugars_100g: float | None = None
    fiber_100g: float | None = None
    sodium_mg_100g: float | None = None
    cholesterol_mg_100g: float | None = None
    potassium_mg_100g: float | None = None
    calcium_mg_100g: float | None = None
    iron_mg_100g: float | None = None
    serving_size_g: Decimal | None = None
    serving_label: str | None = None


class NutritionCategoryGroup(BaseModel):
    category_slug: str
    category_name: str
    items: list[NutritionItem] = Field(default_factory=list)


class NutritionGradeBucket(BaseModel):
    grade: str
    spend_amount: Decimal
    share_percent: Decimal


class NutritionSignal(BaseModel):
    kind: str
    title: str
    detail: str
    tone: Literal["neutral", "warn"] = "neutral"


class NutritionSummary(BaseModel):
    window: DashboardWindow
    currency: str
    overall_grade: str | None = None
    matched_item_count: int
    total_item_count: int
    coverage_percent: Decimal
    confidence: Literal["high", "low"]
    grade_distribution: list[NutritionGradeBucket] = Field(default_factory=list)
    signals: list[NutritionSignal] = Field(default_factory=list)
    groups: list[NutritionCategoryGroup] = Field(default_factory=list)


class UsdaFoodCandidate(BaseModel):
    """One candidate from USDA FoodData Central, already unit-normalized to this app's
    per-100g fields. nutrients_per_100g is null (with data_quality_warning explaining
    why) when the source's own reported macros are internally inconsistent - the same
    NutrimentsInput validators used at save time reject that data here too, so a bad
    candidate can't be handed to the caller looking valid."""

    fdc_id: int
    description: str
    data_type: str
    brand_owner: str | None = None
    brand_name: str | None = None
    gtin_upc: str | None = None
    ingredients: str | None = None
    serving_size: float | None = None
    serving_size_unit: str | None = None
    nutrients_per_100g: NutrimentsInput | None = None
    data_quality_warning: str | None = None
    source_url: str


class UsdaFoodSearchResponse(BaseModel):
    total_hits: int
    candidates: list[UsdaFoodCandidate] = Field(default_factory=list)


class OpenFoodFactsCandidate(BaseModel):
    """One candidate from Open Food Facts, already unit-normalized to this app's
    per-100g fields (Open Food Facts itself reports sodium/cholesterol/potassium/
    calcium/iron in grams per 100g, not milligrams - converted here). Same
    data_quality_warning behavior as UsdaFoodCandidate."""

    barcode: str
    product_name: str | None = None
    brands: str | None = None
    quantity: str | None = None
    serving_size: str | None = None
    nutrition_data_per: str | None = None
    nutriscore_grade: str | None = None
    nova_group: int | None = None
    nutrients_per_100g: NutrimentsInput | None = None
    data_quality_warning: str | None = None
    source_url: str


class OpenFoodFactsSearchResponse(BaseModel):
    total_hits: int
    candidates: list[OpenFoodFactsCandidate] = Field(default_factory=list)


# "claimed" is an in-progress placeholder written by claim_email_for_processing, never a
# valid input to record_email_processed - see TerminalEmailIngestionStatus below.
EmailIngestionStatus = Literal["claimed", "drafted", "flagged", "not_a_receipt"]
TerminalEmailIngestionStatus = Literal["drafted", "flagged", "not_a_receipt"]


class CheckEmailProcessedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=512)


class EmailIngestionRecord(BaseModel):
    status: EmailIngestionStatus
    transaction_id: UUID | None = None
    note: str | None = None
    processed_at: datetime


class CheckEmailProcessedResponse(BaseModel):
    message_id: str
    processed: bool
    record: EmailIngestionRecord | None = None


class ClaimEmailForProcessingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=512)


class ClaimEmailForProcessingResponse(BaseModel):
    """claimed=True means this call owns the message_id and should proceed to process it,
    then call record_email_processed. claimed=False means another attempt already holds
    it (a finished result, or a claim from within the last hour) - skip it this run."""

    message_id: str
    claimed: bool


class RecordEmailProcessedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=512)
    status: TerminalEmailIngestionStatus
    transaction_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_status_has_its_required_field(self) -> RecordEmailProcessedRequest:
        if self.status == "drafted" and self.transaction_id is None:
            raise ValueError("status 'drafted' requires transaction_id - which transaction was saved?")
        if self.status == "flagged" and not (self.note and self.note.strip()):
            raise ValueError("status 'flagged' requires a non-empty note explaining why")
        return self


class CheckEmailsProcessedRequest(BaseModel):
    """Batch form of CheckEmailProcessedRequest - one round-trip for an entire inbox
    listing instead of one call per message, since most of a mature inbox's top-25 by
    recency is already-processed mail on every run, not new receipts."""

    model_config = ConfigDict(extra="forbid")

    message_ids: list[str] = Field(min_length=1, max_length=25)


class CheckEmailsProcessedResponse(BaseModel):
    results: list[CheckEmailProcessedResponse]
