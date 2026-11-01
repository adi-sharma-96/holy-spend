import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth_events import correlation_id, emit_auth_event
from app.config import Settings, get_settings
from app.db import connection

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    token_id: UUID
    scopes: tuple[str, ...]


def generate_pat() -> str:
    return f"det_{secrets.token_urlsafe(32)}"


def hash_pat(token: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    pepper = active_settings.pat_pepper.get_secret_value().encode("utf-8")
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def candidate_pat_hashes(token: str, settings: Settings, now: datetime | None = None) -> tuple[str, ...]:
    current = hash_pat(token, settings)
    deadline = settings.pat_previous_pepper_retire_at
    previous = settings.pat_previous_pepper
    if previous is None or deadline is None or (now or datetime.now(UTC)) >= deadline:
        return (current,)
    old_hash = hmac.new(previous.get_secret_value().encode(), token.encode(), hashlib.sha256).hexdigest()
    return (current, old_hash)


def require_scope(user: AuthenticatedUser, scope: str) -> None:
    if scope not in user.scopes and "*" not in user.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> AuthenticatedUser:
    started = monotonic()
    correlation = correlation_id(request.headers.get("x-correlation-id"))
    request.state.auth_correlation_id = correlation
    if credentials is None or credentials.scheme.lower() != "bearer":
        emit_auth_event(
            "pat_auth",
            "rejected",
            "api",
            settings.environment,
            int((monotonic() - started) * 1000),
            correlation,
            reason="missing_credential",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )

    token_hashes = candidate_pat_hashes(credentials.credentials, settings)
    try:
        with connection() as conn:
            row = None
            for token_hash in token_hashes:
                row = conn.execute(
                    "select token_id, user_id, scopes from app.authenticate_pat(%(token_hash)s)",
                    {"token_hash": token_hash},
                ).fetchone()
                if row is not None:
                    break
            if row is not None:
                conn.commit()
    except Exception:
        emit_auth_event(
            "pat_auth",
            "unavailable",
            "database",
            settings.environment,
            int((monotonic() - started) * 1000),
            correlation,
            reason="database_error",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication unavailable"
        ) from None
    if row is None:
        emit_auth_event(
            "pat_auth",
            "rejected",
            "api",
            settings.environment,
            int((monotonic() - started) * 1000),
            correlation,
            reason="credential_unknown",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    emit_auth_event(
        "pat_auth", "accepted", "api", settings.environment, int((monotonic() - started) * 1000), correlation
    )

    return AuthenticatedUser(
        user_id=row["user_id"],
        token_id=row["token_id"],
        scopes=tuple(row["scopes"] or ()),
    )
