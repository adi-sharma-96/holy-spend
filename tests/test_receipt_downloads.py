import hashlib
import socket

import httpcore
import httpx
import pytest

from app.config import Settings
from app.errors import InvalidUploadError
from app.models import OpenAIFileInput
from app.receipt_downloads import PinnedDNSBackend, RemoteReceiptDownloader

SAMPLES = {
    "image/jpeg": (b"\xff\xd8\xff\xe0jpeg", "receipt.jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\npng", "receipt.png"),
    "image/webp": (b"RIFF\x04\x00\x00\x00WEBPdata", "receipt.webp"),
    "application/pdf": (b"%PDF-1.7\npdf", "receipt.pdf"),
}


def downloader(
    handler: httpx.MockTransport,
    *,
    max_bytes: int = 1024,
    max_redirects: int = 3,
) -> RemoteReceiptDownloader:
    settings = Settings(
        _env_file=None,
        max_receipt_file_bytes=max_bytes,
        receipt_download_max_redirects=max_redirects,
    )
    return RemoteReceiptDownloader(
        settings,
        client=httpx.Client(transport=handler, follow_redirects=False),
    )


@pytest.mark.parametrize(("mime_type", "sample"), SAMPLES.items())
def test_supported_receipt_formats_download_successfully(
    mime_type: str,
    sample: tuple[bytes, str],
) -> None:
    content, filename = sample
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"Content-Type": mime_type, "Content-Length": str(len(content))},
        )
    )

    result = downloader(transport).download(
        OpenAIFileInput(
            download_url="https://files.example.test/receipt?signature=secret",
            file_id="file_123",
            mime_type=mime_type,
            file_name=filename,
        )
    )

    assert result.content == content
    assert result.mime_type == mime_type
    assert result.sha256 == hashlib.sha256(content).hexdigest()


def test_optional_filename_and_mime_are_safely_derived() -> None:
    content = SAMPLES["application/pdf"][0]
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=content))

    result = downloader(transport).download(
        OpenAIFileInput(
            download_url="https://files.example.test/receipt",
            file_id="file_without_optional_metadata",
        )
    )

    assert result.filename == "receipt.pdf"
    assert result.mime_type == "application/pdf"


def test_generic_binary_mime_is_reconciled_from_filename_and_magic() -> None:
    content = SAMPLES["image/png"][0]
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
    )

    result = downloader(transport).download(
        OpenAIFileInput(
            download_url="https://files.example.test/receipt",
            file_id="file_generic_mime",
            mime_type="application/octet-stream",
            file_name="receipt.png",
        )
    )

    assert result.filename == "receipt.png"
    assert result.mime_type == "image/png"


def test_declared_content_length_over_limit_is_rejected_without_reading() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=SAMPLES["image/png"][0],
            headers={"Content-Length": "11", "Content-Type": "image/png"},
        )
    )

    with pytest.raises(InvalidUploadError, match="10-byte limit"):
        downloader(transport, max_bytes=10).download(
            OpenAIFileInput(
                download_url="https://files.example.test/receipt",
                file_id="file_too_large",
            )
        )


@pytest.mark.parametrize("declared_length", ["1", None])
def test_actual_stream_size_limit_rejects_lying_or_chunked_response(
    declared_length: str | None,
) -> None:
    headers = {"Content-Type": "image/png"}
    if declared_length is not None:
        headers["Content-Length"] = declared_length
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\n" + (b"x" * 20),
            headers=headers,
        )
    )

    with pytest.raises(InvalidUploadError, match="16-byte limit"):
        downloader(transport, max_bytes=16).download(
            OpenAIFileInput(
                download_url="https://files.example.test/receipt",
                file_id="file_stream_too_large",
            )
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.test/receipt",
        "https://localhost/receipt",
        "https://127.0.0.1/receipt",
        "https://10.0.0.1/receipt",
        "https://user:password@files.example.test/receipt",
        "https://files.example.test:444/receipt",
    ],
)
def test_untrusted_download_urls_are_rejected(url: str) -> None:
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("Rejected URL must not reach the HTTP client")
    )

    with pytest.raises(InvalidUploadError):
        downloader(transport).download(
            OpenAIFileInput(download_url=url, file_id="file_bad_url")
        )


