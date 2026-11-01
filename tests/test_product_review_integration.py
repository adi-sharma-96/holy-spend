import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.dashboard import DashboardRepository
from app.errors import ConflictError, NotFoundError, ValidationReferenceError
from app.models import TransactionDraftCreate, TransactionItemCreate, TransactionItemUpdate
from app.plugin_models import ItemPriceHistoryRequest
from app.product_evidence import readiness_reasons
from app.product_review import (
    ProductReviewRepository,
    ReviewDecisionRequest,
    ReviewPatch,
    ReviewPreviewRequest,
    ReviewReverseRequest,
)
from app.repositories import TransactionRepository

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
RUNTIME_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL or not RUNTIME_URL, reason="Disposable PostgreSQL URLs required")


def _user(conn: Any, user_id: UUID) -> None:
    conn.execute(
        "insert into auth.users (id, aud, role, email, created_at, updated_at) "
        "values (%s, 'authenticated', 'authenticated', %s, now(), now())",
        (user_id, f"{user_id}@example.test"),
    )
    conn.execute("insert into profiles (id, default_currency) values (%s, 'CAD')", (user_id,))


def _item(conn: Any, user_id: UUID, *, raw_name: str) -> tuple[UUID, UUID]:
    tx = conn.execute(
        """insert into transactions (user_id, transaction_type, source_type, ingestion_method,
                                     transaction_date, currency, total_amount, status, confirmed_at)
           values (%s, 'expense', 'manual', 'manual', current_date, 'CAD', 5, 'confirmed', now()) returning id""",
        (user_id,),
    ).fetchone()["id"]
    item = conn.execute(
        """insert into transaction_items
           (user_id, transaction_id, raw_name, normalized_name, brand, taxonomy_node_id,
            quantity, unit, normalized_unit, normalized_unit_price_amount, line_total_amount)
           select %s, %s, %s, %s, null, id, 1, 'each', 'each', 5, 5
           from taxonomy_nodes where stable_key =
           'food_dining.groceries.produce.fruit.apples_pears.apples' returning id""",
        (user_id, tx, raw_name, raw_name),
    ).fetchone()["id"]
    return tx, item


def _context(conn: Any, user_id: UUID) -> ProductReviewRepository:
    conn.execute("select set_config('app.current_user_id', %s, true)", (str(user_id),))
    return ProductReviewRepository(conn, user_id)


@pytest.mark.parametrize(
    ("edit", "missing_reason"),
    [
        ({"quantity": Decimal("10")}, "unverified_package_count"),
        ({"unit": "pack"}, "unverified_package_count"),
        ({"raw_name": "Different apples"}, "unresolved_identity"),
        ({"unit_price_basis_value": Decimal("2")}, "unverified_price_basis"),
    ],
)
def test_ordinary_item_edits_invalidate_dependent_evidence(
    edit: dict[str, Any], missing_reason: str
) -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    printed_basis = "unit_price_basis_value" in edit
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        tx, item_id = _item(admin, owner, raw_name="Honeycrisp apples")
        admin.execute(
            """update transaction_items set
                 product_identity_key='honeycrisp-500g', product_type_key='apple.honeycrisp',
                 classification_source='user', classification_review_status='reviewed',
                 classification_reviewed_at=now(),
                 package_value=500, package_unit='g',
                 unit_price_amount=%s, unit_price_basis_value=%s, unit_price_basis_unit=%s,
                 normalized_unit='kg', normalized_unit_price_amount=%s,
                 normalized_price_is_estimated=false,
                 field_provenance=%s::jsonb where id=%s""",
            (Decimal("5") if printed_basis else None, Decimal("1") if printed_basis else None,
             "kg" if printed_basis else None, Decimal("5") if printed_basis else Decimal("10"),
             '{"identity":{"source":"user_confirmed"},'
             '"product_type":{"source":"user_confirmed"},'
             '"package_size":{"source":"user_confirmed"},'
             '"package_count":{"source":"user_confirmed"},'
             '"measured_value":{"source":"user_confirmed"}}', item_id),
        )
        admin.commit()
    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        runtime.execute("select set_config('app.current_user_id', %s, true)", (str(owner),))
        query = """select i.*, node.stable_key as taxonomy_key, t.currency,
                          false as has_refund from transaction_items i
                   join transactions t on t.id=i.transaction_id and t.user_id=i.user_id
                   join taxonomy_nodes node on node.id=i.taxonomy_node_id
                   where i.id=%s and i.user_id=%s"""
        before = runtime.execute(query, (item_id, owner)).fetchone()
        assert before is not None
        assert readiness_reasons(before) == ()
        TransactionRepository(runtime, owner).update_item(
            tx, item_id, TransactionItemUpdate(**edit, correction_reason="Correct receipt detail")
        )
        after = runtime.execute(query, (item_id, owner)).fetchone()
        assert after is not None
        assert missing_reason in readiness_reasons(after)
        if "quantity" in edit or printed_basis:
            assert after["normalized_unit_price_amount"] != before["normalized_unit_price_amount"]
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()


