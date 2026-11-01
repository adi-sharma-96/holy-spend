import asyncio
import hashlib
import secrets
import time
from contextvars import ContextVar
from time import monotonic
from typing import Any, cast
from uuid import UUID, uuid4

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.auth_events import emit_auth_event
from app.config import Settings
from app.db import connection, user_transaction
from app.security import candidate_pat_hashes, generate_pat, hash_pat

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
_token_request_resource: ContextVar[str | None] = ContextVar("oauth_token_request_resource", default=None)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def generate_authorization_code() -> str:
    return secrets.token_urlsafe(32)


class _AccessToken(AccessToken):
    pat_token_id: UUID


class _RefreshToken(RefreshToken):
    pat_token_id: UUID
    refresh_token_row_id: UUID


def hash_authorization_code(code: str) -> str:
    """SHA-256 is sufficient for independently generated 256-bit random codes."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class _InvalidAuthorizationCode(Exception):
    pass


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
    rotation is handled separately from authorization-code redemption.
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

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if client_id == self._client.client_id:
            return self._client
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Dynamic client registration is disabled; use the pre-shared client")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        code = generate_authorization_code()
        await asyncio.to_thread(self._store_authorization_code, code, client, params)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    def _store_authorization_code(
        self, code: str, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> None:
        with user_transaction(self._owner_user_id) as conn:
            conn.execute(
                """insert into oauth_authorization_codes
                   (code_hash, user_id, client_id, redirect_uri,
                    redirect_uri_provided_explicitly, code_challenge, scopes, resource, expires_at)
                   values (%(code_hash)s, %(user_id)s, %(client_id)s, %(redirect_uri)s,
                           %(explicit)s, %(challenge)s, %(scopes)s, %(resource)s,
                           now() + make_interval(secs => %(ttl)s))""",
                {
                    "code_hash": hash_authorization_code(code),
                    "user_id": self._owner_user_id,
                    "client_id": client.client_id,
                    "redirect_uri": str(params.redirect_uri),
                    "explicit": params.redirect_uri_provided_explicitly,
                    "challenge": params.code_challenge,
                    "scopes": list(params.scopes) if params.scopes else list(FULL_SCOPES),
                    "resource": params.resource,
                    "ttl": AUTHORIZATION_CODE_TTL_SECONDS,
                },
            )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        row = await asyncio.to_thread(self._load_authorization_code, client, authorization_code)
        if row is None:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=list(row["scopes"]),
            expires_at=row["expires_at"].timestamp(),
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            resource=row["resource"],
            subject=str(row["user_id"]),
        )

    def _load_authorization_code(self, client: OAuthClientInformationFull, code: str) -> dict[str, Any] | None:
        with user_transaction(self._owner_user_id) as conn:
            row = conn.execute(
                """select user_id, client_id, redirect_uri, redirect_uri_provided_explicitly,
                          code_challenge, scopes, resource, expires_at
                   from oauth_authorization_codes
                   where code_hash = %(code_hash)s and user_id = %(user_id)s
                     and client_id = %(client_id)s and expires_at > now()""",
                {
                    "code_hash": hash_authorization_code(code),
                    "user_id": self._owner_user_id,
                    "client_id": client.client_id,
                },
            ).fetchone()
            return cast(dict[str, Any] | None, row)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        return await asyncio.to_thread(self._redeem_authorization_code, client, authorization_code)

    def _redeem_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        started = monotonic()
        try:
            result = self._redeem_authorization_code_transaction(client, authorization_code)
        except _InvalidAuthorizationCode:
            emit_auth_event(
                "oauth_redemption",
                "rejected",
                "oauth",
                self._settings.environment,
                int((monotonic() - started) * 1000),
                reason="code_invalid",
            )
            raise TokenError(error="invalid_grant", error_description="authorization code does not exist") from None
        except Exception:
            emit_auth_event(
                "oauth_redemption",
                "unavailable",
                "database",
                self._settings.environment,
                int((monotonic() - started) * 1000),
                reason="database_error",
            )
            raise
        emit_auth_event(
            "oauth_redemption", "succeeded", "oauth", self._settings.environment, int((monotonic() - started) * 1000)
        )
        return result

    def _redeem_authorization_code_transaction(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with user_transaction(self._owner_user_id) as conn:
            row = conn.execute(
                """delete from oauth_authorization_codes
                   where code_hash = %(code_hash)s and user_id = %(user_id)s
                     and client_id = %(client_id)s
                   returning user_id, client_id, redirect_uri,
                          redirect_uri_provided_explicitly, code_challenge, scopes,
                          resource, expires_at""",
                {
                    "code_hash": hash_authorization_code(authorization_code.code),
                    "user_id": self._owner_user_id,
                    "client_id": client.client_id,
                },
            ).fetchone()
            # DELETE has acquired the row lock before this clock read. If the
            # code expired while waiting, _InvalidAuthorizationCode rolls the
            # deletion back. now() would still report transaction start time.
            checked_at = conn.execute("select clock_timestamp() as checked_at").fetchone()["checked_at"]
            if row is None or (
                row["expires_at"] <= checked_at
                or row["user_id"] != self._owner_user_id
                or row["client_id"] != authorization_code.client_id
                or row["redirect_uri"] != str(authorization_code.redirect_uri)
                or row["redirect_uri_provided_explicitly"] != authorization_code.redirect_uri_provided_explicitly
                or row["code_challenge"] != authorization_code.code_challenge
                or list(row["scopes"]) != list(authorization_code.scopes)
                or row["resource"] != authorization_code.resource
                or (_token_request_resource.get() is not None and row["resource"] != _token_request_resource.get())
                or authorization_code.subject != str(self._owner_user_id)
            ):
                # A mismatched loaded object must not consume the persisted code.
                raise _InvalidAuthorizationCode
            return self._insert_tokens(conn, list(row["scopes"]))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> _RefreshToken | None:
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

    def _mint_tokens(self, scopes: list[str]) -> OAuthToken:
        with user_transaction(self._owner_user_id) as conn:
            return self._insert_tokens(conn, scopes)

    def _insert_tokens(self, conn: Any, scopes: list[str]) -> OAuthToken:
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
        with connection() as conn:
            row = None
            for token_hash in candidate_pat_hashes(refresh_token, self._settings):
                row = conn.execute(
                    "select refresh_token_id, user_id, pat_token_id from app.authenticate_oauth_refresh_token(%(h)s)",
                    {"h": token_hash},
                ).fetchone()
                if row is not None:
                    break
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
        with connection() as conn:
            row = None
            for token_hash in candidate_pat_hashes(token, self._settings):
                row = conn.execute(
                    "select token_id, user_id, scopes from app.authenticate_pat(%(h)s)",
                    {"h": token_hash},
                ).fetchone()
                if row is not None:
                    break
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

    Accepts a pre-built provider for tests; production constructs one."""
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
    # MCP SDK 1.29 validates PKCE and redirect URI but does not forward the
    # parsed token-request resource to the provider callback. Preserve its
    # handler while making an explicit resource available to the transaction.
    for route in routes:
        if isinstance(route, Route) and route.path == "/token":
            original_app = route.app

            async def bound_token_app(
                scope: Scope, receive: Receive, send: Send, original_app: Any = original_app
            ) -> None:
                request = Request(scope, receive)
                body = await request.body()
                content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/x-www-form-urlencoded":
                    await JSONResponse(
                        {"error": "invalid_request", "error_description": "Unsupported token request encoding"},
                        status_code=400,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                    )(scope, receive, send)
                    return
                try:
                    form = await request.form()
                except Exception:
                    await JSONResponse(
                        {"error": "invalid_request", "error_description": "Invalid token request form"},
                        status_code=400,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                    )(scope, receive, send)
                    return
                if any(len(form.getlist(key)) != 1 for key in form):
                    await JSONResponse(
                        {"error": "invalid_request", "error_description": "Duplicate token request parameter"},
                        status_code=400,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                    )(scope, receive, send)
                    return
                resource = form.get("resource") if form.get("grant_type") == "authorization_code" else None
                context = _token_request_resource.set(str(resource) if resource is not None else None)
                replayed = False

                async def replay_receive() -> Any:
                    nonlocal replayed
                    if not replayed:
                        replayed = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                try:
                    await original_app(scope, replay_receive, send)
                finally:
                    _token_request_resource.reset(context)

            route.app = bound_token_app
            break
    routes += create_protected_resource_routes(
        resource_url=AnyHttpUrl(settings.oauth_resource_server_url()),
        authorization_servers=[issuer_url],
        scopes_supported=list(FULL_SCOPES),
        resource_name=settings.app_name,
    )
    return routes
