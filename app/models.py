from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TransactionStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    VOID = "void"


class TransactionType(StrEnum):
    EXPENSE = "expense"
    REFUND = "refund"
    INCOME = "income"
    TRANSFER = "transfer"


class SourceType(StrEnum):
    RECEIPT = "receipt"
    MANUAL = "manual"
    EMAIL = "email"
    INSTACART = "instacart"
    UBER_EATS = "uber_eats"
    IMPORT = "import"


class TransactionClassificationMode(StrEnum):
    ITEMIZED = "itemized"
    WHOLE_BILL = "whole_bill"
    MIXED = "mixed"


class TransactionItemRole(StrEnum):
    PURCHASE = "purchase"
    SERVICE = "service"
    WHOLE_BILL = "whole_bill"


class IngestionMethod(StrEnum):
    MANUAL = "manual"
    RECEIPT = "receipt"
    EMAIL = "email"
    PROVIDER_API = "provider_api"
    IMPORT = "import"


class PurchaseChannel(StrEnum):
    IN_STORE = "in_store"
    ONLINE = "online"
    DELIVERY = "delivery"
    SUBSCRIPTION = "subscription"
    UNKNOWN = "unknown"


class TaxonomyClassificationSource(StrEnum):
    USER = "user"
    ALIAS = "alias"
    MODEL = "model"
    MIGRATION = "migration"


class TaxonomyReviewStatus(StrEnum):
    REVIEWED = "reviewed"
    SUGGESTED = "suggested"
    NEEDS_REVIEW = "needs_review"