def test_history_sql_excludes_estimated_price_even_with_other_verified_fields() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        _, verified_id = _item(admin, owner, raw_name="Honeycrisp apples")
        _, estimated_id = _item(admin, owner, raw_name="Honeycrisp apples")
        for item_id, estimated in ((verified_id, False), (estimated_id, True)):
            admin.execute(
                """update transaction_items set product_identity_key='honeycrisp-500g',
                     product_type_key='apple.honeycrisp', package_value=500, package_unit='g',
                     classification_source='user', classification_review_status='reviewed',
                     classification_reviewed_at=now(), normalized_unit='kg',
                     normalized_unit_price_amount=10, normalized_price_is_estimated=%s,
                     field_provenance='{"identity":{"source":"user_confirmed"},
                                        "product_type":{"source":"user_confirmed"},
                                        "package_size":{"source":"user_confirmed"},
                                        "package_count":{"source":"user_confirmed"}}'::jsonb
                   where id=%s""",
                (estimated, item_id),
            )
        admin.commit()
    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        runtime.execute("select set_config('app.current_user_id', %s, true)", (str(owner),))
        history = DashboardRepository(runtime, owner).get_item_price_history(
            ItemPriceHistoryRequest(identity_key="product:honeycrisp-500g")
        )
        assert [point.transaction_item_id for series in history.series for point in series.points] == [verified_id]
        assert history.comparison_coverage.eligible_items == 1
        assert history.comparison_coverage.excluded_items == 1
        assert history.comparison_coverage.reasons["estimated_unit_price"] == 1
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()


def test_confirmed_replacement_clears_package_evidence_for_a_different_product() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        tx, item_id = _item(admin, owner, raw_name="Honeycrisp apples")
        admin.execute(
            """update transaction_items set product_identity_key='honeycrisp-500g',
                     product_type_key='apple.honeycrisp', package_value=500, package_unit='g',
                     classification_source='user', classification_review_status='reviewed',
                     classification_reviewed_at=now(), normalized_unit='kg',
                     normalized_unit_price_amount=10, normalized_price_is_estimated=false,
                     field_provenance='{"identity":{"source":"user_confirmed"},
                                        "product_type":{"source":"user_confirmed"},
                                        "package_size":{"source":"user_confirmed","source_ref":"apple-label"},
                                        "package_count":{"source":"user_confirmed"}}'::jsonb
                   where id=%s""",
            (item_id,),
        )
        admin.commit()
    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        runtime.execute("select set_config('app.current_user_id', %s, true)", (str(owner),))
        repo = TransactionRepository(runtime, owner)
        draft = TransactionDraftCreate(
            source_type="manual", transaction_date=repo.get_transaction(tx).transaction_date,
            total_amount=Decimal("5"), items=[TransactionItemCreate(
                existing_item_id=item_id,
                raw_name="Different product", normalized_name="Different product",
                taxonomy_node_key="food_dining.groceries.produce.fruit.apples_pears.apples",
                classification_source="user", classification_review_status="reviewed",
                product_identity_key="honeycrisp-500g", product_type_key="apple.honeycrisp",
                field_provenance={"identity": {"source": "user_confirmed"},
                                  "product_type": {"source": "user_confirmed"},
                                  "package_size": {"source": "user_confirmed"},
                                  "package_count": {"source": "user_confirmed"}},
                quantity=Decimal("1"), unit="each", package_value=Decimal("500"), package_unit="g",
                line_total_amount=Decimal("5"),
            )],
        )
        corrected = repo.replace_confirmed(tx, draft, "Correct product identity")
        assert corrected.items[0].field_provenance.package_size.source == "unknown"
        assert corrected.items[0].field_provenance.package_size.source_ref is None
        assert corrected.items[0].field_provenance.identity.source == "unknown"
        assert corrected.items[0].line_total_amount == Decimal("5")
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()


