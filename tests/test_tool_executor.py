"""Tests for the centralized Tool System executor: Run-logging, permissions,
and sanitized errors."""

import pytest

from backend.db import DATABASE_PATH, database_connection
from backend.memory import init_db
from backend.runs import RUN_TYPE_TOOL, list_runs
from backend.tool_executor import execute_tool
from backend.tool_registry import ToolRegistry
from backend.tool_types import (
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolValidationError,
)


READ_ONLY_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string", "minLength": 1}},
    "required": ["value"],
    "additionalProperties": False,
}


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


def _read_only(name="read.echo", executor=None):
    return ToolDefinition(
        name=name,
        version="1",
        description="Echo tool.",
        input_schema=READ_ONLY_SCHEMA,
        risk="read_only",
        data_exposure="local",
        executor=executor or (lambda arguments, context: {"echo": arguments["value"]}),
    )


def _internal_write(name="write.thing", executor=None):
    return ToolDefinition(
        name=name,
        version="2",
        description="Write tool.",
        input_schema=READ_ONLY_SCHEMA,
        risk="internal_write",
        data_exposure="local",
        executor=executor or (lambda arguments, context: {"created": True}),
    )


def _high_risk(name="danger.thing"):
    return ToolDefinition(
        name=name,
        version="1",
        description="High-risk tool.",
        input_schema=READ_ONLY_SCHEMA,
        risk="high_risk",
        data_exposure="tool_external",
        executor=lambda arguments, context: {"never": "runs"},
    )


def test_read_only_tool_executes_and_records_successful_run(clean_db):
    registry = _registry_with(_read_only())
    result = execute_tool(
        tool_name="read.echo",
        arguments={"value": "hi"},
        context=ToolExecutionContext(),
        registry=registry,
    )

    assert result.success is True
    assert result.data == {"echo": "hi"}
    assert result.run_id is not None

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["run_type"] == RUN_TYPE_TOOL
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["tool_name"] == "read.echo"
    assert runs[0]["tool_version"] == "1"
    assert runs[0]["data_exposure"] == "local"


def test_internal_write_tool_does_not_execute_without_approval(clean_db):
    registry = _registry_with(_internal_write())

    with pytest.raises(ToolPermissionError):
        execute_tool(
            tool_name="write.thing",
            arguments={"value": "hi"},
            context=ToolExecutionContext(approved=False),
            registry=registry,
        )

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_class"] == "ToolPermissionError"


def test_internal_write_tool_executes_once_approved(clean_db):
    registry = _registry_with(_internal_write())

    result = execute_tool(
        tool_name="write.thing",
        arguments={"value": "hi"},
        context=ToolExecutionContext(approved=True),
        registry=registry,
    )

    assert result.success is True
    assert list_runs()[0]["status"] == "succeeded"


def test_high_risk_tool_never_executes_even_when_approved(clean_db):
    registry = _registry_with(_high_risk())

    with pytest.raises(ToolPermissionError):
        execute_tool(
            tool_name="danger.thing",
            arguments={"value": "hi"},
            context=ToolExecutionContext(approved=True),
            registry=registry,
        )

    assert list_runs()[0]["status"] == "failed"


def test_unknown_tool_fails_closed_and_still_logs_a_run(clean_db):
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError):
        execute_tool(
            tool_name="does.not.exist",
            arguments={},
            context=ToolExecutionContext(),
            registry=registry,
        )

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["tool_name"] == "does.not.exist"
    assert runs[0]["tool_version"] is None
    assert runs[0]["status"] == "failed"
    assert runs[0]["error_class"] == "ToolNotFoundError"


def test_invalid_arguments_are_rejected_before_executor_runs(clean_db):
    calls = []

    def executor(arguments, context):
        calls.append(arguments)
        return {}

    registry = _registry_with(_read_only(executor=executor))

    with pytest.raises(ToolValidationError):
        execute_tool(
            tool_name="read.echo",
            arguments={},
            context=ToolExecutionContext(),
            registry=registry,
        )

    assert calls == []
    assert list_runs()[0]["status"] == "failed"
    assert list_runs()[0]["error_class"] == "ToolValidationError"


def test_unexpected_executor_failure_is_sanitized_and_logged(clean_db):
    def broken_executor(arguments, context):
        raise RuntimeError("connection string: postgres://user:secret@host/db")

    registry = _registry_with(_read_only(executor=broken_executor))

    with pytest.raises(ToolExecutionError) as excinfo:
        execute_tool(
            tool_name="read.echo",
            arguments={"value": "hi"},
            context=ToolExecutionContext(),
            registry=registry,
        )

    assert "secret" not in str(excinfo.value)
    assert "postgres" not in str(excinfo.value)

    run = list_runs()[0]
    assert run["status"] == "failed"
    assert run["error_class"] == "RuntimeError"
    with database_connection() as connection:
        row = connection.execute("SELECT * FROM runs").fetchone()
    for value in dict(row).values():
        if value is not None:
            assert "secret" not in str(value)
            assert "postgres" not in str(value)


def test_domain_execution_error_message_reaches_caller_but_stays_out_of_run(clean_db):
    def executor(arguments, context):
        raise ToolExecutionError("Project does not exist")

    registry = _registry_with(_read_only(executor=executor))

    with pytest.raises(ToolExecutionError, match="Project does not exist"):
        execute_tool(
            tool_name="read.echo",
            arguments={"value": "hi"},
            context=ToolExecutionContext(),
            registry=registry,
        )

    run = list_runs()[0]
    assert run["error_class"] == "ToolExecutionError"
    with database_connection() as connection:
        row = connection.execute("SELECT * FROM runs").fetchone()
    assert "Project does not exist" not in str(dict(row))
