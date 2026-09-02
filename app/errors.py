class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class ValidationReferenceError(Exception):
    pass


class InvalidUploadError(Exception):
    pass


class StorageConfigurationError(Exception):
    pass


class StorageOperationError(Exception):
    pass


class StorageObjectNotFoundError(StorageOperationError):
    pass


class UploadRateLimitError(Exception):
    pass


class PrincipalConfigurationError(Exception):
    pass


class ExternalLookupError(Exception):
    pass