def test_replacement_matches_evidence_by_item_id_across_reorder_insert_and_delete() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        tx, apple_id = _item(admin, owner, raw_name="Apples")
        pear = admin.execute(
            """insert into transaction_items
               (user_id, transaction_id, raw_name, normalized_name, taxonomy_node_id,
                quantity, unit, line_total_amount)
               select %s, %s, 'Pears', 'Pears', id, 1, 'each', 5
               from taxonomy_nodes where stable_key =
               'food_dining.groceries.produce.fruit.apples_pears.apples' returning id""",
            (owner, tx),
        ).fetchone()
        assert pear is not None
        pear_id = pear["id"]
        for item_id, name, source in ((apple_id, "Apples", "apple-label"),
                                      (pear_id, "Pears", "pear-label")):
            admin.execute(
                """update transaction_items set product_identity_key=%s,
                     product_type_key=%s, package_value=500, package_unit='g',
                     classification_source='user', classification_review_status='reviewed',
                     classification_reviewed_at=now(), normalized_unit='kg',
                     normalized_unit_price_amount=10, normalized_price_is_estimated=false,
                     field_provenance=jsonb_build_object(
                         'identity', jsonb_build_object('source','user_confirmed','source_ref',%s::text),
                         'product_type', jsonb_build_object('source','user_confirmed','source_ref',%s::text),
                         'package_size', jsonb_build_object('source','user_confirmed','source_ref',%s::text),
                         'package_count', jsonb_build_object('source','user_confirmed','source_ref',%s::text))
                   where id=%s""",
                (name.lower(), name.lower(), source, source, source, source, item_id),
            )
        admin.commit()

    def replacement_item(name: str, old_id: UUID | None, source: str) -> TransactionItemCreate:
        return TransactionItemCreate(
            existing_item_id=old_id, raw_name=name, normalized_name=name,
            taxonomy_node_key="food_dining.groceries.produce.fruit.apples_pears.apples",
            classification_source="user", classification_review_status="reviewed",
            product_identity_key=name.lower(), product_type_key=name.lower(),
            quantity=Decimal("1"), unit="each", package_value=Decimal("500"), package_unit="g",
            line_total_amount=Decimal("5"),
            field_provenance={field: {"source": "user_confirmed", "source_ref": source}
                              for field in ("identity", "product_type", "package_size", "package_count")},
        )

    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        runtime.execute("select set_config('app.current_user_id', %s, true)", (str(owner),))
        repo = TransactionRepository(runtime, owner)
        tx_date = repo.get_transaction(tx).transaction_date
        reordered = repo.replace_confirmed(tx, TransactionDraftCreate(
            source_type="manual", transaction_date=tx_date, total_amount=Decimal("15"),
            items=[replacement_item("Pears", pear_id, "pear-label"),
                   replacement_item("Oranges", None, "apple-label"),
                   replacement_item("Apples", apple_id, "apple-label")],
        ), "Reorder and add one line")
        by_name = {item.raw_name: item for item in reordered.items}
        assert by_name["Pears"].field_provenance.package_size.source_ref == "pear-label"
        assert by_name["Apples"].field_provenance.package_size.source_ref == "apple-label"
        assert by_name["Oranges"].field_provenance.package_size.source == "unknown"
        assert by_name["Oranges"].field_provenance.package_size.source_ref is None

        retained = repo.replace_confirmed(tx, TransactionDraftCreate(
            source_type="manual", transaction_date=tx_date, total_amount=Decimal("5"),
            items=[replacement_item("Apples", by_name["Apples"].id, "apple-label")],
        ), "Remove other lines")
        assert len(retained.items) == 1
        assert retained.items[0].field_provenance.package_size.source_ref == "apple-label"
        with pytest.raises(ValidationReferenceError):
            repo.replace_confirmed(tx, TransactionDraftCreate(
                source_type="manual", transaction_date=tx_date, total_amount=Decimal("5"),
                items=[replacement_item("Apples", apple_id, "apple-label")],
            ), "Reject stale item ID")
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()


