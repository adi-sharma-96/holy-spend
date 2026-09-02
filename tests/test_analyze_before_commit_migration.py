from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analyze_before_commit_migration_adds_owner_scoped_ledgers() -> None:
    migration = (
        ROOT / "supabase" / "migrations" / "0011_analyze_before_receipt_commit.sql"
    ).read_text(encoding="utf-8")

    assert "create table receipt_commit_requests" in migration
    assert "unique (user_id, client_request_id)" in migration
    assert "source_file_sha256" in migration
    assert "create table receipt_storage_cleanup_jobs" in migration
    assert "next_attempt_at" in migration
    assert "enable row level security" in migration
    assert "force row level security" in migration
    assert "receipt_commit_requests_crud_own" in migration
    assert "receipt_storage_cleanup_jobs_crud_own" in migration
    assert "temporary" not in migration.lower()


def test_runtime_role_grants_commit_and_cleanup_ledgers() -> None:
    bootstrap = (ROOT / "supabase" / "bootstrap" / "001_runtime_role.sql").read_text(
        encoding="utf-8"
    )

    assert "'receipt_commit_requests'" in bootstrap
    assert "'receipt_storage_cleanup_jobs'" in bootstrap
    assert "'receipt_cleanup_status'" in bootstrap


def test_owner_scoped_file_hash_migration_is_guarded_and_unique() -> None:
    migration = (
        ROOT
        / "supabase"
        / "migrations"
        / "0012_owner_scoped_receipt_hash_idempotency.sql"
    ).read_text(encoding="utf-8")

    assert "group by user_id, source_file_sha256" in migration
    assert "having count(*) > 1" in migration
    assert "raise exception" in migration
    assert "unique index receipt_commit_requests_owner_file_hash_uidx" in migration
    assert "unique using index" in migration
    assert "delete from" not in migration.lower()
