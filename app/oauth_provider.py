import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl
from starlette.routing import Route

from app.config import Settings
from app.db import connection, user_transaction
from app.security import generate_pat, hash_pat

# Full MCP surface. There is no per-request scope enforcement downstream (the
# gateway's own /mcp route just requires *a* valid PAT; the upstream single_user
# resolver grants the owner everything unconditionally either way), so every
# token this issues carries the complete set rather than something narrower.
FULL_SCOPES = (
    "taxonomy:read",
    "aliases:read",
    "transactions:read",
    "transactions:write",
    "analytics:read",
    "receipt_files:read",
    "receipt_files:write",
)

AUTHORIZATION_CODE_TTL_SECONDS = 120
ACCESS_TOKEN_TTL_SECONDS = 180 * 24 * 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 365 * 24 * 60 * 60

CLAUDE_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def generate_authorization_code() -> str:
    return secrets.token_urlsafe(32)


class _AccessToken(AccessToken):
    pat_token_id: UUID


class _RefreshToken(RefreshToken):
    pat_token_id: UUID
    refresh_token_row_id: UUID


@dataclass
class _PendingCode:
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    expires_at: float
    resource: str | None


class SingleOwnerOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, _RefreshToken, _AccessToken]):
    """OAuth 2.1 authorization server for exactly one pre-shared client and one
    resource owner. Multiple chat hosts (Claude, ChatGPT, ...) can all
    authenticate as that same client; each just needs its own callback URL
    registered in the client's redirect_uris (Claude's is a fixed constant,
    others come from OAUTH_ADDITIONAL_REDIRECT_URIS).

    There is only ever one legitimate caller, so /authorize auto-approves
    instead of showing a login screen. What actually gates access is the
    client_secret the MCP SDK's own ClientAuthenticator requires at /token
    (constant-time compared, never exposed here) plus PKCE (also verified by
    the SDK before exchange_authorization_code is ever called) - auto-approval
    alone hands out nothing usable.

    Issued access tokens are real rows in personal_access_tokens (minted the
    same way scripts/manage_pat.py does), so the existing PAT-based /mcp
    gateway auth (app/security.py) needs no changes to accept them. Refresh
    tokens are tracked in oauth_refresh_tokens, one row per PAT, so refresh
    rotation can revoke the old PAT and mint a fresh one atomically.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.owner_user_id is None:
            raise ValueError("OWNER_USER_ID is required for the OAuth provider")
        if settings.oauth_client_id is None or settings.oauth_client_secret is None:
            raise ValueError("OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET are required for the OAuth provider")
        self._owner_user_id = settings.owner_user_id
        self._client = OAuthClientInformationFull(
            client_id=settings.oauth_client_id,
            client_secret=settings.oauth_client_secret.get_secret_value(),
            redirect_uris=[
                AnyUrl(CLAUDE_REDIRECT_URI),
                *(AnyUrl(uri) for uri in settings.additional_oauth_redirect_uris()),
            ],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(FULL_SCOPES),
        )
        # Authorization codes are single-use and live for ~2 minutes between
        # the auto-approved /authorize redirect and the client's /token call;
        # an in-memory store (lost on restart, fine given that lifetime) keeps
        # this from needing its own migration on top of oauth_refresh_tokens.
        self._pending_codes: dict[str, _PendingCode] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if client_id == self._client.client_id:
            return self._client
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Dynamic client registration is disabled; use the pre-shared client")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self._prune_expired_codes()
        code = generate_authorization_code()
        self._pending_codes[code] = _PendingCode(
            code_challenge=params.code_challenge,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=list(params.scopes) if params.scopes else list(FULL_SCOPES),
            expires_at=time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        pending = self._pending_codes.get(authorization_code)
        if pending is None:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=pending.scopes,
            expires_at=pending.expires_at,
            client_id=client.client_id or "",
            code_challenge=pending.code_challenge,
            redirect_uri=AnyUrl(pending.redirect_uri),
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            resource=pending.resource,
            subject=str(self._owner_user_id),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # PKCE, redirect_uri consistency, and expiry were already verified by
        # the SDK's token handler before this is called; a code is only ever
        # consumed once, so drop it here regardless of what happens next.
        self._pending_codes.pop(authorization_code.code, None)
        return await asyncio.to_thread(self._mint_tokens, list(authorization_code.scopes))

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> _RefreshToken | None:
        return await asyncio.to_thread(self._load_refresh_token, refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: _RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        return await asyncio.to_thread(self._rotate_refresh_token, refresh_token, scopes)

    async def load_access_token(self, token: str) -> _AccessToken | None:
        return await asyncio.to_thread(self._load_access_token, token)

    async def revoke_token(self, token: _AccessToken | _RefreshToken) -> None:
        await asyncio.to_thread(self._revoke, token)

    def _prune_expired_codes(self) -> None:
        now = time.time()
        expired = [code for code, pending in self._pending_codes.items() if pending.expires_at < now]
        for code in expired:
            self._pending_codes.pop(code, None)

    def _mint_tokens(self, scopes: list[str]) -> OAuthToken:
        raw_access = generate_pat()
        raw_refresh = generate_refresh_token()
        access_expires_at = time.time() + ACCESS_TOKEN_TTL_SECONDS
        refresh_expires_at = time.time() + REFRESH_TOKEN_TTL_SECONDS
        # Generated here rather than read back via `returning id`: RLS with
        # personal_access_tokens_select_none (and no SELECT grant) means the
        # runtime role can insert/update rows but not read any back,
        # including through RETURNING, which Postgres treats as requiring
        # SELECT under row-level security.
        pat_id = uuid4()

        with user_transaction(self._owner_user_id) as conn:
            conn.execute(
                """
                insert into personal_access_tokens (id, user_id, token_hash, name, scopes, expires_at)
                values (%(id)s, %(user_id)s, %(token_hash)s, %(name)s, %(scopes)s, to_timestamp(%(expires_at)s))
                """,
                {
                    "id": pat_id,
                    "user_id": self._owner_user_id,
                    "token_hash": hash_pat(raw_access, self._settings),
                    "name": f"claude-oauth-{int(time.time())}",
                    "scopes": scopes,
                    "expires_at": access_expires_at,
                },
            )
            conn.execute(
                """
                insert into oauth_refresh_tokens (user_id, token_hash, pat_token_id, expires_at)
                values (%(user_id)s, %(token_hash)s, %(pat_token_id)s, to_timestamp(%(expires_at)s))
                """,
                {
                    "user_id": self._owner_user_id,
                    "token_hash": hash_pat(raw_refresh, self._settings),
                    "pat_token_id": pat_id,
                    "expires_at": refresh_expires_at,
                },
            )

        return OAuthToken(
            access_token=raw_access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=raw_refresh,
        )

    def _load_refresh_token(self, refresh_token: str) -> _RefreshToken | None:
        token_hash = hash_pat(refresh_token, self._settings)
        with connection() as conn:
            row = conn.execute(
                "select refresh_token_id, user_id, pat_token_id from app.authenticate_oauth_refresh_token(%(h)s)",
                {"h": token_hash},
            ).fetchone()
            conn.commit()
        if row is None:
            return None
        return _RefreshToken(
            token=refresh_token,
            client_id=self._client.client_id or "",
            scopes=list(FULL_SCOPES),
            subject=str(row["user_id"]),
            pat_token_id=row["pat_token_id"],
            refresh_token_row_id=row["refresh_token_id"],
        )

    def _rotate_refresh_token(self, refresh_token: _RefreshToken, scopes: list[str]) -> OAuthToken:
        with user_transaction(self._owner_user_id) as conn:
            self._revoke_rows(conn, refresh_token.pat_token_id, refresh_token.refresh_token_row_id)
        return self._mint_tokens(scopes)

    def _load_access_token(self, token: str) -> _AccessToken | None:
        token_hash = hash_pat(token, self._settings)
        with connection() as conn:
            row = conn.execute(
                "select token_id, user_id, scopes from app.authenticate_pat(%(h)s)",
                {"h": token_hash},
            ).fetchone()
            conn.commit()
        if row is None:
            return None
        return _AccessToken(
            token=token,
            client_id=self._client.client_id or "",
            scopes=list(row["scopes"] or ()),
            subject=str(row["user_id"]),
            pat_token_id=row["token_id"],
        )

    def _revoke(self, token: _AccessToken | _RefreshToken) -> None:
        with user_transaction(self._owner_user_id) as conn:
            if isinstance(token, _RefreshToken):
                self._revoke_rows(conn, token.pat_token_id, token.refresh_token_row_id)
            else:
                self._revoke_rows(conn, token.pat_token_id, None)

    def _revoke_rows(self, conn: Any, pat_token_id: UUID, refresh_token_row_id: UUID | None) -> None:
        conn.execute(
            """
            update personal_access_tokens
            set revoked_at = coalesce(revoked_at, now())
            where id = %(id)s and user_id = %(user_id)s
            """,
            {"id": pat_token_id, "user_id": self._owner_user_id},
        )
        if refresh_token_row_id is not None:
            conn.execute(
                """
                update oauth_refresh_tokens
                set revoked_at = coalesce(revoked_at, now())
                where id = %(id)s and user_id = %(user_id)s
                """,
                {"id": refresh_token_row_id, "user_id": self._owner_user_id},
            )


def build_oauth_routes(settings: Settings, provider: SingleOwnerOAuthProvider | None = None) -> list[Route]:
    """Authorization-server routes (/authorize, /token, /revoke, discovery)
    plus RFC 9728 protected-resource metadata for /mcp. Caller is responsible
    for checking that OAuth is actually configured before calling this.

    Accepts a pre-built provider so tests can hold a reference to inspect or
    mutate its in-memory state; production always lets this construct one."""
    if settings.oauth_issuer_url is None:
        raise ValueError("OAUTH_ISSUER_URL is required to build OAuth routes")

    provider = provider or SingleOwnerOAuthProvider(settings)
    issuer_url = AnyHttpUrl(str(settings.oauth_issuer_url))
    routes = create_auth_routes(
        provider,
        issuer_url=issuer_url,
        client_registration_options=ClientRegistrationOptions(enabled=False),
        revocation_options=RevocationOptions(enabled=True),
    )
    routes += create_protected_resource_routes(
        resource_url=AnyHttpUrl(settings.oauth_resource_server_url()),
        authorization_servers=[issuer_url],
        scopes_supported=list(FULL_SCOPES),
        resource_name=settings.app_name,
    )
    return routes
