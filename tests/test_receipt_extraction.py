import hashlib
from decimal import Decimal

import pytest

from app.errors import InvalidUploadError
from app.receipt_downloads import DownloadedReceipt
from app.receipt_extraction import ReceiptCommitRequest, validate_commit_against_download
from app.receipt_normalization import normalize_receipt_savings


def downloaded() -> DownloadedReceipt:
    content = b"\x89PNG\r\n\x1a\nreceipt"
    return DownloadedReceipt(
        content=content,
        filename="receipt.png",
        mime_type="image/png",
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def commit_request(active: DownloadedReceipt, **updates: object) -> ReceiptCommitRequest:
    values: dict[str, object] = {
        "file_sha256": active.sha256,
        "draft": {
            "source_type": "receipt",
            "transaction_date": "2026-07-28",
            "merchant_name_raw": "Corner Market",
            "currency": "CAD",
            "total_amount": "5.64",
            "receipt": {},
        },
        "client_request_id": f"sha256:{active.sha256}",
    }
    values.update(updates)
    return ReceiptCommitRequest.model_validate(values)


def test_commit_candidate_gate_accepts_verified_meaningful_receipt() -> None:
    active = downloaded()

    validate_commit_against_download(commit_request(active), active)


def test_commit_candidate_gate_rejects_zero_or_headless_data() -> None:
    active = downloaded()
    request = commit_request(
        active,
        draft={
            "source_type": "receipt",
            "transaction_date": "2026-07-28",
            "currency": "CAD",
            "total_amount": Decimal("0"),
            "receipt": {},
        },
    )

    with pytest.raises(InvalidUploadError, match="meaningful positive total"):
        validate_commit_against_download(request, active)


def test_commit_candidate_gate_rejects_hash_mismatch() -> None:
    active = downloaded()
    request = commit_request(active, file_sha256="a" * 64)

    with pytest.raises(InvalidUploadError, match="no longer matches"):
        validate_commit_against_download(request, active)


def test_freshco_savings_becomes_informational_and_reconciles() -> None:
    request = commit_request(
        downloaded(),
        draft={
            "source_type": "receipt",
            "transaction_date": "2026-07-20",
            "merchant_name_raw": "FreshCo",
            "currency": "CAD",
            "subtotal_amount": "56.93",
            "tax_amount": "0.46",
            "discount_amount": "2.60",
            "total_amount": "57.39",
            "receipt": {},
            "items": [
                {
                    "raw_name": f"Item {index}",
                    "category_slug": "uncategorized",
                    "line_total_amount": amount,
                }
                for index, amount in enumerate(
                    ["5", "6", "7", "8", "9", "4", "3", "7", "7.93"],
                    start=1,
                )
            ],
            "adjustments": [
                {
                    "type": "discount",
                    "amount": "2.60",
                    "raw_label": "TOTAL SAVINGS",
                    "affects_total": True,
                }
            ],
        },
    )

    normalized = normalize_receipt_savings(request.draft)

    assert normalized.discount_amount is None
    assert len(normalized.items) == 9
    assert normalized.adjustments[0].amount == Decimal("2.60")
    assert normalized.adjustments[0].affects_total is False
    assert normalized.adjustments[0].metadata["normalization"] == "informational_savings"


def test_true_printed_discount_remains_total_affecting() -> None:
    request = commit_request(
        downloaded(),
        draft={
            "source_type": "receipt",
            "transaction_date": "2026-07-20",
            "merchant_name_raw": "Market",
            "currency": "CAD",
            "subtotal_amount": "10.00",
            "discount_amount": "2.00",
            "total_amount": "8.00",
            "receipt": {},
        },
    )

    normalized = normalize_receipt_savings(request.draft)

    assert normalized.discount_amount == Decimal("2.00")
