"""Tests for the V0.3D risk-metadata gate (scripts/gates/risk_metadata.py).

Static-source tests construct small synthetic ToolDefinition-shaped
sources so the "no default value" check is exercised directly, without
needing to edit the real backend/tool_types.py. Live-registry tests run
against the actual repository.
"""

from scripts.gates.risk_metadata import (
    check_risk_field_has_no_default,
    check_live_registry_risk_values,
    evaluate,
)


GOOD_SOURCE = '''
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    input_schema: dict
    risk: str
    data_exposure: str
    executor: Callable
'''

WEAKENED_SOURCE = '''
from dataclasses import dataclass
from typing import Callable

RISK_READ_ONLY = "read_only"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    input_schema: dict
    risk: str = RISK_READ_ONLY
    data_exposure: str = "local"
    executor: Callable = None
'''

MISSING_FIELD_SOURCE = '''
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
'''

MISSING_CLASS_SOURCE = '''
def something_else():
    pass
'''


# --- 9. Production ToolDefinitions cannot omit required risk metadata -------


def test_risk_field_with_no_default_passes():
    assert check_risk_field_has_no_default(GOOD_SOURCE) is None


def test_risk_field_given_a_default_value_is_a_violation():
    """This is the exact regression this gate exists to catch: someone
    adds `risk: str = RISK_READ_ONLY`, silently making every tool that
    forgets to pass risk explicitly default to the most permissive level."""
    violation = check_risk_field_has_no_default(WEAKENED_SOURCE)
    assert violation is not None
    assert "default value" in violation
    assert "most permissive" in violation


def test_missing_risk_field_entirely_is_a_violation():
    violation = check_risk_field_has_no_default(MISSING_FIELD_SOURCE)
    assert violation is not None
    assert "no 'risk' field" in violation


def test_missing_tooldefinition_class_entirely_is_a_violation():
    violation = check_risk_field_has_no_default(MISSING_CLASS_SOURCE)
    assert violation is not None
    assert "could not find class" in violation


def test_syntactically_invalid_source_fails_closed():
    violation = check_risk_field_has_no_default("def broken(:\n  not python")
    assert violation is not None
    assert "could not be parsed" in violation


def test_real_backend_tool_types_passes():
    """The gate against this repository's actual, unmodified
    backend/tool_types.py must pass -- proving the static check works
    against real code, not just synthetic fixtures."""
    from pathlib import Path

    repository_root = Path(__file__).resolve().parent.parent
    source = (repository_root / "backend" / "tool_types.py").read_text(encoding="utf-8")
    assert check_risk_field_has_no_default(source) is None


# --- Live registry check ------------------------------------------------------


def test_live_default_registry_has_only_valid_risk_values():
    assert check_live_registry_risk_values() == []


def test_evaluate_against_the_real_repository_passes():
    from pathlib import Path

    result = evaluate(Path(__file__).resolve().parent.parent)
    assert result.passed is True
    assert "PASS" in result.summary()


# --- Adversarial / structural ------------------------------------------------


def test_a_second_unrelated_class_named_similarly_does_not_confuse_the_check():
    source = GOOD_SOURCE + '''

@dataclass
class NotToolDefinitionAtAll:
    risk: str = "whatever"
'''
    # The real ToolDefinition (found first) still has no default -- a
    # same-named field on a different class must not cause a false
    # violation.
    assert check_risk_field_has_no_default(source) is None


def test_weakened_source_produces_a_failing_gate_result_via_evaluate(tmp_path, monkeypatch):
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "tool_types.py").write_text(WEAKENED_SOURCE, encoding="utf-8")

    result = evaluate(tmp_path)

    assert result.passed is False
    assert any("default value" in v for v in result.violations)
    assert "FAIL" in result.summary()
