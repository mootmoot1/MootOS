"""Deterministic, host-independent POSIX path canonicalization.

Blueprint-declared paths are compared for scope conflicts and validated
for repository-escape safety. Canonicalization never depends on the host
operating system (macOS/Windows/Linux): it always applies pure POSIX
segment semantics, regardless of what platform this process happens to
run on, so the same blueprint canonicalizes identically everywhere.
"""

import re

from .text_safety import utf8_length

MAX_PATH_BYTES = 4096
_UNSAFE_CHARACTER = re.compile(r"[\x00-\x1f\\]")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class PathCanonicalizationError(ValueError):
    """Raised when a declared path cannot be safely canonicalized."""


def canonicalize_repo_path(value):
    """Canonicalize one repository-relative path using pure POSIX rules.

    Rejects a leading ``~`` (home-directory expansion), a drive prefix
    (``C:``), any absolute path (leading ``/``), backslashes (never
    treated as a separator here -- that ambiguity is exactly what this
    function exists to remove), and any ``..`` that would climb above
    the repository root. Repeated slashes and ``.`` segments are
    normalized away so textually different but equivalent paths compare
    equal.
    """
    if not isinstance(value, str) or not value:
        raise PathCanonicalizationError("path must be nonblank text")
    if utf8_length(value) > MAX_PATH_BYTES:
        raise PathCanonicalizationError("path exceeds byte bound")
    if _UNSAFE_CHARACTER.search(value):
        raise PathCanonicalizationError("path contains an unsafe character")
    if value.startswith("~"):
        raise PathCanonicalizationError(
            "path must not reference a home directory"
        )
    if _DRIVE_PREFIX.match(value):
        raise PathCanonicalizationError("path must not use a drive prefix")
    if value.startswith("/"):
        raise PathCanonicalizationError("path must be repository-relative")
    segments = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not segments:
                raise PathCanonicalizationError(
                    "path escapes the repository root"
                )
            segments.pop()
            continue
        segments.append(segment)
    if not segments:
        raise PathCanonicalizationError("path must reference a location")
    return "/".join(segments)
