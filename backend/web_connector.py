"""V0.3C — MootOS's first concrete external connector: read-only web search.

This is the **connector** half of V0.3C Part B (see
``docs/CAPABILITY_ARCHITECTURE.md`` Sec3's Resource/Connector/Tool/Capability
model). It owns exactly one thing: reaching one external search service
safely and turning its provider-specific JSON into a small normalized
shape. It owns no schema, no risk classification, and no model-facing
description -- those belong to the registered tool
(``backend/tools_web.py``).

**Deliberately not a Connector Framework.** There is no base class, no
plugin registry, no provider abstraction layer. This is one concrete
connector for one concrete capability, exactly as
``docs/CAPABILITY_ARCHITECTURE.md`` Sec9 requires ("build connectors one
at a time, concretely... generalize only once 2-3 concrete connectors
exist"). Swapping search providers means editing this file.

**Read-only by construction.** The only HTTP verb used is GET, the URL is
a module constant, and no request body is ever sent. There is no code path
here that posts, comments, submits a form, authenticates as a user, or
performs any other external write.

**Fails closed when unconfigured.** Without ``MOOTOS_SEARCH_API_KEY``,
``is_configured()`` returns False and the web tool is never registered
(``backend/tools_web.py``) -- so MootOS never claims a search capability it
cannot actually perform.
"""

import os
from typing import Any, Optional

import httpx


# --- Provider (Brave Search API) --------------------------------------------
#
# One concrete provider. Its request shape (X-Subscription-Token header,
# q/count query parameters) and response shape (web.results[] with
# title/url/description) are known only inside this module -- callers see
# only the normalized dicts returned by ``search``.

SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
SEARCH_API_KEY_VARIABLE = "MOOTOS_SEARCH_API_KEY"

# Bounds. Every one of these is enforced here, in the connector, so no
# caller can raise them by passing different arguments.
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 512_000
MAX_RESULTS = 5
MAX_QUERY_CHARACTERS = 300
MAX_TITLE_CHARACTERS = 300
MAX_SNIPPET_CHARACTERS = 1_000
MAX_URL_CHARACTERS = 500


class WebSearchError(RuntimeError):
    """Raised when a web search cannot be completed.

    Always carries safe, generic text. Provider error bodies, API keys,
    request URLs, and raw exception messages are never included -- the
    underlying exception is chained for local debugging only, and the Tool
    System persists only its class name (``docs/TOOL_SYSTEM.md`` Sec7).
    """


class WebSearchNotConfiguredError(WebSearchError):
    """Raised when no search API key is configured in this environment."""


def is_configured() -> bool:
    """Whether a usable search API key is present in this environment.

    ``backend/tools_web.py`` calls this at registration time: an
    unconfigured MootOS simply does not register ``web.search``, so the
    V0.3A catalog and the V0.3B capability index both honestly report the
    capability as absent instead of advertising something that would fail.
    """
    key = os.getenv(SEARCH_API_KEY_VARIABLE, "").strip()
    return bool(key) and key != "your_search_api_key_here"


def _require_api_key() -> str:
    key = os.getenv(SEARCH_API_KEY_VARIABLE, "").strip()
    if not key or key == "your_search_api_key_here":
        raise WebSearchNotConfiguredError(
            "Web search is not configured in this MootOS deployment."
        )
    return key


def _clip(value: Any, limit: int) -> str:
    """Coerce a provider-supplied value to a bounded, single-line string.

    Control characters are stripped rather than escaped: they carry no
    meaning in a search result and are a cheap way for hostile content to
    fake structure (fabricated "system:" lines, ANSI sequences) once the
    text reaches a model or a terminal.
    """
    text = value if isinstance(value, str) else ""
    cleaned = "".join(character for character in text if character.isprintable())
    cleaned = cleaned.strip()
    return cleaned[:limit]


def _normalize_results(payload: Any) -> list[dict[str, str]]:
    """Turn one provider response into MootOS's small normalized shape.

    This is the only function that knows the provider's JSON layout. A
    response that does not match it yields an empty result list rather than
    an exception -- an unexpected shape is "no usable results", not a
    MootOS crash.
    """
    if not isinstance(payload, dict):
        return []
    web_section = payload.get("web")
    if not isinstance(web_section, dict):
        return []
    raw_results = web_section.get("results")
    if not isinstance(raw_results, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw_results[:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        url = _clip(item.get("url"), MAX_URL_CHARACTERS)
        # Only ordinary web URLs are ever passed on. This drops
        # javascript:, data:, and file: URLs that hostile results could
        # otherwise surface to a user as clickable links.
        if not url.startswith(("http://", "https://")):
            continue
        normalized.append(
            {
                "title": _clip(item.get("title"), MAX_TITLE_CHARACTERS),
                "url": url,
                "snippet": _clip(item.get("description"), MAX_SNIPPET_CHARACTERS),
            }
        )
    return normalized


def search(query: str, *, limit: Optional[int] = None) -> list[dict[str, str]]:
    """Run one bounded, read-only web search and return normalized results.

    Raises ``WebSearchNotConfiguredError`` when no API key is present, and
    ``WebSearchError`` for every transport, timeout, HTTP-status,
    oversized-response, or malformed-JSON failure -- all with generic,
    sanitized messages.

    The returned list contains only ``{title, url, snippet}`` dicts with
    every field length-bounded and control characters stripped. It is
    untrusted external data; see ``backend/tools_web.py`` for how it is
    labeled before it reaches a model.
    """
    api_key = _require_api_key()

    normalized_query = (query or "").strip()[:MAX_QUERY_CHARACTERS]
    if not normalized_query:
        raise WebSearchError("A non-empty search query is required.")

    requested = MAX_RESULTS if limit is None else max(1, min(int(limit), MAX_RESULTS))

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
            with client.stream(
                "GET",
                SEARCH_ENDPOINT,
                params={"q": normalized_query, "count": requested},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
            ) as response:
                if response.status_code != 200:
                    # Deliberately does not include the provider's status
                    # code or body: both can echo the query or key back.
                    raise WebSearchError("The web search service could not be reached.")

                # Bound the body while reading rather than after: an
                # unbounded/hostile response must never be fully buffered
                # into memory first.
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise WebSearchError("The web search response was too large.")
                    chunks.append(chunk)
                body = b"".join(chunks)
    except WebSearchError:
        raise
    except httpx.TimeoutException as error:
        raise WebSearchError("The web search timed out.") from error
    except Exception as error:  # deliberately broad: sanitized boundary
        raise WebSearchError("The web search could not be completed.") from error

    try:
        import json

        payload = json.loads(body)
    except (TypeError, ValueError) as error:
        raise WebSearchError("The web search service returned an unreadable response.") from error

    return _normalize_results(payload)[:requested]