def test_resolved_correction_is_listed_after_a_new_review_session_and_can_reverse() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        _, item_id = _item(admin, owner, raw_name="Honeycrisp apples")
        admin.execute(
            """update transaction_items set classification_source='user',
                     classification_review_status='reviewed', classification_reviewed_at=now()
               where id=%s""", (item_id,),
        )
        admin.commit()
    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        repo = _context(runtime, owner)
        patch = ReviewPatch(product_identity_key="honeycrisp-each",
                            product_type_key="apple.honeycrisp", confirm_fields=["quantity"])
        preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=patch))
        repo.decide(ReviewDecisionRequest(
            item_id=item_id, patch=patch, operation_id=preview.operation_id,
            decision="confirmed", reason="Verified product and count",
            expected_revisions={item_id: preview.affected[0]["revision"]},
        ))
        assert item_id not in {row["id"] for row in repo.queue()}
        # A new repository instance is equivalent to reopening the screen.
        reopened = ProductReviewRepository(runtime, owner)
        assert item_id in {row["id"] for row in reopened.recent_corrections()}
        event = reopened.history(item_id)[0]
        reopened.reverse(ReviewReverseRequest(
            event_id=event["id"], operation_id=uuid4(), reason="Undo reviewed product"
        ))
        assert item_id in {row["id"] for row in reopened.queue()}
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()


def test_runtime_review_is_owner_scoped_revision_bound_and_reversible() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner, other = uuid4(), uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        _user(admin, other)
        tx, item_id = _item(admin, owner, raw_name="Test Honeycrisp Apples")
        _, foreign_id = _item(admin, other, raw_name="Other Apples")
        admin.commit()

    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        repo = _context(runtime, owner)
        queue = repo.queue()
        assert any(row["id"] == item_id for row in queue)
        assert all(row["id"] != foreign_id for row in queue)
        with pytest.raises(NotFoundError):
            repo.preview(ReviewPreviewRequest(item_id=foreign_id, patch=ReviewPatch()))

        patch = ReviewPatch(product_identity_key="test-honeycrisp", product_type_key="apple.honeycrisp")
        preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=patch))
        assert preview.affected_count == 1
        assert preview.affected[0]["before"]["product_identity_key"] is None
        operation_id = preview.operation_id
        request = ReviewDecisionRequest(
            item_id=item_id, patch=patch, operation_id=operation_id,
            decision="confirmed", reason="Verified package label",
            expected_revisions={item_id: preview.affected[0]["revision"]},
        )
        result = repo.decide(request)
        assert result.affected_count == 1
        assert repo.decide(request).idempotent_replay
        with pytest.raises(ConflictError, match="Operation ID"):
            repo.decide(request.model_copy(update={"reason": "Different correction"}))
        assert repo._item(item_id)["line_total_amount"] == Decimal("5")
        assert repo._item(item_id)["field_provenance"]["identity"]["source_ref"] == (
            preview.affected[0]["after"]["field_provenance"]["identity"]["source_ref"]
        )
        history = repo.history(item_id)
        assert len(history) == 1
        with pytest.raises(ConflictError):
            repo.decide(request.model_copy(update={"operation_id": uuid4()}))

        reverse_request = ReviewReverseRequest(
            event_id=history[0]["id"], operation_id=uuid4(), reason="Undo mistaken match"
        )
        reverse = repo.reverse(reverse_request)
        assert reverse.decision == "reversed"
        assert repo.reverse(reverse_request).idempotent_replay
        assert repo._item(item_id)["product_identity_key"] is None

        defer_preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=ReviewPatch()))
        defer = ReviewDecisionRequest(
            item_id=item_id, patch=ReviewPatch(), operation_id=uuid4(),
            decision="deferred", reason="Need package photo",
            expected_revisions={item_id: defer_preview.affected[0]["revision"]},
        )
        repo.decide(defer)
        assert item_id not in {row["id"] for row in repo.queue()}
        suppressed = {row["id"]: row for row in repo.queue(include_suppressed=True)}
        assert suppressed[item_id]["review_decision"] == "deferred"

        # Explicitly revisit the same revision. The defer stays in the audit
        # trail, while the new operation can apply and be retried safely.
        reopen_patch = ReviewPatch(product_identity_key="reopened-honeycrisp")
        reopen_preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=reopen_patch))
        reopened = ReviewDecisionRequest(
            item_id=item_id, patch=reopen_patch, operation_id=reopen_preview.operation_id,
            decision="confirmed", reason="Package photo now available",
            expected_revisions={item_id: reopen_preview.affected[0]["revision"]},
        )
        assert repo.decide(reopened).affected_count == 1
        assert repo.decide(reopened).idempotent_replay
        decisions = runtime.execute(
            "select count(*) from product_review_decisions where item_id=%s and evidence_revision=%s",
            (item_id, defer_preview.affected[0]["revision"]),
        ).fetchone()
        assert decisions is not None and decisions["count"] == 2

        # A numerical estimate can be user confirmed without retyping it;
        # the source status changes and normalization is recalculated.
        runtime.execute(
            """update transaction_items set package_value=500, package_unit='g',
                      field_provenance='{"package_size":{"source":"estimate"}}'::jsonb
               where id=%s and user_id=%s""",
            (item_id, owner),
        )
        assert item_id in {row["id"] for row in repo.queue()}
        evidence_patch = ReviewPatch(confirm_fields=["package_size", "package_count"])
        evidence_preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=evidence_patch))
        repo.decide(ReviewDecisionRequest(
            item_id=item_id, patch=evidence_patch, operation_id=uuid4(),
            decision="confirmed", reason="Checked the printed package",
            expected_revisions={item_id: evidence_preview.affected[0]["revision"]},
        ))
        corrected = repo._item(item_id)
        assert corrected["field_provenance"]["package_size"]["source"] == "user_confirmed"
        assert corrected["normalized_unit"] == "kg"
        assert corrected["line_total_amount"] == Decimal("5")

        event = repo.history(item_id)[0]
        runtime.execute(
            "update transaction_items set brand='Independent edit' where id=%s and user_id=%s",
            (item_id, owner),
        )
        with pytest.raises(ConflictError, match="later edit"):
            repo.reverse(ReviewReverseRequest(
                event_id=event["id"], operation_id=uuid4(), reason="Undo package correction"
            ))

        reject_preview = repo.preview(ReviewPreviewRequest(item_id=item_id, patch=ReviewPatch()))
        repo.decide(ReviewDecisionRequest(
            item_id=item_id, patch=ReviewPatch(), operation_id=uuid4(),
            decision="rejected", reason="No supporting product evidence",
            expected_revisions={item_id: reject_preview.affected[0]["revision"]},
        ))
        assert item_id not in {row["id"] for row in repo.queue()}

    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id = any(%s)", ([owner, other],))
        admin.commit()


