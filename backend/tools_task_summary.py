"""V0.3E proof-capability tool: ``tasks.status_summary``.

One new registered tool, ``RISK_READ_ONLY``, backed by a thin adapter over
``backend.tasks.count_tasks_by_status`` -- exactly the same shape as every
tool in ``backend/tools_reference.py``: no new storage, no new schema, no
external connector, no credentials. See
``docs/CAPABILITY_BUILD_PIPELINE.md`` and
``capability_specs/tasks_status_summary.json`` for the full spec/lifecycle
record this tool was built against, and
``docs/CAPABILITY_ARCHITECTURE.md`` Sec6 (V0.3E) for why this was chosen
as the manual pipeline's proof capability.

**This module registering a ``ToolDefinition`` does not, by itself, make
this tool live.** Only ``register_v03e_tools`` being called from
``backend.tool_registry.build_default_registry`` wires it into the
process-wide default registry -- and that one-line addition to
``backend/tool_registry.py`` is itself a protected-path change (ADR-031),
so it is expected to (and does) fail V0.3D's protected-path gate, exactly
like every other protected-core change: a mechanical signal for explicit
human review, not a bug to route around. See
``docs/GATES_AND_RELEASE_SAFETY.md`` Sec9.
"""

from typing import Any

from backend.runs import DATA_EXPOSURE_LOCAL
from backend.tasks import TASK_STATUSES, count_tasks_by_status as _count_tasks_by_status
from backend.tool_registry import ToolRegistry
from backend.tool_types import RISK_READ_ONLY, ToolDefinition, ToolExecutionContext, ToolExecutionError


TOOL_VERSION = "1"


# --- tasks.status_summary -----------------------------------------------------


def _tasks_status_summary(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    project = arguments.get("project")
    try:
        counts = _count_tasks_by_status(project=project)
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    return {"counts": counts, "total": sum(counts.values()), "project": project}


TASKS_STATUS_SUMMARY = ToolDefinition(
    name="tasks.status_summary",
    version=TOOL_VERSION,
    description=(
        "Report how many MootOS Tasks currently exist in each status "
        f"({', '.join(sorted(TASK_STATUSES))}), optionally scoped to one "
        "project. Use this instead of calling tasks.list and counting rows "
        "yourself -- this returns an exact, deterministic breakdown in one "
        "call."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project": {"type": "string", "minLength": 1, "maxLength": 100},
        },
        "required": [],
        "additionalProperties": False,
    },
    risk=RISK_READ_ONLY,
    data_exposure=DATA_EXPOSURE_LOCAL,
    executor=_tasks_status_summary,
    capabilities=("tasks.status_insight",),
    side_effects="None -- read-only.",
    idempotent=True,
    limitations=(
        "Reports counts only, never the underlying task rows or content; use "
        "tasks.list for that. Every status in TASK_STATUSES is always present "
        "in the result, including as zero."
    ),
    depends_on=("tasks.list",),
)


V03E_TOOLS = (TASKS_STATUS_SUMMARY,)


def register_v03e_tools(registry: ToolRegistry) -> None:
    """Register V0.3E's one proof-capability tool on ``registry``.

    Always registered (no configuration gate) -- unlike ``web.search``,
    this tool needs no external service or credential, so there is no
    "unconfigured" state for it to conditionally hide behind.
    """
    for definition in V03E_TOOLS:
        registry.register(definition)
