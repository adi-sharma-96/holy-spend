from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from app.db import user_transaction
from app.security import AuthenticatedUser, get_current_user


@dataclass(frozen=True)
class RequestContext:
    user: AuthenticatedUser
    conn: Any


def get_request_context(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Iterator[RequestContext]:
    with user_transaction(user.user_id) as conn:
        yield RequestContext(user=user, conn=conn)
