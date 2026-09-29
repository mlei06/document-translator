"""Service errors with stable codes and HTTP statuses; messages never contain document text."""

__all__ = [
    "AdmissionError",
    "ConflictError",
    "DocumentRejectedError",
    "InvalidRequestError",
    "NotFoundError",
    "ServiceError",
    "TooLargeError",
    "UnavailableError",
]


class ServiceError(Exception):
    code = "service_error"
    status = 500
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, **details: object) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details


class InvalidRequestError(ServiceError):
    code = "invalid_request"
    status = 422


class NotFoundError(ServiceError):
    """Absent and other-user resources look the same (ADR-015)."""

    code = "not_found"
    status = 404

    def __init__(self, kind: str) -> None:
        super().__init__(f"{kind} not found")


class ConflictError(ServiceError):
    code = "conflict"
    status = 409


class TooLargeError(ServiceError):
    code = "file_too_large"
    status = 413


class DocumentRejectedError(ServiceError):
    """The file was read completely and cannot be accepted (415 unsupported, 422 invalid)."""

    def __init__(self, message: str, *, code: str, status: int, item_id: str | None = None) -> None:
        super().__init__(message, code=code)
        self.status = status
        self.item_id = item_id


class AdmissionError(ServiceError):
    code = "queue_full"
    status = 429
    retryable = True
    retry_after_s = 5


class UnavailableError(ServiceError):
    code = "unavailable"
    status = 503
    retryable = True
