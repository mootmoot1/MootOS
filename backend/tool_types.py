"""Normalized contract types for the MootOS Tool System.

This module is intentionally a leaf: it has no dependency on the model
provider, the tool registry, or the executor. Every other tool-system module
imports from here so a single, small, dependency-free file defines what a
tool *is* before anything decides how tools are registered, validated,
authorized, executed, or exposed to a model provider.

Provider-native tool-call objects (OpenAI Responses API items, a future
Ollama/local format, etc.) must never appear here or anywhere outside
``backend/model_router.py``. Everything below is plain, JSON-serializable
data.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from backend.runs import VALID_DATA_EXPOSURES


# --- Risk / permission taxonomy -------------------------------------------
#
# Risk is a property of the *registered tool definition*, never of a model's
# request. A model can ask for anything; it can never choose how risky that
# request is treated. See backend/tool_executor.py for enforcement.

RISK_READ_ONLY = "read_only"
RISK_INTERNAL_WRITE = "internal_write"
RISK_HIGH_RISK = "high_risk"
VALID_RISK_LEVELS = {RISK_READ_ONLY, RISK_INTERNAL_WRITE, RISK_HIGH_RISK}

# Data-exposure classification is reused directly from the existing Run
# architecture (backend/runs.py: DATA_EXPOSURE_LOCAL etc.) rather than
# re-defined here, so a tool and its Run always describe exposure the same
# way. Import those constants from backend.runs, not from this module.


# --- Exceptions -------------------------------------------------------------


class ToolNotFoundError(LookupError):
    """Raised when a requested tool name is not registered. Fails closed."""


class DuplicateToolError(ValueError):
    """Raised when a tool name is registered a second time."""


class ToolValidationError(ValueError):
    """Raised when tool arguments do not match the registered input schema."""


class ToolPermissionError(PermissionError):
    """Raised when a tool's risk classification blocks this execution path."""


class ToolExecutionError(RuntimeError):
    """Raised when a tool's executor callable fails.

    The message on this exception is shown to the model/user, so tool code
    should only put safe, non-sensitive domain text here (e.g. "Project does
    not exist"). Unexpected internal failures are wrapped by the executor
    with a fully generic message instead of leaking their own text.
    """

    def __init__(self, message: str = "Tool execution failed") -> None:
        super().__init__(message)


class ToolBudgetExceededError(RuntimeError):
    """Raised internally when a conversation turn exceeds its tool-call budget."""


# --- Core contract types ----------------------------------------------------


@dataclass(frozen=True)
class ToolExecutionContext:
    """Everything a tool executor callable is allowed to know about the caller.

    ``approved`` is only ever set to True by the approval-operation path
    (backend/tool_operations.py) after a human has approved a frozen
    operation. A model can never set it directly.
    """

    conversation_id: Optional[str] = None
    project: Optional[str] = None
    approved: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    """One normalized, registered MootOS tool.

    ``executor`` is a plain Python callable -- ``(arguments, context) ->
    dict`` -- selected explicitly at registration time. It is never resolved
    from a model-supplied string, and it never sees provider-native types.
    """

    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    risk: str
    data_exposure: str
    executor: Callable[[dict[str, Any], ToolExecutionContext], dict[str, Any]]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Tool name cannot be empty")
        if self.risk not in VALID_RISK_LEVELS:
            raise ValueError(f"Unsupported tool risk classification: {self.risk!r}")
        if self.data_exposure not in VALID_DATA_EXPOSURES:
            raise ValueError(
                f"Unsupported tool data-exposure classification: {self.data_exposure!r}"
            )

    def to_catalog_entry(self) -> dict[str, Any]:
        """Return the safe, JSON-serializable subset exposed to a model/API.

        Never includes ``executor`` -- the catalog is read-only description,
        not a way to reach the callable.
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk": self.risk,
        }


@dataclass(frozen=True)
class ToolRequest:
    """One normalized tool-call request produced by a model turn."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass(frozen=True)
class ToolResult:
    """One normalized outcome of attempting to run a tool.

    ``data`` must be JSON-serializable; it is fed back to the model as
    explicitly labeled tool output, never as a fabricated user message.
    """

    success: bool
    tool_name: str
    data: Any
    summary: str
    run_id: Optional[str] = None
    call_id: Optional[str] = None
