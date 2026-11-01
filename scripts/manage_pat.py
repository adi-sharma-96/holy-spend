import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from getpass import getpass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.auth_events import configure_auth_logging, emit_auth_event
from app.config import get_settings
from app.pat_verification import VerifyCode, verification_target, verify_credential
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
    expires_at = datetime.now(UTC) + timedelta(days=expires_days) if expires_days is not None else None
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
    create_parser.add_argument("--verify-url", help="Explicit API base URL; overrides PAT_VERIFY_BASE_URL")
    create_parser.add_argument("--allow-loopback-http", action="store_true")
    create_parser.add_argument("--skip-verification", action="store_true")
    create_parser.add_argument(
        "--allow-development-pepper",
        action="store_true",
        help="Permit the development pepper only for an explicitly selected literal loopback target.",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify an existing PAT without database access.")
    verify_parser.add_argument("--verify-url", help="Explicit API base URL; overrides PAT_VERIFY_BASE_URL")
    verify_parser.add_argument("--allow-loopback-http", action="store_true")
    verify_parser.add_argument("--stdin", action="store_true", help="Read token from standard input")
    verify_parser.add_argument("--user-id", type=UUID, required=True)
    verify_parser.add_argument("--token-id", type=UUID, required=True)
    verify_parser.add_argument("--scope", action="append", dest="scopes", choices=sorted(ALLOWED_SCOPES))

    revoke_parser = subparsers.add_parser("revoke", help="Revoke a PAT by ID for one user.")
    revoke_parser.add_argument("--user-id", type=UUID, required=True)
    revoke_parser.add_argument("--token-id", type=UUID, required=True)
    return parser


def _main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"create", "verify"}:
        target = args.verify_url or os.getenv("PAT_VERIFY_BASE_URL")
        if target or not (args.command == "create" and args.skip_verification):
            try:
                if not target:
                    raise ValueError("Verification target required")
                verification_target(target, args.allow_loopback_http)
            except ValueError:
                print("CONFIGURATION_ERROR: provide a valid --verify-url (or PAT_VERIFY_BASE_URL)", file=sys.stderr)
                return int(VerifyCode.CONFIGURATION_ERROR)
    if args.command == "verify":
        token = sys.stdin.readline().rstrip("\r\n") if args.stdin else getpass("PAT: ")
        if not token:
            print("CONFIGURATION_ERROR: empty token", file=sys.stderr)
            return int(VerifyCode.CONFIGURATION_ERROR)
        assert target is not None
        result = verify_credential(
            target,
            token,
            args.user_id,
            args.token_id,
            set(args.scopes) if args.scopes is not None else None,
            allow_loopback_http=args.allow_loopback_http,
        )
        scope_status = "specified" if args.scopes is not None else "unspecified"
        emit_auth_event(
            "pat_verification", "accepted" if result.code == VerifyCode.VERIFIED else "failed", "cli", "local", 0
        )
        print(
            f"{result.code.name}: selected origin {result.origin}; expected user {args.user_id}; "
            f"token {args.token_id}; scopes {scope_status}"
        )
        return int(result.code)
    if args.command == "create":
        if args.expires_days < 0:
            print("CONFIGURATION_ERROR: --expires-days must be nonnegative", file=sys.stderr)
            return int(VerifyCode.CONFIGURATION_ERROR)
        settings = get_settings()
        pepper = settings.pat_pepper.get_secret_value()
        if not pepper or pepper == "dev-only-change-me":
            local_target = target is not None and urlsplit(target).hostname in {"localhost", "127.0.0.1", "::1"}
            if not (pepper == "dev-only-change-me" and args.allow_development_pepper and local_target):
                print("CONFIGURATION_ERROR: configure a non-development PAT_PEPPER", file=sys.stderr)
                return int(VerifyCode.CONFIGURATION_ERROR)
    admin_database_url = os.getenv("PAT_ADMIN_DATABASE_URL")
    if not admin_database_url:
        print("CONFIGURATION_ERROR: PAT_ADMIN_DATABASE_URL is required", file=sys.stderr)
        return int(VerifyCode.CONFIGURATION_ERROR)

    with psycopg.connect(admin_database_url, row_factory=dict_row) as conn:
        if args.command == "create":
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
            if args.skip_verification:
                emit_auth_event("pat_issuance", "succeeded", "cli", settings.environment, 0)
                print("CREATED_UNVERIFIED: saved; verification explicitly skipped")
                return int(VerifyCode.CREATED_UNVERIFIED)
            assert target is not None
            result = verify_credential(
                target,
                created.raw_token,
                args.user_id,
                created.token_id,
                set(scopes),
                allow_loopback_http=args.allow_loopback_http,
            )
            print(f"{result.code.name}: saved token {created.token_id}; selected origin {result.origin}")
            emit_auth_event("pat_issuance", "succeeded", "cli", settings.environment, 0)
            emit_auth_event(
                "pat_verification",
                "accepted" if result.code == VerifyCode.VERIFIED else "failed",
                "cli",
                settings.environment,
                0,
            )
            return int(result.code)

        revoked = revoke_pat(conn, args.user_id, args.token_id)
        conn.commit()
        if not revoked:
            raise SystemExit("PAT not found for the selected user")
        print(f"Revoked PAT: {args.token_id}")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_auth_logging()
    try:
        return _main(argv)
    except Exception:
        # Database and transport exceptions can contain credentials or URLs.
        emit_auth_event("pat_issuance", "failed", "cli", "local", 0, reason="database_error")
        print("CONFIGURATION_ERROR: operation failed; no verification claim", file=sys.stderr)
        return int(VerifyCode.CONFIGURATION_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
