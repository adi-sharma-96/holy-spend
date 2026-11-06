"""Durable storage cleanup with adoption checks and bounded retries."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.errors import ConflictError, NotFoundError, StorageOperationError
from app.object_storage import ObjectStorage
from app.receipt_files import ReceiptRepository


@dataclass(frozen=True)
class CleanupAttempt:
    job_id: UUID
    attempt_id: UUID


class ReceiptRecoveryRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def stage(self, bucket: str, object_key: str, source_sha256: str) -> CleanupAttempt | None:
        if self._adopted(object_key):
            return None
        attempt_id = uuid4()
        row = self.conn.execute(
            """insert into receipt_storage_cleanup_jobs
               (user_id, bucket_name, object_key, reason, status, source_sha256, active_attempt_ids)
               values (%(user_id)s, %(bucket)s, %(key)s, 'upload_in_progress',
                       'pending', %(hash)s, array[%(attempt_id)s]::uuid[])
               on conflict (user_id, bucket_name, object_key) do update
               set status='pending', source_sha256=excluded.source_sha256,
                   reason='upload_in_progress', attempt_count=0,
                   last_error=null, next_attempt_at=now(), completed_at=null,
                   active_attempt_ids=array_append(
                       receipt_storage_cleanup_jobs.active_attempt_ids, %(attempt_id)s)
               where receipt_storage_cleanup_jobs.source_sha256 is null
                  or receipt_storage_cleanup_jobs.source_sha256=excluded.source_sha256
               returning id""",
            {"user_id": self.user_id, "bucket": bucket, "key": object_key,
             "hash": source_sha256, "attempt_id": attempt_id},
        ).fetchone()
        if row is None:
            raise ConflictError("Cleanup object key belongs to different receipt bytes")
        return CleanupAttempt(row["id"], attempt_id)

    def assert_active_attempt(
        self, attempt: CleanupAttempt, bucket: str, object_key: str, source_sha256: str
    ) -> None:
        # The caller holds the source-hash advisory lock through upload, so
        # recovery cannot retire this attempt between the check and Storage.
        # A plain read avoids holding the cleanup row lock while other retries
        # stage in separate transactions.
        row = self.conn.execute(
            """select 1 from receipt_storage_cleanup_jobs
               where id=%(id)s and user_id=%(user_id)s and bucket_name=%(bucket)s
                 and object_key=%(key)s and source_sha256=%(hash)s
                 and status <> 'completed' and %(attempt_id)s = any(active_attempt_ids)""",
            {"id": attempt.job_id, "user_id": self.user_id, "bucket": bucket,
             "key": object_key, "hash": source_sha256, "attempt_id": attempt.attempt_id},
        ).fetchone()
        if row is None:
            raise ConflictError("Upload cleanup protection is no longer active")

    def list_unresolved(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """select id, reason, status, attempt_count, next_attempt_at, created_at,
                      attempt_count >= 5 as exhausted
               from receipt_storage_cleanup_jobs
               where user_id=%(user_id)s and status <> 'completed'
               order by created_at, id""",
            {"user_id": self.user_id},
        ).fetchall()
        return [dict(row) for row in rows]

    def recover(
        self, job_id: UUID, storage: ObjectStorage, *, finished_attempt_id: UUID | None = None
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """select id, bucket_name, object_key, source_sha256,
                      status, attempt_count, active_attempt_ids from receipt_storage_cleanup_jobs
               where id=%(id)s and user_id=%(user_id)s""",
            {"id": job_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Receipt cleanup job not found")
        if row["status"] == "completed":
            return {"id": job_id, "status": "completed", "adopted": False}
        if row["source_sha256"] is None:
            return {"id": job_id, "status": "retrying", "reason": "legacy_cleanup_requires_manual_review"}
        # Match ReceiptCommitSaga's order: source hash advisory lock first,
        # cleanup row lock second. Recheck after waiting for a concurrent retry.
        ReceiptRepository(self.conn, self.user_id).acquire_commit_lock(row["source_sha256"])
        locked = self.conn.execute(
            """select id, bucket_name, object_key, source_sha256, status, attempt_count,
                      active_attempt_ids
               from receipt_storage_cleanup_jobs where id=%(id)s and user_id=%(user_id)s
               for update""",
            {"id": job_id, "user_id": self.user_id},
        ).fetchone()
        if locked is None:
            raise NotFoundError("Receipt cleanup job not found")
        if locked["source_sha256"] != row["source_sha256"]:
            return {"id": job_id, "status": "retrying", "reason": "source_changed_retry"}
        row = locked
        if row["status"] == "completed":
            return {"id": job_id, "status": "completed", "adopted": False}
        active_attempts = list(row["active_attempt_ids"])
        if finished_attempt_id is not None:
            if finished_attempt_id not in active_attempts:
                return {"id": job_id, "status": "retrying", "reason": "attempt_not_active"}
            active_attempts.remove(finished_attempt_id)
            self.conn.execute(
                """update receipt_storage_cleanup_jobs
                   set active_attempt_ids=array_remove(active_attempt_ids, %(attempt_id)s)
                   where id=%(id)s and user_id=%(user_id)s""",
                {"attempt_id": finished_attempt_id, "id": job_id, "user_id": self.user_id},
            )
        if self._adopted(row["object_key"]):
            self._complete(job_id)
            return {"id": job_id, "status": "completed", "adopted": True}
        if row["attempt_count"] >= 5:
            return {"id": job_id, "status": "retrying", "exhausted": True}
        try:
            if not storage.object_exists(row["bucket_name"], row["object_key"]):
                # The staged upload may not have started yet. Keep its durable
                # cleanup intent until adoption or a later orphan cleanup.
                if not active_attempts:
                    self._complete(job_id)
                    return {"id": job_id, "status": "completed", "adopted": False}
                return {"id": job_id, "status": "retrying", "reason": "upload_not_observed"}
            storage.delete_object(row["bucket_name"], row["object_key"])
        except StorageOperationError:
            self.conn.execute(
                """update receipt_storage_cleanup_jobs
                   set status='retrying', attempt_count=attempt_count+1,
                       last_error='storage_delete_failed',
                       next_attempt_at=now() + make_interval(mins => least(60, 5 * (attempt_count+1)))
                   where id=%(id)s and user_id=%(user_id)s""",
                {"id": job_id, "user_id": self.user_id},
            )
            return {"id": job_id, "status": "retrying", "reason": "storage_delete_failed"}
        if active_attempts:
            return {"id": job_id, "status": "retrying", "reason": "upload_attempt_active"}
        self._complete(job_id)
        return {"id": job_id, "status": "completed", "adopted": False}

    def _adopted(self, object_key: str) -> bool:
        row = self.conn.execute(
            """select 1 from receipt_files
               where user_id=%(user_id)s and object_key=%(key)s and upload_status='uploaded'
               union all
               select 1 from receipt_commit_requests
               where user_id=%(user_id)s and object_key=%(key)s
               limit 1""",
            {"user_id": self.user_id, "key": object_key},
        ).fetchone()
        return row is not None

    def _complete(self, job_id: UUID) -> None:
        self.conn.execute(
            """update receipt_storage_cleanup_jobs
               set status='completed', completed_at=now(), last_error=null,
                   active_attempt_ids='{}'::uuid[]
               where id=%(id)s and user_id=%(user_id)s""",
            {"id": job_id, "user_id": self.user_id},
        )
