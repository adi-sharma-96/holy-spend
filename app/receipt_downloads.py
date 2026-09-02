import hashlib
import ipaddress
import socket
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from app.config import Settings
from app.errors import InvalidUploadError
from app.models import OpenAIFileInput
from app.receipt_files import ALLOWED_RECEIPT_TYPES, READ_CHUNK_BYTES, sanitize_and_validate_filename

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
GENERIC_BINARY_MIME_TYPES = {"application/octet-stream", "binary/octet-stream"}


@dataclass(frozen=True)
class DownloadedReceipt:
    content: bytes
    filename: str
    mime_type: str
    byte_size: int
    sha256: str


def detected_receipt_mime(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise InvalidUploadError("Downloaded file is not a supported JPEG, PNG, WebP, or PDF receipt")


def _public_addresses(host: str, port: int) -> list[str]:
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise httpcore.ConnectError("Remote receipt host could not be resolved") from error
    addresses = list(dict.fromkeys(str(candidate[4][0]) for candidate in resolved))
    if not addresses:
        raise httpcore.ConnectError("Remote receipt host could not be resolved")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise httpcore.ConnectError("Remote receipt host is not publicly routable")
    return addresses


class PinnedDNSBackend(httpcore.NetworkBackend):
    """Resolve once, reject every non-public answer, then connect to a pinned IP."""

    def __init__(self) -> None:
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for address in _public_addresses(host, port):
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("Remote receipt host could not be reached")

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        del path, timeout, socket_options
        raise httpcore.ConnectError("Unix sockets are not allowed for receipt downloads")


class PinnedDNSHTTPTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=5,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=PinnedDNSBackend(),
        )


class RemoteReceiptDownloader:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._external_client = client

    def download(self, supplied: OpenAIFileInput) -> DownloadedReceipt:
        current_url = supplied.download_url
        timeout = httpx.Timeout(
            connect=self.settings.receipt_download_connect_timeout_seconds,
            read=self.settings.receipt_download_read_timeout_seconds,
            write=self.settings.receipt_download_write_timeout_seconds,
            pool=self.settings.receipt_download_pool_timeout_seconds,
        )
        owned_client = self._external_client is None
        client = self._external_client or httpx.Client(
            transport=PinnedDNSHTTPTransport(),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "image/jpeg, image/png, image/webp, application/pdf"},
        )
        try:
            for redirect_count in range(self.settings.receipt_download_max_redirects + 1):
                self._validate_url(current_url)
                try:
                    with client.stream("GET", current_url, follow_redirects=False) as response:
                        if response.status_code in REDIRECT_STATUSES:
                            if redirect_count >= self.settings.receipt_download_max_redirects:
                                raise InvalidUploadError("Receipt download exceeded the redirect limit")
                            location = response.headers.get("location")
                            if not location:
                                raise InvalidUploadError("Receipt download redirect was missing a location")
                            current_url = urljoin(current_url, location)
                            continue
                        if not 200 <= response.status_code < 300:
                            raise InvalidUploadError(
                                f"Receipt download failed with HTTP status {response.status_code}"
                            )
                        return self._read_response(response, supplied)
                except httpx.TimeoutException as error:
                    raise InvalidUploadError("Receipt download timed out") from error
                except httpx.HTTPError as error:
                    raise InvalidUploadError("Receipt download failed") from error
            raise InvalidUploadError("Receipt download exceeded the redirect limit")
        finally:
            if owned_client:
                client.close()

    def _read_response(
        self,
        response: httpx.Response,
        supplied: OpenAIFileInput,
    ) -> DownloadedReceipt:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as error:
                raise InvalidUploadError("Receipt download returned an invalid Content-Length") from error
            if declared_size < 0:
                raise InvalidUploadError("Receipt download returned an invalid Content-Length")
            if declared_size > self.settings.max_receipt_file_bytes:
                raise InvalidUploadError(
                    f"Receipt file exceeds the {self.settings.max_receipt_file_bytes}-byte limit"
                )

        content = bytearray()
        digest = hashlib.sha256()
        for chunk in response.iter_bytes(READ_CHUNK_BYTES):
            if not chunk:
                continue
            if len(content) + len(chunk) > self.settings.max_receipt_file_bytes:
                raise InvalidUploadError(
                    f"Receipt file exceeds the {self.settings.max_receipt_file_bytes}-byte limit"
                )
            content.extend(chunk)
            digest.update(chunk)
        if not content:
            raise InvalidUploadError("Receipt download returned an empty file")

        body = bytes(content)
        detected_mime = detected_receipt_mime(body)
        # File metadata and response Content-Type are advisory. Supported magic
        # bytes are authoritative so a safe JPEG/PNG/PDF is not rejected merely
        # because a host supplied a generic or incorrect MIME label.
        original_name = supplied.file_name.strip() or "receipt"
        original_stem = Path(original_name).stem or "receipt"
        original_name = f"{original_stem}{MIME_EXTENSIONS[detected_mime]}"
        safe_filename, normalized_mime = sanitize_and_validate_filename(original_name, detected_mime)
        if Path(safe_filename).suffix.lower() not in ALLOWED_RECEIPT_TYPES:
            raise InvalidUploadError("Unsupported receipt file extension")
        return DownloadedReceipt(
            content=body,
            filename=safe_filename,
            mime_type=normalized_mime,
            byte_size=len(body),
            sha256=digest.hexdigest(),
        )

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise InvalidUploadError("Receipt download URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidUploadError("Receipt download URL must not contain credentials")
        try:
            port = parsed.port
        except ValueError as error:
            raise InvalidUploadError("Receipt download URL contains an invalid port") from error
        if port not in {None, 443}:
            raise InvalidUploadError("Receipt download URL must use the standard HTTPS port")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise InvalidUploadError("Receipt download host is not publicly routable")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return
        if not address.is_global:
            raise InvalidUploadError("Receipt download host is not publicly routable")
