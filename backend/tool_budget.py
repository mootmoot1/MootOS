"""Centralized tool-call budget / loop protection for one chat turn.

A single call to ``ToolCallBudget()`` is created fresh per user chat turn by
``backend.tool_conversation``. It is the *only* place that decides whether
another tool execution is allowed this turn -- no other module hardcodes a
call-count limit.

Precise semantics (do not confuse these two numbers):

- ``total_calls`` counts every tool-*request* the loop has finished
  processing this turn, regardless of outcome: a real execution (success or
  failure), an unknown-tool rejection, a schema-validation rejection, *and*
  a request denied outright by this budget (duplicate-call cap or the hard
  cap already reached). ``MAX_TOOL_CALLS_PER_TURN`` bounds this number, and
  because it counts every processed request -- not only executions -- it is
  what actually guarantees the model <-> tool loop terminates. If a denied
  request were left uncounted, a model that kept re-requesting an
  already-capped duplicate call could bounce the loop through an unbounded
  number of rounds without ever being stopped by ``allow_next()``.
- ``executions`` counts only requests that actually reached a tool's
  executor callable and ran (``OUTCOME_SUCCESS``). This is the number the
  product guarantee "maximum 5 tool executions per user turn" refers to. It
  is always ``<= total_calls``, and is the number to check in tests/logs
  when the question is "how many tools actually ran," not "how many
  requests were processed."
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


MAX_TOOL_CALLS_PER_TURN = 5
MAX_IDENTICAL_CALLS_PER_TURN = 2
MAX_CONSECUTIVE_FAILURES = 2

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_UNKNOWN_TOOL = "unknown_tool"
OUTCOME_SKIPPED = "skipped"


def _call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    """A stable fingerprint for one (tool, arguments) pair, order-independent."""
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(f"{tool_name}:{canonical}".encode("utf-8")).hexdigest()


@dataclass
class ToolCallBudget:
    """Tracks tool-execution attempts for one chat turn and enforces limits."""

    max_calls: int = MAX_TOOL_CALLS_PER_TURN
    max_identical_calls: int = MAX_IDENTICAL_CALLS_PER_TURN
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES

    total_calls: int = field(default=0, init=False)
    executions: int = field(default=0, init=False)
    consecutive_failures: int = field(default=0, init=False)
    _signature_counts: dict[str, int] = field(default_factory=dict, init=False)

    def remaining(self) -> int:
        return max(0, self.max_calls - self.total_calls)

    def allow_next(self) -> bool:
        """Whether the budget allows attempting one more tool request at all."""
        if self.total_calls >= self.max_calls:
            return False
        if self.consecutive_failures >= self.max_consecutive_failures:
            return False
        return True

    def allow_call(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Whether this specific (tool, arguments) pair may be attempted now."""
        if not self.allow_next():
            return False
        signature = _call_signature(tool_name, arguments)
        return self._signature_counts.get(signature, 0) < self.max_identical_calls

    def record(self, tool_name: str, arguments: dict[str, Any], outcome: str) -> None:
        """Record one processed tool request and its outcome. Always call this --
        including for a request this budget itself denied (``OUTCOME_SKIPPED``)
        -- so the loop is guaranteed to terminate. See the module docstring
        for why ``total_calls`` (every processed request) and ``executions``
        (only ``OUTCOME_SUCCESS``) are deliberately different numbers.
        """
        self.total_calls += 1
        signature = _call_signature(tool_name, arguments)
        self._signature_counts[signature] = self._signature_counts.get(signature, 0) + 1

        if outcome == OUTCOME_SUCCESS:
            self.executions += 1
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
