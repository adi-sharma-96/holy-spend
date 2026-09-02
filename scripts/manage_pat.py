import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.security import generate_pat, hash_pat

ALLOWED_SCOPES = frozenset(
    {
        "taxonomy:read",
        "aliases:read",
        "transactions:read",
        "transactions:write",
        "analytics:read",
        "receipt_files:read",
        "receipt_files:write",
    }
)
DEFAULT_GPT_SCOPES = (
    "taxonomy:read",
    "aliases:read",
    "transactions:read",
    "transactions:write",
    "analytics:read",
)


@dataclass(frozen=True)
class CreatedPAT:
    token_id: UUID
    raw_token: str
    expires_at: datetime | None


def validate_scopes(scopes: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(scopes))
    unsupported = sorted(set(normalized) - ALLOWED_SCOPES)
    if unsupported:
        raise ValueError(f"Unsupported PAT scopes: {', '.join(unsupported)}")
    if not normalized:
        raise ValueError("At least one PAT scope is required")
    return normalized


def create_pat(
    conn: Any,
    user_id: UUID,
    name: str,
    scopes: Sequence[str],
    expires_days: int | None,
) -> CreatedPAT:
    approved_scopes = validate_scopes(scopes)
    profile = conn.execute(
        "select id from profiles where id = %(user_id)s",
        {"user_id": user_id},
    ).fetchone()
    if profile is None:
        raise ValueError("The selected user does not have a profile")

    raw_token = generate_pat()
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_days) if expires_days is not None else None
    )
    row = conn.execute(
        """
        insert into personal_access_tokens (user_id, token_hash, name, scopes, expires_at)
        values (%(user_id)s, %(token_hash)s, %(name)s, %(scopes)s, %(expires_at)s)
        returning id
        """,
        {
            "user_id": user_id,
            "token_hash": hash_pat(raw_token),
            "name": name,
            "scopes": list(approved_scopes),
            "expires_at": expires_at,
        },
    ).fetchone()
    return CreatedPAT(token_id=row["id"], raw_token=raw_token, expires_at=expires_at)


def revoke_pat(conn: Any, user_id: UUID, token_id: UUID) -> bool:
    result = conn.execute(
        """
        update personal_access_tokens
        set revoked_at = coalesce(revoked_at, now())
        where id = %(token_id)s and user_id = %(user_id)s
        """,
        {"token_id": token_id, "user_id": user_id},
    )
    return int(result.rowcount) > 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and revoke personal access tokens.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a PAT and print its raw value once.")
    create_parser.add_argument("--user-id", type=UUID, required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument(
        "--scope",
        action="append",
        choices=sorted(ALLOWED_SCOPES),
        dest="scopes",
        help="Repeat for each scope. Defaults to the private GPT scope set.",
    )
    create_parser.add_argument(
        "--expires-days",
        type=int,
        default=365,
        help="Positive lifetime in days; use 0 for no expiry.",
    )

    revoke_parser = subparsers.add_parser("revoke", help="Revoke a PAT by ID for one user.")
    revoke_parser.add_argument("--user-id", type=UUID, required=True)
    revoke_parser.add_argument("--token-id", type=UUID, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    admin_database_url = os.getenv("PAT_ADMIN_DATABASE_URL")
    if not admin_database_url:
        raise SystemExit("PAT_ADMIN_DATABASE_URL is required")

    with psycopg.connect(admin_database_url, row_factory=dict_row) as conn:
        if args.command == "create":
            if args.expires_days < 0:
                raise SystemExit("--expires-days must be zero or greater")
            scopes = args.scopes or list(DEFAULT_GPT_SCOPES)
            created = create_pat(
                conn,
                args.user_id,
                args.name,
                scopes,
                args.expires_days or None,
            )
            conn.commit()
            print(f"PAT id: {created.token_id}")
            print(f"Raw PAT (shown once): {created.raw_token}")
            if created.expires_at is not None:
                print(f"Expires at: {created.expires_at.isoformat()}")
            return 0

        revoked = revoke_pat(conn, args.user_id, args.token_id)
        conn.commit()
        if not revoked:
            raise SystemExit("PAT not found for the selected user")
        print(f"Revoked PAT: {args.token_id}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
