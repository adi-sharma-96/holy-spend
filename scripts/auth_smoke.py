"""Bounded authentication and MCP deployment smoke check.

All output is a sanitized JSON summary. Use only with an explicitly selected
disposable or approved staging database and a protected test client.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import psycopg
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from psycopg.rows import dict_row

from app.auth_events import configure_auth_logging, emit_auth_event
from app.pat_verification import VerifyCode, verification_target, verify_credential
from app.security import generate_pat, hash_pat


@dataclass
class Summary:
    schema: str = "holy-spend-auth-smoke-v1"
    origin: str = ""
    stages: dict[str, str] = field(default_factory=dict)
    created_ids: dict[str, str] = field(default_factory=dict)
    success: bool = False


async def check_mcp(base: str, token: str) -> None:
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(10, connect=3),
            follow_redirects=False,
            trust_env=False,
        ) as client,
        streamable_http_client(base.rstrip("/") + "/mcp", http_client=client) as (read, write, _session_id),
        ClientSession(read, write) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=15)
        tools = await asyncio.wait_for(session.list_tools(), timeout=15)
        if not tools.tools:
            raise RuntimeError("empty MCP tool list")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run protected authentication/MCP smoke checks")
    p.add_argument("--base-url", required=True)
    p.add_argument("--allow-loopback-http", action="store_true")
    p.add_argument("--user-id", type=UUID, required=True)
    p.add_argument("--admin-database-url-env", default="SMOKE_ADMIN_DATABASE_URL")
    p.add_argument("--existing-token-stdin", action="store_true")
    p.add_argument("--existing-token-id", type=UUID)
    p.add_argument("--oauth-client-id")
    p.add_argument("--oauth-secret-env", default="SMOKE_OAUTH_CLIENT_SECRET")
    p.add_argument("--oauth-redirect-uri")
    return p


def oauth_access_id(base_url: str, access_token: str, owner_id: UUID) -> UUID:
    """Resolve the issued access row through the selected server, not a local pepper."""
    with (
        httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client,
        client.stream(
            "GET",
            base_url.rstrip("/") + "/v1/auth/verify",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response,
    ):
        if response.status_code != 200:
            raise RuntimeError("OAuth access identification failed")
        body = b""
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > 8192:
                raise RuntimeError("OAuth access identification response too large")
    try:
        data = json.loads(body)
        if (
            not isinstance(data, dict)
            or data.get("service") != "holy-spend"
            or data.get("response") != "pat-verification-v1"
            or UUID(data["user_id"]) != owner_id
        ):
            raise ValueError
        return UUID(data["token_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("OAuth access identification incompatible") from error


def run(argv: list[str] | None = None) -> int:
    configure_auth_logging()
    args = parser().parse_args(argv)
    summary = Summary()
    try:
        _, summary.origin = verification_target(args.base_url, args.allow_loopback_http)
        admin_url = os.getenv(args.admin_database_url_env)
        if not args.existing_token_stdin and not admin_url:
            raise ValueError("admin database URL required")
        if args.existing_token_stdin and args.existing_token_id is None:
            raise ValueError("existing token ID required")
        if (args.oauth_client_id or args.oauth_redirect_uri) and not (
            args.oauth_client_id and args.oauth_redirect_uri and os.getenv(args.oauth_secret_env)
        ):
            raise ValueError("complete OAuth test client configuration required")
        if args.existing_token_stdin and args.oauth_client_id:
            raise ValueError("OAuth issuance requires owned cleanup database")
        token = sys.stdin.readline().rstrip("\r\n") if args.existing_token_stdin else generate_pat()
        if not token:
            raise ValueError("empty test token")
    except ValueError:
        summary.stages["preflight"] = "CONFIGURATION_ERROR"
        print(json.dumps(summary.__dict__, sort_keys=True))
        return 2

    pat_id: UUID | None = args.existing_token_id
    oauth_pat_id: UUID | None = None
    refresh_id: UUID | None = None
    access: str | None = None
    refresh: str | None = None
    oauth_exchange_attempted = False
    conn: psycopg.Connection[dict[str, object]] | None = None
    active_stage = "create_pat"
    try:
        if not args.existing_token_stdin:
            assert admin_url is not None
            conn = psycopg.connect(admin_url, row_factory=dict_row, connect_timeout=3)
            row = conn.execute(
                """insert into personal_access_tokens (user_id, token_hash, name, scopes, expires_at)
                   values (%s, %s, %s, %s, %s) returning id""",
                (
                    args.user_id,
                    hash_pat(token),
                    "auth-smoke",
                    ["taxonomy:read"],
                    datetime.now(UTC) + timedelta(minutes=15),
                ),
            ).fetchone()
            assert row is not None
            pat_id = UUID(str(row["id"]))
            summary.created_ids["pat_id"] = str(pat_id)
            conn.commit()
            summary.stages["create_pat"] = "PASSED"
        else:
            summary.stages["create_pat"] = "SKIPPED_CALLER_TOKEN"

        assert pat_id is not None
        active_stage = "verify_pat"
        verification = verify_credential(
            args.base_url,
            token,
            args.user_id,
            pat_id,
            {"taxonomy:read"} if not args.existing_token_stdin else None,
            allow_loopback_http=args.allow_loopback_http,
        )
        summary.stages["verify_pat"] = verification.code.name
        if verification.code != VerifyCode.VERIFIED:
            raise RuntimeError("PAT verification failed")

        active_stage = "reject_unauthenticated"
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            unauth = client.get(args.base_url.rstrip("/") + "/v1/auth/verify")
            if unauth.status_code != 401:
                raise RuntimeError("unauthenticated verification was not rejected")
        summary.stages["reject_unauthenticated"] = "PASSED"

        active_stage = "mcp_initialize_tools_list"
        asyncio.run(check_mcp(args.base_url, token))
        summary.stages["mcp_initialize_tools_list"] = "PASSED"

        if args.oauth_client_id:
            active_stage = "oauth_code_exchange_replay"
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
                response = client.get(
                    args.base_url.rstrip("/") + "/authorize",
                    params={
                        "response_type": "code",
                        "client_id": args.oauth_client_id,
                        "redirect_uri": args.oauth_redirect_uri,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                        "resource": args.base_url.rstrip("/") + "/mcp",
                    },
                )
                if response.status_code != 302:
                    raise RuntimeError("OAuth authorization failed")
                location = urlsplit(response.headers.get("location", ""))
                expected = urlsplit(args.oauth_redirect_uri)
                if (location.scheme, location.netloc, location.path) != (
                    expected.scheme,
                    expected.netloc,
                    expected.path,
                ):
                    raise RuntimeError("OAuth callback mismatch")
                code = parse_qs(location.query).get("code", [None])[0]
                if not code:
                    raise RuntimeError("OAuth code absent")
                payload = {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": args.oauth_client_id,
                    "client_secret": os.environ[args.oauth_secret_env],
                    "redirect_uri": args.oauth_redirect_uri,
                    "code_verifier": verifier,
                    "resource": args.base_url.rstrip("/") + "/mcp",
                }
                # Even an invalid probe may expose a broken server that issues tokens.
                # Once sent, a missing response is not proof that issuance rolled back.
                oauth_exchange_attempted = True
                wrong_verifier = client.post(
                    args.base_url.rstrip("/") + "/token",
                    data={**payload, "code_verifier": "invalid-verifier"},
                )
                if wrong_verifier.status_code != 400 or wrong_verifier.json().get("error") != "invalid_grant":
                    raise RuntimeError("OAuth wrong verifier was not rejected")
                wrong_redirect = client.post(
                    args.base_url.rstrip("/") + "/token",
                    data={**payload, "redirect_uri": "https://invalid.example/callback"},
                )
                if wrong_redirect.status_code != 400:
                    raise RuntimeError("OAuth wrong redirect was not rejected")
                exchanged = client.post(args.base_url.rstrip("/") + "/token", data=payload)
                if exchanged.status_code != 200:
                    raise RuntimeError("OAuth exchange failed")
                tokens = exchanged.json()
                access = tokens.get("access_token")
                refresh = tokens.get("refresh_token")
                if not isinstance(access, str):
                    raise RuntimeError("OAuth token response malformed")
                oauth_pat_id = oauth_access_id(args.base_url, access, args.user_id)
                summary.created_ids["oauth_pat_id"] = str(oauth_pat_id)
                if not isinstance(refresh, str):
                    raise RuntimeError("OAuth refresh token response malformed")
                replay = client.post(args.base_url.rstrip("/") + "/token", data=payload)
                if replay.status_code != 400 or replay.json().get("error") != "invalid_grant":
                    raise RuntimeError("OAuth code replay was not rejected as invalid_grant")
            summary.stages["oauth_code_exchange_replay"] = "PASSED"
        else:
            summary.stages["oauth_code_exchange_replay"] = "SKIPPED_NO_CLIENT"

        summary.success = not args.existing_token_stdin and bool(args.oauth_client_id)
    except Exception:
        summary.stages.setdefault(active_stage, "FAILED")
    finally:
        if conn is not None:
            try:
                conn.rollback()
                cleanup_ok = True
                if pat_id is not None:
                    updated = conn.execute(
                        "update personal_access_tokens set revoked_at = now() where id = %s and user_id = %s",
                        (pat_id, args.user_id),
                    )
                    cleanup_ok = cleanup_ok and updated.rowcount == 1
                if access is not None and oauth_pat_id is None:
                    try:
                        oauth_pat_id = oauth_access_id(args.base_url, access, args.user_id)
                        summary.created_ids["oauth_pat_id"] = str(oauth_pat_id)
                    except Exception:
                        cleanup_ok = False
                if oauth_pat_id is not None:
                    rows = conn.execute(
                        "select id from oauth_refresh_tokens where pat_token_id = %s and user_id = %s",
                        (oauth_pat_id, args.user_id),
                    ).fetchall()
                    if len(rows) == 1:
                        refresh_id = UUID(str(rows[0]["id"]))
                        summary.created_ids["refresh_id"] = str(refresh_id)
                    else:
                        cleanup_ok = False
                    updated = conn.execute(
                        "update personal_access_tokens set revoked_at = now() where id = %s and user_id = %s",
                        (oauth_pat_id, args.user_id),
                    )
                    cleanup_ok = cleanup_ok and updated.rowcount == 1
                elif oauth_exchange_attempted:
                    cleanup_ok = False
                if refresh_id is not None:
                    updated = conn.execute(
                        "update oauth_refresh_tokens set revoked_at = now() where id = %s and user_id = %s",
                        (refresh_id, args.user_id),
                    )
                    cleanup_ok = cleanup_ok and updated.rowcount == 1
                conn.commit()
                summary.stages["cleanup"] = "PASSED" if cleanup_ok else "FAILED"
                summary.success = summary.success and cleanup_ok
            except Exception:
                summary.stages["cleanup"] = "FAILED"
                summary.success = False
            finally:
                conn.close()
        else:
            summary.stages["cleanup"] = "SKIPPED_CALLER_TOKEN"
    print(json.dumps(summary.__dict__, sort_keys=True))
    for stage, result in summary.stages.items():
        reason = {
            "create_pat": "create_pat",
            "verify_pat": "verify_pat",
            "mcp_initialize_tools_list": "mcp_exchange",
            "oauth_code_exchange_replay": "oauth_exchange",
            "cleanup": "cleanup",
        }.get(stage, "none")
        emit_auth_event(
            "smoke_stage",
            "succeeded" if result in {"PASSED", "VERIFIED"} else "failed",
            "smoke",
            os.getenv("ENVIRONMENT", "local"),
            0,
            reason=reason,
        )
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(run())
