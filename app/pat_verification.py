"""Bounded, fail-closed verification against an explicitly selected API."""

from dataclasses import dataclass
from enum import IntEnum
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx


class VerifyCode(IntEnum):
    VERIFIED = 0
    AUTH_REJECTED = 10
    IDENTITY_MISMATCH = 11
    VERIFICATION_UNAVAILABLE = 12
    TARGET_INCOMPATIBLE = 13
    VERIFICATION_DENIED = 14
    CREATED_UNVERIFIED = 15
    CONFIGURATION_ERROR = 16


@dataclass(frozen=True)
class VerifyResult:
    code: VerifyCode
    origin: str


def verification_target(base_url: str, allow_loopback_http: bool = False) -> tuple[str, str]:
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("Invalid verification target")
    if parsed.scheme == "http":
        if not allow_loopback_http or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP verification requires explicit literal loopback allowance")
    elif parsed.scheme != "https":
        raise ValueError("Verification target requires HTTPS")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Invalid verification target port") from error
    if parsed.path.rstrip("/").endswith("/mcp"):
        raise ValueError("Verification target must be a base URL, not /mcp")
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    path = parsed.path.rstrip("/") + "/v1/auth/verify"
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid verification target port")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")), origin


def verify_credential(
    base_url: str,
    token: str,
    user_id: UUID,
    token_id: UUID,
    scopes: set[str] | None = None,
    *,
    allow_loopback_http: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> VerifyResult:
    url, origin = verification_target(base_url, allow_loopback_http)
    try:
        with (
            httpx.Client(
                timeout=httpx.Timeout(connect=3, read=5, write=3, pool=3),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client,
            client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as response,
        ):
            status = response.status_code
            if status == 401:
                return VerifyResult(VerifyCode.AUTH_REJECTED, origin)
            if status == 403:
                return VerifyResult(VerifyCode.VERIFICATION_DENIED, origin)
            if status == 429 or status >= 500:
                return VerifyResult(VerifyCode.VERIFICATION_UNAVAILABLE, origin)
            if status != 200:
                return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
            length = response.headers.get("content-length", "0")
            if not length.isdecimal() or int(length) > 8192:
                return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > 8192:
                    return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
            try:
                data = httpx.Response(200, content=body).json()
            except ValueError:
                return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
    except (httpx.HTTPError, OSError, ValueError):
        return VerifyResult(VerifyCode.VERIFICATION_UNAVAILABLE, origin)
    if (
        not isinstance(data, dict)
        or data.get("service") != "holy-spend"
        or data.get("response") != "pat-verification-v1"
    ):
        return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
    try:
        actual_user = UUID(data["user_id"])
        actual_token = UUID(data["token_id"])
        actual_scopes = data["scopes"]
        if not isinstance(actual_scopes, list) or not all(isinstance(scope, str) for scope in actual_scopes):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return VerifyResult(VerifyCode.TARGET_INCOMPATIBLE, origin)
    if actual_user != user_id or actual_token != token_id or (scopes is not None and set(actual_scopes) != scopes):
        return VerifyResult(VerifyCode.IDENTITY_MISMATCH, origin)
    return VerifyResult(VerifyCode.VERIFIED, origin)
