"""Small password and signed-session layer for private MootOS deployments."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import Response


COOKIE_NAME = "mootos_session"
SESSION_DAYS = 30
TRUE_VALUES = {"1", "true", "yes", "on"}


def _environment_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def running_on_railway() -> bool:
    """Return whether Railway production metadata is present."""
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT", "").strip()
        or os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    )


def public_access_allowed() -> bool:
    """Return whether public startup was explicitly approved."""
    return _environment_flag("MOOTOS_ALLOW_PUBLIC")


def auth_enabled() -> bool:
    """Return whether password protection is configured."""
    return bool(os.getenv("MOOTOS_PASSWORD", "").strip())


def validate_auth_configuration() -> None:
    """Reject incomplete or accidentally public production configuration."""
    password = os.getenv("MOOTOS_PASSWORD", "").strip()
    session_secret = os.getenv("MOOTOS_SESSION_SECRET", "").strip()

    if bool(password) != bool(session_secret):
        raise RuntimeError(
            "MOOTOS_PASSWORD and MOOTOS_SESSION_SECRET must be configured together"
        )

    if running_on_railway() and not password and not public_access_allowed():
        raise RuntimeError(
            "Railway deployments require MOOTOS_PASSWORD and "
            "MOOTOS_SESSION_SECRET. Set MOOTOS_ALLOW_PUBLIC=true only when "
            "public access is intentional."
        )


def password_matches(candidate: str) -> bool:
    """Compare a submitted password without timing-sensitive equality."""
    configured = os.getenv("MOOTOS_PASSWORD", "")
    return bool(configured) and secrets.compare_digest(candidate, configured)


def _session_secret() -> bytes:
    secret = os.getenv("MOOTOS_SESSION_SECRET", "").strip()
    if not secret:
        raise RuntimeError("MOOTOS_SESSION_SECRET is not configured")
    return secret.encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_session_token(now: Optional[int] = None) -> str:
    """Create a short signed payload with a fixed expiration."""
    issued_at = int(time.time() if now is None else now)
    payload = {
        "exp": issued_at + (SESSION_DAYS * 24 * 60 * 60),
        "nonce": secrets.token_urlsafe(12),
        "v": 1,
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _session_secret(), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_session_token(token: Optional[str], now: Optional[int] = None) -> bool:
    """Validate token structure, signature, version, and expiration."""
    if not token or "." not in token:
        return False

    encoded, supplied_signature = token.rsplit(".", 1)
    expected_signature = hmac.new(
        _session_secret(), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not secrets.compare_digest(supplied_signature, expected_signature):
        return False

    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        current_time = int(time.time() if now is None else now)
        return payload.get("v") == 1 and int(payload["exp"]) > current_time
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False


def request_is_authenticated(request: Request) -> bool:
    """Return whether a request carries a valid session cookie."""
    if not auth_enabled():
        return True
    return verify_session_token(request.cookies.get(COOKIE_NAME))


def _secure_cookie_enabled() -> bool:
    explicit = os.getenv("MOOTOS_SECURE_COOKIES", "").strip().lower()
    if explicit:
        return explicit in TRUE_VALUES
    return running_on_railway()


def set_session_cookie(response: Response) -> None:
    """Attach the signed session using browser-safe cookie settings."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(),
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_secure_cookie_enabled(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the login cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=_secure_cookie_enabled(),
        samesite="lax",
        path="/",
    )
