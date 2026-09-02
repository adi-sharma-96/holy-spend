import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


def require_scope(user: AuthenticatedUser, scope: str) -> None:
    if scope not in user.scopes and "*" not in user.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )

    token_hash = hash_pat(credentials.credentials, settings)
    with connection() as conn:
        row = conn.execute(
            """
            select token_id, user_id, scopes
            from app.authenticate_pat(%(token_hash)s)
            """,
            {"token_hash": token_hash},
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        conn.commit()

    return AuthenticatedUser(
        user_id=row["user_id"],
        token_id=row["token_id"],
        scopes=tuple(row["scopes"] or ()),
    )
