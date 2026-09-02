from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models import TransactionAdjustment
from app.plugin_models import ExpenseDraftInput, ExpenseDraftSaveRequest


def test_save_request_requires_stable_request_key() -> None:
    with pytest.raises(ValidationError):
        ExpenseDraftSaveRequest(
            client_request_id="short",
            draft=ExpenseDraftInput(
                source_type="manual",
                transaction_date="2026-07-27",
                total_amount="12.34",
            ),
        )


def test_existing_draft_can_carry_revision_without_user_identity() -> None:
    request = ExpenseDraftSaveRequest(
        client_request_id="widget:request-123",
        expected_revision=datetime(2026, 7, 27, tzinfo=UTC),
        draft=ExpenseDraftInput(
            source_type="manual",
            transaction_date="2026-07-27",
            currency="cad",
            total_amount="12.34",
        ),
    )
    dumped = request.model_dump(mode="json")

    assert request.draft.currency == "CAD"
    assert "user_id" not in dumped


def test_old_adjustment_rows_deserialize_with_backward_compatible_defaults() -> None:
    adjustment = TransactionAdjustment.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "item_id": None,
            "type": "tax",
            "amount": "1.23",
            "description": "HST",
        }
    )

    assert adjustment.subtype is None
    assert adjustment.raw_label is None
    assert adjustment.affects_total is True
    assert adjustment.metadata == {}


def test_draft_adjustment_rejects_subtype_from_wrong_vocabulary() -> None:
    with pytest.raises(ValidationError, match="not valid"):
        ExpenseDraftInput(
            source_type="receipt",
            transaction_date="2026-07-27",
            total_amount="10.00",
            adjustments=[
                {
                    "type": "tax",
                    "subtype": "service_fee",
                    "amount": "1.00",
                }
            ],
        )
