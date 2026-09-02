from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Holy Spend"
    environment: str = "local"
    database_url: str = Field(default="postgresql://expense_app:change-me@localhost:54322/postgres")
    pat_pepper: SecretStr = Field(default=SecretStr("dev-only-change-me"))
    reconciliation_accepted_cents: int = 2
    reconciliation_warning_cents: int = 100
    supported_currencies: tuple[str, ...] = ("CAD", "USD")
    # This is a single-user deployment: "today" for dashboard windows, the
    # spending calendar, and future-date validation follows the owner's own
    # calendar day, not the server container's (default UTC) system clock.
    local_timezone: str = "America/New_York"
    auth_mode: Literal["pat", "single_user"] = "single_user"
    owner_user_id: UUID | None = None
    mcp_enabled: bool = False
    mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*"
    mcp_allowed_origins: str = ""
    mcp_widget_connect_domains: str = ""
    mcp_widget_resource_domains: str = ""
    # Actual browser CORS (preflight + response headers) for the public gateway's
    # /mcp, /authorize, and /token endpoints - distinct from mcp_allowed_origins
    # above, which only feeds the MCP SDK's own Origin-header DNS-rebinding check
    # on the private mcp service and never applies here. Defaults to the two
    # platforms this app is actually built for; override to narrow or extend it.
    cors_allowed_origins: str = "https://claude.ai,https://chatgpt.com,https://chat.openai.com"
    # When set, this process does not run its own MCP server. Instead it
    # exposes a PAT-authenticated reverse proxy at /mcp that streams every
    # request to this upstream Streamable HTTP endpoint (a private-network
    # MCP service, e.g. Railway internal DNS). Lets a public, already
    # PAT-authenticated service front an otherwise unauthenticated
    # single_user MCP backend for hosts that need a public HTTPS entry
    # point (Claude) without touching that backend's existing callers.
    mcp_gateway_upstream_url: HttpUrl | None = None
    # Railway's private networking makes an upstream request implicitly trusted just by
    # being unreachable from outside; Cloud Run has no equivalent for two plain services
    # calling each other without a paid VPC connector. When true, the gateway instead
    # attaches a Google-signed ID token (audience = mcp_gateway_upstream_url) to every
    # upstream request, and the mcp Cloud Run service is deployed with
    # --no-allow-unauthenticated so only a caller holding that exact token (this
    # service's own service account, granted roles/run.invoker) can ever reach it.
    mcp_gateway_use_google_id_token: bool = False
    # Enables the gateway's OAuth 2.1 authorization server (app/oauth_provider.py)
    # for hosts that cannot use a static bearer header (e.g. Claude's consumer
    # apps). oauth_issuer_url is this service's own public origin, used both as
    # the OAuth issuer and to derive the protected-resource identifier
    # (issuer + "/mcp"). The client is a single pre-shared credential, not
    # dynamic registration: generate oauth_client_id/secret yourself and enter
    # them in the connecting host's OAuth client fields.
    oauth_client_id: str | None = None
    oauth_client_secret: SecretStr | None = None
    oauth_issuer_url: HttpUrl | None = None
    # The pre-shared OAuth client is shared by every connecting host (Claude,
    # ChatGPT, ...); each host's own callback URL must be pre-registered here.
    # Claude's is a fixed constant (see oauth_provider.CLAUDE_REDIRECT_URI);
    # ChatGPT mints a fresh one per connector instance, so it belongs in an
    # env var rather than source, and needs updating if that connector is
    # ever deleted and recreated.
    oauth_additional_redirect_uris: str = ""
    supabase_url: HttpUrl | None = None
    supabase_secret_key: SecretStr | None = None
    storage_bucket: str = "receipt-originals"
    storage_signed_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    max_receipt_file_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)
    receipt_download_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    receipt_download_read_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    receipt_download_write_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    receipt_download_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    receipt_download_max_redirects: int = Field(default=3, ge=0, le=5)
    # Read server-side only, by the nutrition_lookup_usda(_detail) MCP tools - never sent
    # to or through a connecting client, so a scheduled task never needs its own key.
    # DEMO_KEY works but is rate-limited to ~30 requests/hour; a free personal key from
    # https://fdc.nal.usda.gov/api-key-signup.html raises that substantially.
    usda_fdc_api_key: SecretStr = Field(default=SecretStr("DEMO_KEY"))
    nutrition_lookup_timeout_seconds: float = Field(default=15.0, gt=0, le=60)

    @field_validator("local_timezone")
    @classmethod
    def validate_local_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"LOCAL_TIMEZONE must be a valid IANA timezone name: {value}") from error
        return value

    @field_validator("storage_bucket")
    @classmethod
    def validate_storage_bucket(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate or "/" in candidate or "\\" in candidate:
            raise ValueError("STORAGE_BUCKET must be a single non-empty bucket name")
        return candidate

    @model_validator(mode="after")
    def validate_mcp_mode_exclusive(self) -> "Settings":
        if self.mcp_enabled and self.mcp_gateway_upstream_url is not None:
            raise ValueError(
                "MCP_ENABLED and MCP_GATEWAY_UPSTREAM_URL are mutually exclusive: "
                "a process either runs its own MCP server or proxies to one, not both"
            )
        return self

    @model_validator(mode="after")
    def validate_google_id_token_requires_gateway(self) -> "Settings":
        if self.mcp_gateway_use_google_id_token and self.mcp_gateway_upstream_url is None:
            raise ValueError(
                "MCP_GATEWAY_USE_GOOGLE_ID_TOKEN requires MCP_GATEWAY_UPSTREAM_URL: "
                "it only applies to the gateway's upstream call"
            )
        return self

    @model_validator(mode="after")
    def validate_oauth_requires_gateway(self) -> "Settings":
        oauth_fields = (self.oauth_client_id, self.oauth_client_secret, self.oauth_issuer_url)
        if any(field is not None for field in oauth_fields):
            if not all(field is not None for field in oauth_fields):
                raise ValueError(
                    "OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_ISSUER_URL must be set together"
                )
            if self.mcp_gateway_upstream_url is None:
                raise ValueError("OAuth settings require MCP_GATEWAY_UPSTREAM_URL: it only applies to the gateway")
        return self

    def storage_credentials(self) -> tuple[str, str]:
        if self.supabase_url is None or self.supabase_secret_key is None:
            raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required for receipt storage")
        secret = self.supabase_secret_key.get_secret_value()
        if not secret:
            raise ValueError("SUPABASE_SECRET_KEY must not be empty")
        return str(self.supabase_url).rstrip("/"), secret

    def widget_connect_domains(self) -> tuple[str, ...]:
        domains = set(self._split_origins(self.mcp_widget_connect_domains))
        if self.supabase_url is not None:
            parsed = urlsplit(str(self.supabase_url))
            domains.add(f"{parsed.scheme}://{parsed.netloc}")
        return tuple(sorted(domains))

    def allowed_mcp_hosts(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.mcp_allowed_hosts.split(",") if item.strip())

    def allowed_mcp_origins(self) -> tuple[str, ...]:
        return self._split_origins(self.mcp_allowed_origins)

    def allowed_cors_origins(self) -> tuple[str, ...]:
        return self._split_origins(self.cors_allowed_origins)

    def widget_resource_domains(self) -> tuple[str, ...]:
        return self._split_origins(self.mcp_widget_resource_domains)

    def oauth_resource_server_url(self) -> str:
        if self.oauth_issuer_url is None:
            raise ValueError("OAUTH_ISSUER_URL is required to compute the resource server URL")
        return str(self.oauth_issuer_url).rstrip("/") + "/mcp"

    def additional_oauth_redirect_uris(self) -> tuple[str, ...]:
        uris: list[str] = []
        for item in self.oauth_additional_redirect_uris.split(","):
            candidate = item.strip()
            if not candidate:
                continue
            parsed = urlsplit(candidate)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"OAUTH_ADDITIONAL_REDIRECT_URIS must be absolute HTTP(S) URLs: {candidate}")
            uris.append(candidate)
        return tuple(dict.fromkeys(uris))

    @staticmethod
    def _split_origins(value: str) -> tuple[str, ...]:
        origins: list[str] = []
        for item in value.split(","):
            candidate = item.strip().rstrip("/")
            if not candidate:
                continue
            parsed = urlsplit(candidate)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
                raise ValueError(f"Widget CSP domain must be an HTTP(S) origin: {candidate}")
            origins.append(candidate)
        return tuple(sorted(set(origins)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
