"""Time handling. ADR-0016: everything is UTC ISO-8601 with an explicit 'Z'.

Domain functions never call ``now()`` themselves -- the current instant is always
passed in as a parameter. That is what makes expiry, freshness and deadline logic
deterministically testable without patching the system clock.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

UTC = UTC
IST = timezone(timedelta(hours=5, minutes=30))  # Asia/Kolkata, no DST


def now_utc() -> datetime:
    """The only sanctioned clock read. Call at the edge (handlers/jobs), not in domain logic."""
    return datetime.now(UTC)


def to_iso(dt: datetime | None) -> str | None:
    """Serialize as ISO-8601 with a literal 'Z'. Naive datetimes are rejected."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError("naive datetime cannot be serialized; attach a timezone")
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | datetime | None) -> datetime | None:
    """Parse ISO-8601 into an aware UTC datetime. Returns None for None/empty.

    A string without timezone information is rejected rather than assumed to be UTC --
    silently guessing the zone is how expiry bugs get introduced (spec 12.1).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime is not accepted")
        return value.astimezone(UTC)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp '{value}' has no timezone designator")
    return parsed.astimezone(UTC)


def ensure_aware(value: datetime, field: str = "timestamp") -> datetime:
    """Return ``value`` as aware UTC, refusing a naive datetime.

    Separate from :func:`parse_iso` because callers that already hold a
    ``datetime`` should not have to round-trip it through a string to get the
    same guarantee. Names the offending field, since "naive datetime is not
    accepted" on its own is a poor error when several timestamps are in play.
    """
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware; got a naive datetime")
    return value.astimezone(UTC)


def to_ist_display(dt: datetime | None) -> str | None:
    """Render for the UI edge only. Never used for computation."""
    if dt is None:
        return None
    return dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def hours_between(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0
