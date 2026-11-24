"""Domain error taxonomy.

Every error carries a stable machine-readable ``code`` so the API layer can map
it to an HTTP status without string matching, and so clients can branch on it.
"""
from __future__ import annotations


class LifeLinkError(Exception):
    """Base class. ``code`` is part of the API contract; ``message`` is for humans."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(LifeLinkError):
    code = "VALIDATION_ERROR"
    http_status = 400


class NotFoundError(LifeLinkError):
    code = "NOT_FOUND"
    http_status = 404


class UnauthenticatedError(LifeLinkError):
    code = "UNAUTHENTICATED"
    http_status = 401


class ForbiddenError(LifeLinkError):
    code = "FORBIDDEN"
    http_status = 403


class AccountSuspendedError(ForbiddenError):
    code = "ACCOUNT_SUSPENDED"


class CrossOrganizationError(ForbiddenError):
    """Caller authenticated, but the resource belongs to another organization."""

    code = "CROSS_ORGANIZATION_DENIED"


class ConflictError(LifeLinkError):
    code = "CONFLICT"
    http_status = 409


class ConcurrentModificationError(ConflictError):
    """Optimistic-concurrency version check failed. Caller should re-read and retry."""

    code = "CONCURRENT_MODIFICATION"


class DuplicateError(ConflictError):
    code = "DUPLICATE"


class RequestInProgressError(ConflictError):
    code = "REQUEST_IN_PROGRESS"


class InsufficientStockError(ConflictError):
    code = "INSUFFICIENT_STOCK"


class InvalidStateTransitionError(ConflictError):
    code = "INVALID_STATE_TRANSITION"


class CapacityExceededError(ConflictError):
    code = "CAPACITY_EXCEEDED"


class ChannelUnavailableError(LifeLinkError):
    """A notification channel is not implemented or not permitted in this account."""

    code = "CHANNEL_UNAVAILABLE"
    http_status = 503


class ProviderUnavailableError(LifeLinkError):
    """An external provider (maps, routing, geocoding) failed or timed out."""

    code = "PROVIDER_UNAVAILABLE"
    http_status = 503


class RateLimitedError(LifeLinkError):
    code = "RATE_LIMITED"
    http_status = 429
