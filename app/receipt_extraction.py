import hashlib
import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.errors import InvalidUploadError
from app.models import SourceType
from app.plugin_models import ExpenseDraftInput, ExpenseSnapshot, ExpenseValidationResult
from app.receipt_downloads import DownloadedReceipt


class ReceiptCommitRequest(BaseModel):
    """Durable commit request for one already-downloaded ChatGPT receipt file."""

    model_config = ConfigDict(extra="forbid")

    file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    draft: ExpenseDraftInput
    client_request_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9._:-]+$")
    transaction_id: UUID | None = None
    expected_revision: datetime | None = None

    def stable_hash(self) -> str:
        canonical = self.model_dump(mode="json")
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ReceiptCommitResult(BaseModel):
    expense: ExpenseSnapshot
    receipt_file_id: str
    validation: ExpenseValidationResult
    idempotent_replay: bool = False
    exact_file_duplicate: bool = False
    result_version: int = 1


def validate_commit_against_download(
    request: ReceiptCommitRequest,
    downloaded: DownloadedReceipt,
) -> None:
    if downloaded.sha256.lower() != request.file_sha256.lower():
        raise InvalidUploadError("The downloaded receipt no longer matches the verified file")
    draft = request.draft
    if draft.source_type != SourceType.RECEIPT:
        raise InvalidUploadError("Committed receipt drafts must use source_type=receipt")
    if not draft.currency or not draft.total_amount.is_finite() or draft.total_amount <= 0:
        raise InvalidUploadError("Receipt extraction must include a meaningful positive total before storage")
    meaningful_items = [
        item for item in draft.items if (item.raw_name or item.interpreted_name or item.normalized_name)
    ]
    if not (draft.merchant_name_raw or draft.merchant_name_normalized or meaningful_items):
        raise InvalidUploadError("Receipt extraction did not produce a meaningful merchant or line item")
