from uuid import UUID

import httpx
import pytest

from app.pat_verification import VerifyCode, verification_target, verify_credential

OWNER = UUID("33333333-3333-3333-3333-333333333333")
TOKEN = UUID("44444444-4444-4444-4444-444444444444")


@pytest.mark.parametrize(
    "target",
    [
        "https://user:password@example.test",
        "https://example.test?secret=abc",
        "https://example.test/#frag",
        "http://example.test",
        "https://example.test/mcp",
    ],
)
def test_rejects_unsafe_target(target: str) -> None:
    with pytest.raises(ValueError):
        verification_target(target)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, VerifyCode.AUTH_REJECTED),
        (403, VerifyCode.VERIFICATION_DENIED),
        (404, VerifyCode.TARGET_INCOMPATIBLE),
        (429, VerifyCode.VERIFICATION_UNAVAILABLE),
        (503, VerifyCode.VERIFICATION_UNAVAILABLE),
        (302, VerifyCode.TARGET_INCOMPATIBLE),
    ],
)
def test_failure_statuses(status: int, code: VerifyCode) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.host == "example.test"
        return httpx.Response(status, headers={"Location": "https://other.test/"})

    result = verify_credential(
        "https://example.test", "sentinel-secret", OWNER, TOKEN, transport=httpx.MockTransport(handler)
    )
    assert result.code == code
    assert calls == 1


def test_matching_identity_and_restricted_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sentinel-secret"
        return httpx.Response(
            200,
            json={
                "service": "holy-spend",
                "response": "pat-verification-v1",
                "user_id": str(OWNER),
                "token_id": str(TOKEN),
                "scopes": ["taxonomy:read"],
            },
        )

    result = verify_credential(
        "https://example.test",
        "sentinel-secret",
        OWNER,
        TOKEN,
        {"taxonomy:read"},
        transport=httpx.MockTransport(handler),
    )
    assert result.code == VerifyCode.VERIFIED


def test_html_and_health_json_are_incompatible() -> None:
    for response in (httpx.Response(200, text="<html>ok</html>"), httpx.Response(200, json={"status": "ok"})):
        result = verify_credential(
            "https://example.test",
            "sentinel-secret",
            OWNER,
            TOKEN,
            transport=httpx.MockTransport(lambda _request, response=response: response),
        )
        assert result.code == VerifyCode.TARGET_INCOMPATIBLE
