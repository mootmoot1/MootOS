"""Deterministic ISO-8601 timestamp parsing, independent of Python version.

``datetime.fromisoformat`` accepts materially different input across
Python versions -- notably a trailing ``Z`` (UTC) suffix, which raises on
3.9/3.10 and is accepted starting in 3.11. Relying on that directly would
make timestamp validation change behavior depending only on which
interpreter happens to run this code. Normalizing ``Z`` ourselves first
makes the accepted format identical on every supported version.
"""

from datetime import datetime


def parse_timestamp(value, name, error_cls):
    """Parse a required, timezone-aware ISO-8601 timestamp.

    Raises ``error_cls(message)`` (not the raw stdlib exception) so every
    caller gets its own domain error type, uniformly, on any Python
    version this runs under.
    """
    if not isinstance(value, str):
        raise error_cls(f"{name} must be an ISO timestamp")
    normalized = (
        f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise error_cls(f"{name} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise error_cls(f"{name} must include a timezone")
    return parsed