def test_redirect_targets_are_revalidated() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    with pytest.raises(InvalidUploadError, match="not publicly routable"):
        downloader(httpx.MockTransport(handler)).download(
            OpenAIFileInput(
                download_url="https://files.example.test/receipt",
                file_id="file_redirect_private",
            )
        )

    assert calls == 1


def test_redirect_limit_is_enforced() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": str(request.url)})
    )

    with pytest.raises(InvalidUploadError, match="redirect limit"):
        downloader(transport, max_redirects=1).download(
            OpenAIFileInput(
                download_url="https://files.example.test/receipt",
                file_id="file_redirect_loop",
            )
        )


def test_timeout_and_non_success_errors_do_not_expose_signed_url() -> None:
    signed_url = "https://files.example.test/receipt?signature=top-secret"

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out at signed URL", request=request)

    with pytest.raises(InvalidUploadError) as timeout_error:
        downloader(httpx.MockTransport(timeout_handler)).download(
            OpenAIFileInput(download_url=signed_url, file_id="file_timeout")
        )
    assert "top-secret" not in str(timeout_error.value)
    assert signed_url not in str(timeout_error.value)

    with pytest.raises(InvalidUploadError) as status_error:
        downloader(
            httpx.MockTransport(lambda _request: httpx.Response(403, text="signed URL denied"))
        ).download(OpenAIFileInput(download_url=signed_url, file_id="file_forbidden"))
    assert "top-secret" not in str(status_error.value)
    assert signed_url not in str(status_error.value)


def test_empty_is_rejected_and_safe_magic_overrides_advisory_metadata() -> None:
    with pytest.raises(InvalidUploadError, match="empty"):
        downloader(
            httpx.MockTransport(lambda _request: httpx.Response(200, content=b""))
        ).download(
            OpenAIFileInput(
                download_url="https://files.example.test/empty",
                file_id="file_empty",
            )
        )

    mismatched = downloader(
            httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    content=SAMPLES["image/png"][0],
                    headers={"Content-Type": "image/png"},
                )
            )
        ).download(
            OpenAIFileInput(
                download_url="https://files.example.test/mismatch",
                file_id="file_mismatch",
                mime_type="application/pdf",
                file_name="receipt.pdf",
            )
        )
    assert mismatched.mime_type == "image/png"
    assert mismatched.filename == "receipt.png"

    mismatched_extension = downloader(
            httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    content=SAMPLES["image/png"][0],
                    headers={"Content-Type": "image/png"},
                )
            )
        ).download(
            OpenAIFileInput(
                download_url="https://files.example.test/mismatch",
                file_id="file_extension_mismatch",
                mime_type="image/png",
                file_name="receipt.pdf",
            )
        )
    assert mismatched_extension.mime_type == "image/png"
    assert mismatched_extension.filename == "receipt.png"


def test_html_and_unknown_binary_are_rejected_even_when_declared_as_images() -> None:
    for content in (b"<!doctype html><title>Login</title>", b"\x00\x01\x02unknown"):
        with pytest.raises(InvalidUploadError, match="not a supported"):
            downloader(
                httpx.MockTransport(
                    lambda _request, body=content: httpx.Response(
                        200,
                        content=body,
                        headers={"Content-Type": "image/png"},
                    )
                )
            ).download(
                OpenAIFileInput(
                    download_url="https://files.example.test/disguised",
                    file_id="file_disguised",
                    mime_type="image/png",
                    file_name="receipt.png",
                )
            )


def test_connection_backend_rejects_any_private_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )

    with pytest.raises(httpcore.ConnectError, match="not publicly routable"):
        PinnedDNSBackend().connect_tcp("files.example.test", 443)