def test_bulk_preview_excludes_related_variant_and_preserves_financial_totals() -> None:
    assert ADMIN_URL and RUNTIME_URL
    owner = uuid4()
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        _user(admin, owner)
        first_tx, first_id = _item(admin, owner, raw_name="TEST APPLES")
        second_tx, second_id = _item(admin, owner, raw_name="TEST APPLES")
        variant_tx, variant_id = _item(admin, owner, raw_name="TEST APPLES")
        for item_id, product_type in ((first_id, "apple.honeycrisp"),
                                      (second_id, "apple.honeycrisp"),
                                      (variant_id, "apple.gala")):
            admin.execute(
                """update transaction_items set product_identity_key='test-apples',
                          product_type_key=%s,
                          field_provenance='{"identity":{"source":"user_confirmed"},
                                             "product_type":{"source":"user_confirmed"}}'::jsonb
                   where id=%s""",
                (product_type, item_id),
            )
        admin.commit()

    with psycopg.connect(RUNTIME_URL, row_factory=dict_row) as runtime, runtime.transaction():
        repo = _context(runtime, owner)
        patch = ReviewPatch(brand="Verified brand")
        preview = repo.preview(ReviewPreviewRequest(
            item_id=first_id, scope="confirmed_identity", patch=patch
        ))
        assert {row["item_id"] for row in preview.affected} == {first_id, second_id}
        assert preview.affected_count == 2
        result = repo.decide(ReviewDecisionRequest(
            item_id=first_id, scope="confirmed_identity", patch=patch,
            operation_id=uuid4(), decision="confirmed", reason="Checked both labels",
            expected_revisions={row["item_id"]: row["revision"] for row in preview.affected},
        ))
        assert result.affected_count == 2
        assert repo._item(first_id)["brand"] == "Verified brand"
        assert repo._item(second_id)["brand"] == "Verified brand"
        assert repo._item(variant_id)["brand"] is None
        totals = runtime.execute(
            "select id, total_amount from transactions where id = any(%s) and user_id=%s",
            ([first_tx, second_tx, variant_tx], owner),
        ).fetchall()
        assert len(totals) == 3
        assert all(row["total_amount"] == Decimal("5") for row in totals)

    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as admin:
        admin.execute("delete from auth.users where id=%s", (owner,))
        admin.commit()
