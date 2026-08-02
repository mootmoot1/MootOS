"""Tests for understandable keyword memory retrieval and search."""

import pytest
from fastapi.testclient import TestClient

from backend.main import _build_model_instructions, app
from backend.memory import (
    DATABASE_PATH,
    archive_memory,
    correct_memory,
    create_memory,
    init_db,
    restore_memory,
)
from backend.memory_retrieval import (
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


@pytest.fixture
def client():
    return TestClient(app)


def test_keyword_tokenizer_normalizes_case_punctuation_and_simple_plurals():
    assert tokenize_keywords("What's MY Cars' test codes, codes?") == (
        "car",
        "test",
        "code",
    )


def test_repeated_query_terms_do_not_hide_later_unique_keyword():
    query = ("repeat " * 45) + "needleword"

    assert tokenize_keywords(query) == ("repeat", "needleword")


def test_no_project_retrieval_prioritizes_relevant_memory_across_projects(clean_db):
    relevant = create_memory(
        "I drive a black C300 Benz.",
        project="Cars",
        memory_type="explicit_chat",
    )
    create_memory("My preferred tea is jasmine.", memory_type="explicit_chat")

    results = retrieve_context_memories(None, "What car do I have?")

    assert results[0]["id"] == relevant["id"]


def test_no_project_retrieval_uses_match_strength_not_global_scope(clean_db):
    project_memory = create_memory(
        "My black C300 Benz is the current vehicle.",
        project="Cars",
    )
    global_memory = create_memory("Car paperwork is stored safely.")

    results = retrieve_context_memories(None, "car C300 Benz")

    assert [memory["id"] for memory in results[:2]] == [
        project_memory["id"],
        global_memory["id"],
    ]


def test_keyword_match_scans_complete_long_memory_content(clean_db):
    long_memory = create_memory(
        ("fillerword " * 45) + "needleword appears at the end.",
        project="Personal",
    )

    results = retrieve_context_memories(None, "needleword")

    assert results[0]["id"] == long_memory["id"]


def test_project_retrieval_orders_matching_global_and_other_project_matches(clean_db):
    matching_project = create_memory(
        "The Studio car workflow uses the rear entrance.",
        project="Studio",
    )
    global_memory = create_memory("Car insurance renews in October.")
    other_project = create_memory("I drive a black C300 Benz.", project="Cars")
    create_memory("Post three short videos each week.", project="Social Media")

    results = retrieve_context_memories("Studio", "car")

    assert [memory["id"] for memory in results[:3]] == [
        matching_project["id"],
        global_memory["id"],
        other_project["id"],
    ]


def test_project_fallback_does_not_include_unrelated_other_project_memory(clean_db):
    create_memory("I drive a black C300 Benz.", project="Cars")

    results = retrieve_context_memories("Studio", "weather tomorrow")

    assert results == []


def test_stopword_only_query_preserves_matching_project_and_global_fallback(clean_db):
    matching_project = create_memory("Studio sessions start at noon.", project="Studio")
    global_memory = create_memory("Plain explanations are preferred.")
    create_memory("I drive a black C300 Benz.", project="Cars")

    results = retrieve_context_memories("Studio", "How are you?")

    assert {memory["id"] for memory in results} == {
        matching_project["id"],
        global_memory["id"],
    }


def test_archived_and_superseded_rows_never_enter_keyword_context(clean_db):
    original = create_memory("My test code is blue.")
    replacement = correct_memory(original["id"], "My test code is green.")[
        "replacement"
    ]
    archive_memory(replacement["id"])

    assert retrieve_context_memories(None, "test code") == []

    restore_memory(replacement["id"])
    restored = retrieve_context_memories(None, "test code")

    assert [memory["id"] for memory in restored] == [replacement["id"]]


def test_memory_search_api_filters_active_and_archived_keyword_matches(clean_db, client):
    active = create_memory("Jasmine tea is preferred.", project="Personal")
    archived = create_memory("The jasmine mug is in storage.", project="Personal")
    archive_memory(archived["id"])
    create_memory("The studio microphone is repaired.", project="Studio")

    active_response = client.get(
        "/memories",
        params={"status": "active", "q": "jasmine"},
    )
    archived_response = client.get(
        "/memories",
        params={"status": "archived", "q": "jasmine"},
    )

    assert active_response.status_code == 200
    assert archived_response.status_code == 200
    assert [memory["id"] for memory in active_response.json()["data"]] == [
        active["id"]
    ]
    assert [memory["id"] for memory in archived_response.json()["data"]] == [
        archived["id"]
    ]


def test_memory_search_rejects_oversized_query(clean_db, client):
    response = client.get("/memories", params={"q": "x" * 501})

    assert response.status_code == 422


def test_model_instructions_include_relevant_cross_project_memory_only(clean_db):
    relevant = create_memory("I drive a black C300 Benz.", project="Cars")
    unrelated = create_memory(
        "Post three short videos each week.",
        project="Social Media",
    )

    instructions = _build_model_instructions("Studio", "What car do I have?")

    assert relevant["content"] in instructions
    assert unrelated["content"] not in instructions


def test_memory_search_interface_uses_keyword_query_without_new_mutation_methods(client):
    page = client.get("/memory")
    script = client.get("/static/memory.js")

    assert page.status_code == 200
    assert 'id="memorySearchForm"' in page.text
    assert 'id="memorySearchInput"' in page.text
    assert 'maxlength="500"' in page.text
    assert 'params.set("q", searchQuery)' in script.text
    assert 'method: "DELETE"' not in script.text
    assert 'method: "PATCH"' not in script.text
    assert 'method: "PUT"' not in script.text
