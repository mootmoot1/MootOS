"""Tests for deterministic concept-aware memory retrieval."""

import pytest

from backend.memory import (
    DATABASE_PATH,
    archive_memory,
    correct_memory,
    create_memory,
    init_db,
)
from backend.memory_retrieval import (
    expand_query_concepts,
    retrieve_context_memories,
    tokenize_keywords,
)


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def test_concept_expansion_keeps_literal_terms_first():
    literal = tokenize_keywords("recording software")
    expanded = expand_query_concepts(literal)

    assert expanded[:2] == ("recording", "software")
    assert "daw" in expanded
    assert "tracking" in expanded
    assert len(expanded) == len(set(expanded))


def test_overlapping_concept_groups_union_aliases_instead_of_overwriting():
    recording = set(expand_query_concepts(("recording",)))
    tracking = set(expand_query_concepts(("tracking",)))

    assert {"daw", "protools", "software", "studio", "session"} <= recording
    assert {"daw", "protools", "software", "studio", "session"} <= tracking


def test_recording_software_query_recalls_daw_memory(clean_db):
    daw_memory = create_memory(
        "My main DAW is Pro Tools Ultimate.",
        project="Studio",
        memory_type="bootstrap_profile",
    )
    create_memory(
        "My favorite car platform is the Mercedes W204.",
        project="Cars",
        memory_type="bootstrap_profile",
    )

    results = retrieve_context_memories(
        "Studio",
        "What recording software do I use professionally?",
    )

    assert results[0]["id"] == daw_memory["id"]


def test_recording_alone_recalls_daw_memory_after_overlap_union(clean_db):
    daw_memory = create_memory(
        "My main DAW is Pro Tools Ultimate.",
        project="Studio",
        memory_type="bootstrap_profile",
    )

    results = retrieve_context_memories("Studio", "recording")

    assert results[0]["id"] == daw_memory["id"]


def test_vehicle_query_recalls_car_memory_without_literal_vehicle_word(clean_db):
    car_memory = create_memory(
        "I own and work on a 2008 Mercedes-Benz C300 W204 project car.",
        project="Cars",
    )

    results = retrieve_context_memories(None, "What vehicle do I work on?")

    assert results[0]["id"] == car_memory["id"]


def test_literal_match_outranks_alias_only_match(clean_db):
    literal = create_memory(
        "My recording software is Pro Tools Ultimate.",
        project="Studio",
    )
    alias_only = create_memory(
        "My main DAW is Pro Tools Ultimate.",
        project="Studio",
    )

    results = retrieve_context_memories("Studio", "recording software")

    assert results[0]["id"] == literal["id"]
    assert alias_only["id"] in {memory["id"] for memory in results}


def test_semantic_match_can_cross_project_but_project_fallback_stays_scoped(clean_db):
    car_memory = create_memory(
        "I own a Mercedes project car.",
        project="Cars",
    )
    create_memory(
        "Studio sessions use the rear entrance.",
        project="Studio",
    )
    unrelated = create_memory(
        "Post short videos every week.",
        project="Social Media",
    )

    results = retrieve_context_memories("Studio", "Which vehicle do I own?")
    ids = [memory["id"] for memory in results]

    assert car_memory["id"] in ids
    assert unrelated["id"] not in ids


def test_archived_and_superseded_semantic_matches_never_enter_context(clean_db):
    original = create_memory("My main DAW is OldDAW.", project="Studio")
    replacement = correct_memory(
        original["id"],
        "My main DAW is Pro Tools Ultimate.",
    )["replacement"]
    archive_memory(replacement["id"])

    results = retrieve_context_memories("Studio", "recording software")

    assert original["id"] not in {memory["id"] for memory in results}
    assert replacement["id"] not in {memory["id"] for memory in results}


def test_unrelated_query_does_not_pull_other_project_aliases_as_fallback(clean_db):
    create_memory("I own a Mercedes project car.", project="Cars")

    results = retrieve_context_memories("Studio", "weather tomorrow")

    assert results == []
