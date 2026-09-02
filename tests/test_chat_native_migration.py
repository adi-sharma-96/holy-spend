from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_native_migration_adds_adjustment_detail_and_retry_ledger() -> None:
    migration = (
        ROOT / "supabase" / "migrations" / "0010_chat_native_receipt_ingestion.sql"
    ).read_text(encoding="utf-8")

    for column in ("subtype", "raw_label", "affects_total", "metadata"):
        assert f"add column {column}" in migration
    for subtype in (
        "bag_fee",
        "delivery_fee",
        "service_fee",
        "other_fee",
        "membership_benefit",
        "delivery_discount",
        "offer",
        "other_discount",
    ):
        assert subtype in migration
    assert "create table receipt_ingestion_requests" in migration
    assert "source_file_id_hash" in migration
    assert "temporary" not in migration.lower()
    assert "enable row level security" in migration
    assert "force row level security" in migration
    assert "receipt_ingestion_requests_crud_own" in migration


def test_runtime_role_grants_chat_native_retry_ledger() -> None:
    bootstrap = (ROOT / "supabase" / "bootstrap" / "001_runtime_role.sql").read_text(
        encoding="utf-8"
    )

    assert "'receipt_ingestion_requests'" in bootstrap
