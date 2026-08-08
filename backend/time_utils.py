"""Shared time normalization helpers for durable MootOS timestamps."""

from datetime import datetime, timezone
from typing import Optional


def normalize_optional_utc_datetime(
    value: Optional[str],
    *,
    field_name: str,
) -> Optional[str]:
    """Normalize an optional timezone-aware ISO 8601 datetime to UTC."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime") from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")

    return parsed.astimezone(timezone.utc).isoformat()
