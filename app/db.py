from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=get_settings().database_url,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        _pool.open()
    return _pool


@contextmanager
def connection() -> Iterator[Any]:
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def user_transaction(user_id: UUID) -> Iterator[Any]:
    with get_pool().connection() as conn, conn.transaction():
        conn.execute(
            "select set_config('app.current_user_id', %(user_id)s, true)",
            {"user_id": str(user_id)},
        )
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
