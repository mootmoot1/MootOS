"""Understandable keyword retrieval for active MootOS memories."""

import re
from typing import Any, Iterable, Optional, Sequence

from backend.memory import (
    MEMORY_STATUS_ACTIVE,
    get_project,
    list_memories,
)


MAX_CONTEXT_MEMORIES = 20
MAX_QUERY_TOKENS = 40
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "ours",
        "s",
        "she",
        "should",
        "t",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
    }
)


def _normalize_token(token: str) -> str:
    """Apply intentionally small normalization without pretending to understand synonyms."""
    normalized = token.casefold()
    if len(normalized) > 4 and normalized.endswith("ies"):
        return normalized[:-3] + "y"
    if (
        len(normalized) > 3
        and normalized.endswith("s")
        and not normalized.endswith(("ss", "us", "is"))
    ):
        return normalized[:-1]
    return normalized


def _keyword_sequence(text: Optional[str]) -> tuple[str, ...]:
    if not text:
        return ()

    keywords: list[str] = []
    for raw_token in _TOKEN_PATTERN.findall(text.casefold()):
        token = _normalize_token(raw_token)
        if not token or token in _STOP_WORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        keywords.append(token)
    return tuple(keywords)


def tokenize_keywords(text: Optional[str]) -> tuple[str, ...]:
    """Return at most 40 unique normalized keywords in their original order."""
    seen: set[str] = set()
    unique: list[str] = []
    for token in _keyword_sequence(text):
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
        if len(unique) >= MAX_QUERY_TOKENS:
            break
    return tuple(unique)


def _contains_sequence(candidate: Sequence[str], query: Sequence[str]) -> bool:
    if not query or len(query) > len(candidate):
        return False
    query_length = len(query)
    return any(
        tuple(candidate[index : index + query_length]) == tuple(query)
        for index in range(len(candidate) - query_length + 1)
    )


def _scope_rank(memory: dict[str, Any], project: Optional[str]) -> int:
    memory_project = memory.get("project")
    if project is None:
        return 0
    if memory_project and memory_project.casefold() == project.casefold():
        return 2
    if memory_project is None:
        return 1
    return 0


def _match_score(
    memory: dict[str, Any],
    query_tokens: Sequence[str],
) -> Optional[int]:
    if not query_tokens:
        return None

    query_set = set(query_tokens)
    content_sequence = _keyword_sequence(memory.get("content"))
    content_tokens = set(content_sequence)
    project_tokens = set(_keyword_sequence(memory.get("project")))
    type_tokens = set(_keyword_sequence(memory.get("memory_type")))

    content_matches = query_set & content_tokens
    project_matches = query_set & project_tokens
    type_matches = query_set & type_tokens
    if not (content_matches or project_matches or type_matches):
        return None

    phrase_bonus = 20 if _contains_sequence(content_sequence, query_tokens) else 0
    return (
        phrase_bonus
        + (len(content_matches) * 5)
        + (len(project_matches) * 3)
        + len(type_matches)
    )


def _recency_value(memory: dict[str, Any]) -> str:
    return str(memory.get("updated_at") or memory.get("created_at") or "")


def _rank_matches(
    memories: Iterable[dict[str, Any]],
    query_tokens: Sequence[str],
    project: Optional[str],
) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, str, str, dict[str, Any]]] = []
    for memory in memories:
        score = _match_score(memory, query_tokens)
        if score is None:
            continue
        scored.append(
            (
                _scope_rank(memory, project),
                score,
                _recency_value(memory),
                str(memory.get("id") or ""),
                memory,
            )
        )

    scored.sort(key=lambda item: item[:4], reverse=True)
    return [item[4] for item in scored]


def _fallback_is_allowed(memory: dict[str, Any], project: Optional[str]) -> bool:
    if project is None:
        return True
    memory_project = memory.get("project")
    return memory_project is None or (
        isinstance(memory_project, str)
        and memory_project.casefold() == project.casefold()
    )


def _rank_fallback(
    memories: Iterable[dict[str, Any]],
    project: Optional[str],
) -> list[dict[str, Any]]:
    fallback = [
        memory
        for memory in memories
        if _fallback_is_allowed(memory, project)
    ]
    fallback.sort(
        key=lambda memory: (
            _scope_rank(memory, project),
            _recency_value(memory),
            str(memory.get("id") or ""),
        ),
        reverse=True,
    )
    return fallback


def rank_memories(
    memories: Sequence[dict[str, Any]],
    query: Optional[str],
    project: Optional[str] = None,
    *,
    include_fallback: bool,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Rank keyword matches and optionally append safe recent fallback memories."""
    query_tokens = tokenize_keywords(query)
    matches = _rank_matches(memories, query_tokens, project)

    ranked = list(matches)
    if include_fallback:
        matched_ids = {memory["id"] for memory in matches}
        ranked.extend(
            memory
            for memory in _rank_fallback(memories, project)
            if memory["id"] not in matched_ids
        )
    elif not query_tokens:
        ranked = list(memories)

    if limit is None:
        return ranked
    if limit < 1:
        return []
    return ranked[:limit]


def retrieve_context_memories(
    project: Optional[str],
    query: Optional[str],
    limit: int = MAX_CONTEXT_MEMORIES,
) -> list[dict[str, Any]]:
    """Return active context ranked by query while treating projects as focus lenses."""
    canonical_project = None
    if project is not None:
        saved_project = get_project(project)
        if saved_project is None:
            raise ValueError("Project does not exist")
        canonical_project = saved_project["name"]

    active_memories = list_memories(memory_status=MEMORY_STATUS_ACTIVE)
    return rank_memories(
        active_memories,
        query,
        canonical_project,
        include_fallback=True,
        limit=limit,
    )


def search_memories(
    query: Optional[str],
    project: Optional[str] = None,
    memory_status: str = MEMORY_STATUS_ACTIVE,
) -> list[dict[str, Any]]:
    """Search one normal memory listing without exposing superseded rows."""
    memories = list_memories(project=project, memory_status=memory_status)
    return rank_memories(
        memories,
        query,
        project,
        include_fallback=False,
    )
