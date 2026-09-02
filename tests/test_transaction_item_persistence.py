from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from app.models import (
    TaxonomyReviewStatus,
    TransactionItemCreate,
    TransactionItemUpdate,
    TransactionStatus,
    TransactionType,
)
from app.repositories import TaxonomyRepository, TransactionRepository

USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TRANSACTION_ID = UUID("55555555-5555-5555-5555-555555555555")
ITEM_ID = UUID("77777777-7777-7777-7777-777777777777")
TAXONOMY_NODE_ID = UUID("88888888-8888-8888-8888-888888888888")


class FakeResult:
    def fetchone(self) -> dict[str, UUID]:
        return {"id": ITEM_ID}


class RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        return FakeResult()


class ItemInsertRepository(TransactionRepository):
    def get_transaction(self, transaction_id: UUID) -> Any:
        assert transaction_id == TRANSACTION_ID
        return SimpleNamespace(
            status=TransactionStatus.DRAFT,
            transaction_type=TransactionType.EXPENSE,
        )

    def validate_product_references(
        self,
        concept_id: UUID | None,
        variant_id: UUID | None,
    ) -> tuple[UUID | None, UUID | None]:
        return concept_id, variant_id

    def replace_item_themes(self, item_id: UUID, theme_slugs: list[str]) -> None:
        pass

    def replace_item_facets(
        self,
        item_id: UUID,
        facet_value_keys: list[str],
        *,
        source: str,
        confidence: Decimal | None,
    ) -> None:
        pass

    def touch_transaction(self, transaction_id: UUID) -> None:
        pass

    def clear_validation_issues(self, transaction_id: UUID) -> None:
        pass

    def add_audit_event(
        self,
        entity_type: str,
        entity_id: UUID,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        pass

    def get_item(self, transaction_id: UUID, item_id: UUID) -> Any:
        return SimpleNamespace(id=item_id)


@pytest.mark.parametrize(
    ("review_status", "expects_reviewed_at"),
    [
        (TaxonomyReviewStatus.REVIEWED, True),
        (TaxonomyReviewStatus.SUGGESTED, False),
    ],
)
def test_add_item_binds_review_timestamp_without_reusing_enum_parameter(
    monkeypatch: pytest.MonkeyPatch,
    review_status: TaxonomyReviewStatus,
    expects_reviewed_at: bool,
) -> None:
    monkeypatch.setattr(
        TaxonomyRepository,
        "resolve_assignable_node_id",
        lambda self, stable_key, transaction_type: TAXONOMY_NODE_ID,
    )
    monkeypatch.setattr(
        TaxonomyRepository,
        "legacy_category_id_for_node",
        lambda self, taxonomy_node_id: None,
    )
    connection = RecordingConnection()
    repository = ItemInsertRepository(connection, USER_ID)

    repository.add_item(
        TRANSACTION_ID,
        TransactionItemCreate(
            raw_name="Milk",
            taxonomy_node_key="food_dining.groceries.dairy_eggs.milk.fresh_milk",
            classification_review_status=review_status,
            quantity=Decimal("1"),
            unit="item",
            line_total_amount=Decimal("4.99"),
        ),
    )

    sql, params = connection.calls[0]
    assert "%(classification_reviewed_at)s" in sql
    assert "case when %(classification_review_status)s" not in sql.lower()
    assert params["classification_review_status"] == review_status.value
    if expects_reviewed_at:
        assert isinstance(params["classification_reviewed_at"], datetime)
    else:
        assert params["classification_reviewed_at"] is None


def test_add_item_binds_brand_as_a_real_insert_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        TaxonomyRepository,
        "resolve_assignable_node_id",
        lambda self, stable_key, transaction_type: TAXONOMY_NODE_ID,
    )
    monkeypatch.setattr(
        TaxonomyRepository,
        "legacy_category_id_for_node",
        lambda self, taxonomy_node_id: None,
    )
    connection = RecordingConnection()
    repository = ItemInsertRepository(connection, USER_ID)

    repository.add_item(
        TRANSACTION_ID,
        TransactionItemCreate(
            raw_name="Tide Liquid Detergent",
            brand="Tide",
            taxonomy_node_key="housing_utilities.household_operations.laundry_supplies",
            quantity=Decimal("1"),
            unit="item",
            line_total_amount=Decimal("12.99"),
        ),
    )

    sql, params = connection.calls[0]
    assert "brand" in sql
    assert "%(brand)s" in sql
    assert params["brand"] == "Tide"


def test_add_item_leaves_brand_null_when_not_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        TaxonomyRepository,
        "resolve_assignable_node_id",
        lambda self, stable_key, transaction_type: TAXONOMY_NODE_ID,
    )
    monkeypatch.setattr(
        TaxonomyRepository,
        "legacy_category_id_for_node",
        lambda self, taxonomy_node_id: None,
    )
    connection = RecordingConnection()
    repository = ItemInsertRepository(connection, USER_ID)

    repository.add_item(
        TRANSACTION_ID,
        TransactionItemCreate(
            raw_name="Gala Apples",
            taxonomy_node_key="food_dining.groceries.produce.fruit.apples_pears",
            quantity=Decimal("1"),
            unit="kg",
            line_total_amount=Decimal("4.99"),
        ),
    )

    _sql, params = connection.calls[0]
    assert params["brand"] is None


def test_update_item_diff_picks_up_brand_as_a_plain_scalar_column() -> None:
    connection = RecordingConnection()
    repository = ItemInsertRepository(connection, USER_ID)

    repository.update_item(
        TRANSACTION_ID,
        ITEM_ID,
        TransactionItemUpdate(brand="Kirkland Signature"),
    )

    sql, params = connection.calls[0]
    assert "brand = %(brand)s" in sql
    assert params["brand"] == "Kirkland Signature"
