from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.config import Settings
from app.errors import PrincipalConfigurationError


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    auth_mode: Literal["single_user"]


class SingleUserPrincipalResolver:
    """Maps every MCP call to the server-configured owner identity."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve(self) -> Principal:
        if self.settings.auth_mode != "single_user":
            raise PrincipalConfigurationError(
                "MCP requires AUTH_MODE=single_user for the private single-owner release"
            )
        if self.settings.owner_user_id is None or self.settings.owner_user_id.int == 0:
            raise PrincipalConfigurationError(
                "OWNER_USER_ID must be set to the existing Supabase profile UUID"
            )
        return Principal(user_id=self.settings.owner_user_id, auth_mode="single_user")
