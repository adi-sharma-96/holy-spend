from typing import Protocol


class ImageNormalizer(Protocol):
    def create_derivative(self, content: bytes, mime_type: str) -> tuple[bytes, str]: ...


class PreserveOriginalImageNormalizer:
    """V1 placeholder for future derivatives; original receipt bytes remain untouched."""

    def create_derivative(self, content: bytes, mime_type: str) -> tuple[bytes, str]:
        return content, mime_type