class TaxonomySelectionMode(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"


class AdjustmentType(StrEnum):
    COUPON = "coupon"
    DISCOUNT = "discount"
    TAX = "tax"
    FEE = "fee"
    TIP = "tip"
    DEPOSIT = "deposit"
    REFUND = "refund"
    ROUNDING = "rounding"


class AdjustmentSubtype(StrEnum):
    BAG_FEE = "bag_fee"
    DELIVERY_FEE = "delivery_fee"
    SERVICE_FEE = "service_fee"
    OTHER_FEE = "other_fee"
    MEMBERSHIP_BENEFIT = "membership_benefit"
    DELIVERY_DISCOUNT = "delivery_discount"
    OFFER = "offer"
    OTHER_DISCOUNT = "other_discount"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class AliasSource(StrEnum):
    USER_MERCHANT = "user_merchant"
    USER_GLOBAL = "user_global"
    CURATED_GLOBAL = "curated_global"


class AnalyticsMetric(StrEnum):
    TOTAL_SPEND = "total_spend"
    PURCHASE_COUNT = "purchase_count"
    QUANTITY_PURCHASED = "quantity_purchased"
    AVERAGE_ITEM_PRICE = "average_item_price"
    DISCOUNT_TOTAL = "discount_total"
    TAX_TOTAL = "tax_total"
    FEE_TOTAL = "fee_total"
    REFUND_TOTAL = "refund_total"


class AnalyticsGrouping(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    MERCHANT = "merchant"
    CATEGORY = "category"
    CONCEPT = "concept"
    VARIANT = "variant"
    THEME = "theme"
    FACET = "facet"
    INGESTION_METHOD = "ingestion_method"
    PURCHASE_CHANNEL = "purchase_channel"
    PROVIDER = "provider"
    CURRENCY = "currency"


class ReceiptFileUploadStatus(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"
    DELETED = "deleted"


def normalize_currency(value: str) -> str:
    return value.strip().upper()


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    parent_id: UUID | None
    name: str
    depth: int
    path_slug: str
    sort_order: int
    is_assignable: bool


class Theme(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None = None


class TaxonomyResponse(BaseModel):
    categories: list[Category]
    themes: list[Theme]


class TaxonomyVersion(BaseModel):
    id: UUID
    version: str
    content_hash: str
    status: str
    level_names: list[str]
    max_depth: int


class TaxonomyPathNode(BaseModel):
    id: UUID
    stable_key: str
    level: int
    level_name: str
    name: str


class TaxonomyNode(BaseModel):
    id: UUID
    version_id: UUID
    stable_key: str
    parent_id: UUID | None
    level: int
    level_name: str
    name: str
    description: str
    sort_order: int
    is_assignable: bool
    allowed_transaction_types: list[TransactionType]
    path: list[TaxonomyPathNode]
    synonyms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaxonomyFacetValue(BaseModel):
    id: UUID
    facet_id: UUID
    stable_key: str
    name: str
    description: str
    sort_order: int


class TaxonomyFacet(BaseModel):
    id: UUID
    stable_key: str
    name: str
    description: str
    selection_mode: TaxonomySelectionMode
    values: list[TaxonomyFacetValue] = Field(default_factory=list)


class TaxonomyManifest(BaseModel):
    version: TaxonomyVersion
    roots: list[TaxonomyNode]
    assignable_nodes: list[TaxonomyNode]
    facets: list[TaxonomyFacet]


class TaxonomyBranch(BaseModel):
    root: TaxonomyNode
    nodes: list[TaxonomyNode]


class TaxonomySearchResponse(BaseModel):
    query: str
    results: list[TaxonomyNode]


class ReceiptDraft(BaseModel):
    receipt_date: date | None = None
    receipt_number: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ReceiptDraftCreate(BaseModel):
    transaction_id: UUID | None = None
    transaction_date: date = Field(default_factory=date.today)
    currency: str = "CAD"

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return normalize_currency(value)


class ReceiptRecord(BaseModel):
    id: UUID
    transaction_id: UUID
    created_at: datetime


class ReceiptFileRecord(BaseModel):
    id: UUID
    receipt_id: UUID
    storage_provider: str
    bucket_name: str
    original_filename: str
    mime_type: str
    byte_size: int | None
    sha256: str | None
    upload_status: ReceiptFileUploadStatus
    created_at: datetime
    uploaded_at: datetime | None
    deleted_at: datetime | None


class ReceiptFileDownloadUrlResponse(BaseModel):
    file_id: UUID
    download_url: str
    expires_at: datetime


class OpenAIFileInput(BaseModel):
    """OpenAI host file parameter. Empty defaults keep optional fields out of JSON Schema required."""

    model_config = ConfigDict(extra="forbid")

    download_url: str = Field(min_length=1)
    file_id: str = Field(min_length=1, max_length=512)
    mime_type: str = Field(default="", max_length=100)
    file_name: str = Field(default="", max_length=255)


class TransactionItemBase(BaseModel):
    raw_name: str | None = None
    interpreted_name: str | None = None
    normalized_name: str | None = None
    brand: str | None = Field(
        default=None,
        description=(
            "Manufacturer or store brand distinct from the generic product name "
            "(e.g. 'Tide', 'Kirkland Signature', 'Great Value'). Dairy, eggs, and other "
            "non-produce packaged food/drink almost always carry one; ask the user before "
            "finalizing the draft if it is not legible there. Leave null without asking for "
            "unbranded commodities such as most fresh produce."
        ),
    )
    concept_id: UUID | None = None
    variant_id: UUID | None = None
    taxonomy_node_key: str | None = None
    category_slug: str | None = None
    facet_value_keys: list[str] = Field(default_factory=list)
    item_role: TransactionItemRole = TransactionItemRole.PURCHASE
    classification_source: TaxonomyClassificationSource = TaxonomyClassificationSource.MODEL
    classification_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    classification_review_status: TaxonomyReviewStatus = TaxonomyReviewStatus.SUGGESTED
    theme_slugs: list[str] = Field(default_factory=list)
    quantity: Decimal | None = None
    unit: str | None = None
    measured_value: Decimal | None = Field(default=None, gt=0)
    measured_unit: str | None = None
    package_value: Decimal | None = Field(default=None, gt=0)
    package_unit: str | None = None
    unit_price_amount: Decimal | None = None
    unit_price_basis_value: Decimal | None = Field(default=None, gt=0)
    unit_price_basis_unit: str | None = None
    line_subtotal_amount: Decimal | None = None
    line_discount_amount: Decimal | None = None
    line_tax_amount: Decimal | None = None
    line_fee_amount: Decimal | None = None
    line_total_amount: Decimal
    confidence: Decimal | None = None

    @model_validator(mode="after")
    def validate_measurement_pairs(self) -> "TransactionItemBase":
        if self.taxonomy_node_key is None and self.category_slug is None:
            raise ValueError("taxonomy_node_key is required (category_slug is accepted for v1 compatibility)")
        pairs = (
            ("measured_value", self.measured_value, "measured_unit", self.measured_unit),
            ("package_value", self.package_value, "package_unit", self.package_unit),
            (
                "unit_price_basis_value",
                self.unit_price_basis_value,
                "unit_price_basis_unit",
                self.unit_price_basis_unit,
            ),
        )
        for value_name, value, unit_name, unit in pairs:
            if (value is None) != (unit is None):
                raise ValueError(f"{value_name} and {unit_name} must be supplied together")
        return self


class TransactionItemCreate(TransactionItemBase):
    pass


class TransactionItemUpdate(BaseModel):
    raw_name: str | None = None
    interpreted_name: str | None = None
    normalized_name: str | None = None
    brand: str | None = None
    concept_id: UUID | None = None
    variant_id: UUID | None = None
    category_slug: str | None = None
    taxonomy_node_key: str | None = None
    facet_value_keys: list[str] | None = None
    item_role: TransactionItemRole | None = None
    classification_source: TaxonomyClassificationSource | None = None
    classification_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    classification_review_status: TaxonomyReviewStatus | None = None
    theme_slugs: list[str] | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    measured_value: Decimal | None = Field(default=None, gt=0)
    measured_unit: str | None = None
    package_value: Decimal | None = Field(default=None, gt=0)
    package_unit: str | None = None
    unit_price_amount: Decimal | None = None
    unit_price_basis_value: Decimal | None = Field(default=None, gt=0)
    unit_price_basis_unit: str | None = None
    line_subtotal_amount: Decimal | None = None
    line_discount_amount: Decimal | None = None
    line_tax_amount: Decimal | None = None
    line_fee_amount: Decimal | None = None
    line_total_amount: Decimal | None = None
    confidence: Decimal | None = None
    correction_reason: str | None = None


class TransactionAdjustmentCreate(BaseModel):
    item_id: UUID | None = None
    type: AdjustmentType
    subtype: AdjustmentSubtype | None = None
    amount: Decimal
    description: str | None = None
    raw_label: str | None = None
    affects_total: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    correction_reason: str | None = None

    @model_validator(mode="after")
    def validate_subtype(self) -> "TransactionAdjustmentCreate":
        _validate_adjustment_subtype(self.type, self.subtype)
        return self


class TransactionAdjustmentUpdate(BaseModel):
    item_id: UUID | None = None
    type: AdjustmentType | None = None
    subtype: AdjustmentSubtype | None = None
    amount: Decimal | None = None
    description: str | None = None
    raw_label: str | None = None
    affects_total: bool | None = None
    metadata: dict[str, Any] | None = None
    correction_reason: str | None = None

    @field_validator("type", "amount")
    @classmethod
    def reject_explicit_null_required_values(cls, value: object) -> object:
        if value is None:
            raise ValueError("must not be null when supplied")
        return value

    @model_validator(mode="after")
    def validate_subtype_for_supplied_type(self) -> "TransactionAdjustmentUpdate":
        if self.type is not None:
            _validate_adjustment_subtype(self.type, self.subtype)
        return self


class TransactionDraftCreate(BaseModel):
    transaction_type: TransactionType = TransactionType.EXPENSE
    source_type: SourceType
    classification_mode: TransactionClassificationMode = TransactionClassificationMode.ITEMIZED
    ingestion_method: IngestionMethod = IngestionMethod.MANUAL
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
    adjustments: list[TransactionAdjustmentCreate] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @model_validator(mode="before")
    @classmethod
    def derive_ingestion_method(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("ingestion_method") is None:
            source = str(value.get("source_type", SourceType.MANUAL.value))
            value = {
                **value,
                "ingestion_method": {
                    SourceType.MANUAL.value: IngestionMethod.MANUAL.value,
                    SourceType.RECEIPT.value: IngestionMethod.RECEIPT.value,
                    SourceType.EMAIL.value: IngestionMethod.EMAIL.value,
                    SourceType.IMPORT.value: IngestionMethod.IMPORT.value,
                    SourceType.INSTACART.value: IngestionMethod.PROVIDER_API.value,
                    SourceType.UBER_EATS.value: IngestionMethod.PROVIDER_API.value,
                }.get(source, IngestionMethod.MANUAL.value),
            }
        return value

    @model_validator(mode="after")
    def normalize_origin_and_structure(self) -> "TransactionDraftCreate":
        if self.provider_key is None and self.source_type in {SourceType.INSTACART, SourceType.UBER_EATS}:
            self.provider_key = self.source_type.value
        if self.classification_mode == TransactionClassificationMode.WHOLE_BILL and len(self.items) > 1:
            raise ValueError("whole_bill transactions may contain at most one semantic line item")
        return self


class TransactionPatch(BaseModel):
    transaction_date: date | None = None
    merchant_name_raw: str | None = None
    merchant_name_normalized: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    currency: str | None = None
    subtotal_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    tip_amount: Decimal | None = None
    deposit_amount: Decimal | None = None
    rounding_amount: Decimal | None = None
    total_amount: Decimal | None = None
    correction_reason: str | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return normalize_currency(value) if value is not None else None


class TransactionItem(BaseModel):
    id: UUID
    raw_name: str | None
    interpreted_name: str | None
    normalized_name: str | None
    concept_id: UUID | None = None
    variant_id: UUID | None = None
    concept_name: str | None = None
    variant_name: str | None = None
    brand: str | None = None
    size_text: str | None = None
    category_id: UUID | None = None
    category_slug: str | None = None
    taxonomy_node_id: UUID | None = None
    taxonomy_node_key: str = "unclassified.needs_review"
    taxonomy_node_name: str = "Needs Review"
    taxonomy_version: str = "legacy"
    taxonomy_path: list[TaxonomyPathNode] = Field(default_factory=list)
    facet_value_keys: list[str] = Field(default_factory=list)
    item_role: TransactionItemRole = TransactionItemRole.PURCHASE
    classification_source: TaxonomyClassificationSource = TaxonomyClassificationSource.MIGRATION
    classification_confidence: Decimal | None = None
    classification_review_status: TaxonomyReviewStatus = TaxonomyReviewStatus.REVIEWED
    classification_reviewed_at: datetime | None = None
    theme_slugs: list[str] = Field(default_factory=list)
    quantity: Decimal | None
    unit: str | None
    measured_value: Decimal | None = None
    measured_unit: str | None = None
    package_value: Decimal | None = None
    package_unit: str | None = None
    unit_price_amount: Decimal | None
    unit_price_basis_value: Decimal | None = None
    unit_price_basis_unit: str | None = None
    normalized_unit: str | None = None
    normalized_unit_price_amount: Decimal | None = None
    normalized_price_is_estimated: bool = False
    line_subtotal_amount: Decimal | None
    line_discount_amount: Decimal | None
    line_tax_amount: Decimal | None
    line_fee_amount: Decimal | None
    line_total_amount: Decimal
    confidence: Decimal | None

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_taxonomy_display(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value.get("taxonomy_node_key") and value.get("category_slug"):
            key = str(value["category_slug"])
            value = {
                **value,
                "taxonomy_node_key": key,
                "taxonomy_node_name": key.rsplit(".", 1)[-1].replace("_", " ").title(),
            }
        return value


class TransactionAdjustment(BaseModel):
    id: UUID
    item_id: UUID | None
    type: AdjustmentType
    subtype: AdjustmentSubtype | None = None
    amount: Decimal
    description: str | None
    raw_label: str | None = None
    affects_total: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


FEE_SUBTYPES = {
    AdjustmentSubtype.BAG_FEE,
    AdjustmentSubtype.DELIVERY_FEE,
    AdjustmentSubtype.SERVICE_FEE,
    AdjustmentSubtype.OTHER_FEE,
}
DISCOUNT_SUBTYPES = {
    AdjustmentSubtype.MEMBERSHIP_BENEFIT,
    AdjustmentSubtype.DELIVERY_DISCOUNT,
    AdjustmentSubtype.OFFER,
    AdjustmentSubtype.OTHER_DISCOUNT,
}


def _validate_adjustment_subtype(
    adjustment_type: AdjustmentType,
    subtype: AdjustmentSubtype | None,
) -> None:
    if subtype is None:
        return
    if adjustment_type == AdjustmentType.FEE and subtype in FEE_SUBTYPES:
        return
    if adjustment_type in {AdjustmentType.COUPON, AdjustmentType.DISCOUNT} and subtype in DISCOUNT_SUBTYPES:
        return
    raise ValueError(f"Subtype {subtype.value} is not valid for adjustment type {adjustment_type.value}")


class ValidationIssue(BaseModel):
    id: UUID | None = None
    transaction_id: UUID | None = None
    item_id: UUID | None = None
    severity: ValidationSeverity
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransactionDetail(BaseModel):
    id: UUID
    transaction_type: TransactionType
    source_type: SourceType
    classification_mode: TransactionClassificationMode = TransactionClassificationMode.ITEMIZED
    ingestion_method: IngestionMethod = IngestionMethod.MANUAL
    purchase_channel: PurchaseChannel = PurchaseChannel.UNKNOWN
    provider_key: str | None = None
    status: TransactionStatus
    transaction_date: date
    merchant_name_raw: str | None
    merchant_name_normalized: str | None
    notes: str | None = None
    currency: str
    subtotal_amount: Decimal | None
    tax_amount: Decimal | None
    fee_amount: Decimal | None
    discount_amount: Decimal | None
    tip_amount: Decimal | None
    deposit_amount: Decimal | None
    rounding_amount: Decimal | None
    total_amount: Decimal
    reconciliation_delta_amount: Decimal | None
    confirmed_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[TransactionItem] = Field(default_factory=list)
    adjustments: list[TransactionAdjustment] = Field(default_factory=list)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    transaction_id: UUID
    reconciliation_delta_amount: Decimal | None
    issues: list[ValidationIssue]


class AliasResolveItem(BaseModel):
    raw_name: str


class AliasResolveRequest(BaseModel):
    merchant_normalized: str | None = None
    items: list[AliasResolveItem]


class AliasResolution(BaseModel):
    raw_name: str
    raw_name_normalized: str
    source: AliasSource | None = None
    category_id: UUID | None = None
    category_slug: str | None = None
    taxonomy_node_id: UUID | None = None
    taxonomy_node_key: str | None = None
    concept_id: UUID | None = None
    variant_id: UUID | None = None
    unresolved: bool


class AliasResolveResponse(BaseModel):
    resolutions: list[AliasResolution]


class AnalyticsFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    relative_days: int | None = Field(default=None, ge=1, le=3660)
    merchant: str | None = Field(default=None, min_length=1, max_length=255)
    category_slug: str | None = Field(default=None, min_length=1, max_length=100)
    taxonomy_node_key: str | None = Field(default=None, min_length=1, max_length=512)
    include_descendants: bool = True
    product_concept_id: UUID | None = None
    product_variant_id: UUID | None = None
    theme_slug: str | None = Field(default=None, min_length=1, max_length=100)
    facet_value_key: str | None = Field(default=None, min_length=1, max_length=160)
    source_type: SourceType | None = None
    ingestion_method: IngestionMethod | None = None
    purchase_channel: PurchaseChannel | None = None
    provider_key: str | None = Field(default=None, min_length=1, max_length=100)
    transaction_type: TransactionType | None = None
    currency: str | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return normalize_currency(value) if value is not None else None

    @model_validator(mode="after")
    def validate_date_range(self) -> "AnalyticsFilters":
        if self.relative_days is not None and (self.start_date is not None or self.end_date is not None):
            raise ValueError("relative_days cannot be combined with start_date or end_date")
        if self.start_date is not None and self.end_date is not None and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class AnalyticsQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[AnalyticsMetric] = Field(min_length=1)
    group_by: list[AnalyticsGrouping] = Field(default_factory=list, max_length=3)
    category_rollup_depth: int | None = Field(default=2, ge=0, le=5)
    taxonomy_rollup_level: int | None = Field(default=None, ge=1, le=6)
    filters: AnalyticsFilters = Field(default_factory=AnalyticsFilters)

    @field_validator("metrics", "group_by")
    @classmethod
    def reject_duplicate_values(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate values are not allowed")
        return values


class AnalyticsRow(BaseModel):
    dimensions: dict[str, str | date | None]
    metrics: dict[str, Decimal]


class AnalyticsQueryResponse(BaseModel):
    rows: list[AnalyticsRow]
    confirmed_only: bool = True


class TransactionSummary(BaseModel):
    id: UUID
    transaction_type: TransactionType
    source_type: SourceType
    classification_mode: TransactionClassificationMode = TransactionClassificationMode.ITEMIZED
    ingestion_method: IngestionMethod = IngestionMethod.MANUAL
    purchase_channel: PurchaseChannel = PurchaseChannel.UNKNOWN
    provider_key: str | None = None
    status: TransactionStatus
    transaction_date: date
    merchant_name_raw: str | None
    merchant_name_normalized: str | None
    currency: str
    total_amount: Decimal
    confirmed_at: datetime | None
    item_count: int = 0


class TransactionListResponse(BaseModel):
    transactions: list[TransactionSummary]
    total: int
    limit: int
    offset: int


class TransactionListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TransactionStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    merchant: str | None = Field(default=None, min_length=1, max_length=255)
    category_slug: str | None = Field(default=None, min_length=1, max_length=100)
    taxonomy_node_key: str | None = Field(default=None, min_length=1, max_length=512)
    include_descendants: bool = True
    source_type: SourceType | None = None
    ingestion_method: IngestionMethod | None = None
    purchase_channel: PurchaseChannel | None = None
    provider_key: str | None = Field(default=None, min_length=1, max_length=100)
    transaction_type: TransactionType | None = None
    currency: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_date_range(self) -> "TransactionListFilters":
        if self.start_date is not None and self.end_date is not None and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return normalize_currency(value) if value is not None else None
