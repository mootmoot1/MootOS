"""Tests for V0.3C narrow self-inspection (backend/self_inspection.py and
the self.state / self.architecture tools in backend/tools_web.py).

The security property under test throughout: self-inspection reads an
explicit, compile-time allow-list of curated architecture documents and
live registry state -- never an arbitrary path, never secrets, never user
data, never source code.
"""

import json

import pytest

from backend.db import DATABASE_PATH
from backend.memory import init_db
from backend.self_inspection import (
    CURATED_DOCUMENTS,
    DOCUMENT_MAX_CHARACTERS,
    SelfInspectionError,
    describe_runtime_state,
    detect_documentation_drift,
    list_documents,
    read_document,
)
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import (
    RISK_READ_ONLY,
    ToolDefinition,
    ToolExecutionContext,
    ToolValidationError,
)
from backend.tools_web import SELF_ARCHITECTURE, SELF_STATE


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


def _registry_with(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


def _run(tool_name: str, arguments: dict, registry: ToolRegistry) -> dict:
    return execute_tool(
        tool_name=tool_name,
        arguments=arguments,
        context=ToolExecutionContext(),
        registry=registry,
    )


# --- 1. Self-inspection cannot access arbitrary paths ------------------------


@pytest.mark.parametrize(
    "hostile_key",
    [
        ".env",
        "../.env",
        "/etc/passwd",
        "../../etc/passwd",
        "backend/auth.py",
        "backend/self_inspection.py",
        "data/mootos.db",
        ".git/config",
        "ARCHITECTURE.md",  # a real path -- but a path, not an allow-listed key
        "docs/TOOL_SYSTEM.md",
        "",
        "..",
    ],
)
def test_read_document_rejects_every_path_like_input(hostile_key):
    """read_document takes an allow-listed KEY, never a path. Even the real
    repository path of an allow-listed document is rejected, because paths
    are not the interface."""
    with pytest.raises(SelfInspectionError):
        read_document(hostile_key)


@pytest.mark.parametrize(
    "hostile_document",
    ["../.env", "/etc/passwd", "backend/auth.py", ".git/config", "ARCHITECTURE.md"],
)
def test_self_architecture_tool_rejects_path_input_at_schema_validation(clean_db, hostile_document):
    """The tool's enum schema is the real boundary: a path never reaches the
    executor at all -- it fails in backend/tool_validation.py first."""
    registry = _registry_with(SELF_ARCHITECTURE)

    with pytest.raises(ToolValidationError):
        _run("self.architecture", {"document": hostile_document}, registry)


def test_curated_document_paths_all_resolve_inside_the_repository():
    """Every allow-list entry is a real, in-repository file. Guards against a
    future edit introducing a traversal or an absent path."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for key, entry in CURATED_DOCUMENTS.items():
        resolved = (root / entry["path"]).resolve()
        assert resolved.is_relative_to(root), f"{key} escapes the repository"
        assert resolved.is_file(), f"{key} points at a missing file: {entry['path']}"


def test_there_is_no_generic_read_file_capability():
    """V0.3C explicitly must not add read_file(path). Nothing in the
    self-inspection surface accepts a caller-supplied path."""
    import backend.self_inspection as module

    assert not hasattr(module, "read_file")
    assert not hasattr(module, "read_path")
    # read_document's only parameter is the allow-listed key.
    import inspect

    assert list(inspect.signature(module.read_document).parameters) == ["key"]


# --- 2. Self-inspection cannot read secrets or environment data -------------


def test_no_curated_document_is_a_secret_or_data_file():
    paths = {entry["path"] for entry in CURATED_DOCUMENTS.values()}
    for path in paths:
        assert not path.startswith("data/")
        assert ".env" not in path
        assert not path.startswith(".git")
        assert path.endswith(".md"), "only markdown architecture docs are curated"
        assert not path.startswith("backend/"), "no source files are exposed"
        assert not path.startswith("frontend/")


def test_runtime_state_contains_no_environment_values_or_secrets(clean_db, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "SECRET-OPENAI-KEY-VALUE")
    monkeypatch.setenv("MOOTOS_PASSWORD", "SECRET-PASSWORD-VALUE")
    monkeypatch.setenv("MOOTOS_SESSION_SECRET", "SECRET-SESSION-VALUE")

    serialized = json.dumps(describe_runtime_state(get_tool_registry()))

    assert "SECRET-OPENAI-KEY-VALUE" not in serialized
    assert "SECRET-PASSWORD-VALUE" not in serialized
    assert "SECRET-SESSION-VALUE" not in serialized


def test_runtime_state_exposes_only_expected_metadata_keys(clean_db):
    state = describe_runtime_state(get_tool_registry())

    assert set(state) == {
        "schema_version",
        "installed_tool_count",
        "tools",
        "capabilities",
        "available_documents",
        "documentation_notes",
        "authority_note",
    }
    # Each tool entry is capability metadata only -- the same closed key set
    # V0.3A's catalog already guarantees, with no room for arguments,
    # prompt/response text, or user data. (Leakage of actual secret *values*
    # is covered by the value-based test above; scanning this prose for
    # words like "secret" would false-positive on tool limitations text that
    # correctly says it cannot read secrets.)
    for entry in state["tools"]:
        assert set(entry) == {
            "name",
            "version",
            "description",
            "input_schema",
            "risk",
            "capabilities",
            "side_effects",
            "idempotent",
            "limitations",
            "depends_on",
        }


# --- 3. Allow-listed architecture docs can actually be inspected ------------


@pytest.mark.parametrize("key", sorted(CURATED_DOCUMENTS))
def test_every_allow_listed_document_is_readable(key):
    result = read_document(key)

    assert result["key"] == key
    assert result["title"]
    assert len(result["content"]) > 0
    assert "curated architecture document" in result["content"]


def test_document_content_is_bounded_and_truncation_is_explicit():
    # ARCHITECTURE.md is well over the cap, so it must be truncated visibly.
    result = read_document("architecture")

    assert result["truncated"] is True
    assert "[TRUNCATED by MootOS self-inspection" in result["content"]
    assert len(result["content"]) < DOCUMENT_MAX_CHARACTERS + 1_000


def test_self_architecture_tool_reads_an_allow_listed_document(clean_db):
    registry = _registry_with(SELF_ARCHITECTURE)

    result = _run("self.architecture", {"document": "gap_reasoning"}, registry)

    assert result.success is True
    assert result.data["key"] == "gap_reasoning"
    assert "Gap Reasoning" in result.data["content"]


def test_list_documents_returns_keys_and_titles_but_never_paths():
    documents = list_documents()

    assert {entry["key"] for entry in documents} == set(CURATED_DOCUMENTS)
    for entry in documents:
        assert set(entry) == {"key", "title"}
        assert ".md" not in entry["title"], "titles must not leak repository paths"


# --- 4. Runtime Tool Registry remains authoritative -------------------------


def test_runtime_state_reports_the_live_registry_not_documentation(clean_db):
    """A tiny custom registry must be reported exactly -- documentation
    naming other tools cannot add them."""
    tiny = _registry_with(SELF_STATE)

    state = describe_runtime_state(tiny)

    assert state["installed_tool_count"] == 1
    assert [entry["name"] for entry in state["tools"]] == ["self.state"]


def test_documentation_drift_is_surfaced_not_silently_resolved(clean_db):
    """docs/TOOL_SYSTEM.md documents the four V0.2A tools. Against a registry
    that lacks them, self-inspection must SAY SO rather than either trusting
    the documentation or hiding the mismatch."""
    tiny = _registry_with(SELF_STATE)

    notes = detect_documentation_drift(tiny)

    assert len(notes) == 4
    joined = " ".join(notes)
    for missing in ("projects.list", "memory.search", "tasks.list", "tasks.create"):
        assert missing in joined
    assert "NOT in the live Tool Registry" in joined
    assert "registry is authoritative" in joined

    state = describe_runtime_state(tiny)
    assert state["documentation_notes"] == notes


def test_no_drift_reported_when_registry_matches_documentation(clean_db):
    assert detect_documentation_drift(get_tool_registry()) == []


def test_runtime_state_states_registry_authority_explicitly(clean_db):
    state = describe_runtime_state(get_tool_registry())

    note = state["authority_note"].lower()
    assert "authoritative" in note
    assert "documents" in note


def test_documentation_can_never_add_a_tool_to_the_registry(clean_db):
    """Reading every curated document must not change installed state."""
    registry = _registry_with(SELF_STATE, SELF_ARCHITECTURE)
    before = {d.name for d in registry.list_definitions()}

    for key in sorted(CURATED_DOCUMENTS):
        read_document(key)

    assert {d.name for d in registry.list_definitions()} == before
    assert len(registry) == 2


# --- Self-inspection tools are read-only and registry-controlled ------------


def test_self_inspection_tools_are_read_only():
    for definition in (SELF_STATE, SELF_ARCHITECTURE):
        assert definition.risk == RISK_READ_ONLY
        assert definition.idempotent is True
        assert "none" in definition.side_effects.lower()


def test_self_state_takes_no_arguments(clean_db):
    registry = _registry_with(SELF_STATE)

    with pytest.raises(ToolValidationError):
        _run("self.state", {"anything": "at all"}, registry)

    assert _run("self.state", {}, registry).success is True


def test_self_architecture_requires_the_document_argument(clean_db):
    registry = _registry_with(SELF_ARCHITECTURE)

    with pytest.raises(ToolValidationError):
        _run("self.architecture", {}, registry)


def test_unknown_document_key_fails_with_a_sanitized_tool_error(clean_db):
    """A key that passes schema validation cannot exist (the enum is the
    allow-list), so this exercises the executor's own defense directly."""
    from backend.self_inspection import read_document as direct_read

    with pytest.raises(SelfInspectionError) as captured:
        direct_read("definitely_not_a_document")

    message = str(captured.value)
    assert "Available documents" in message
    # Never leaks a filesystem path.
    assert "/" not in message.replace("Available documents: ", "")


def test_self_inspection_error_never_leaks_a_filesystem_path(monkeypatch):
    """Even an OS-level read failure must not surface the absolute path."""
    from pathlib import Path

    def explode(self, **kwargs):
        raise OSError("/absolute/secret/path/ARCHITECTURE.md: permission denied")

    monkeypatch.setattr(Path, "read_text", explode)

    with pytest.raises(SelfInspectionError) as captured:
        read_document("architecture")

    assert "/absolute/secret/path" not in str(captured.value)
    assert str(captured.value) == "Document could not be read."


def test_self_inspection_tools_declare_v03a_metadata_explicitly():
    for definition in (SELF_STATE, SELF_ARCHITECTURE):
        assert definition.capabilities == ("self.inspect",)
        assert definition.side_effects.strip()
        assert definition.idempotent is not None
        assert definition.limitations.strip()


def test_self_architecture_limitations_state_what_it_cannot_read():
    limitations = SELF_ARCHITECTURE.limitations.lower()
    for claim in ("source code", ".env", "secrets", "database", "git history"):
        assert claim in limitations
