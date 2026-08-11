"""V0.3E proof-capability #2: ``projects.overview``.

One new registered tool, ``RISK_READ_ONLY``, a thin adapter over
``backend.project_insight.summarize_projects`` -- the same shape as every
tool in ``backend/tools_reference.py``, ``backend/tools_web.py``, and
``backend/tools_task_summary.py``: no new storage, no new schema, no
external connector, no credentials.

See ``capability_specs/projects_overview.json`` for the validated spec and
lifecycle record this tool was built against, and
``docs/CAPABILITY_BUILD_PIPELINE.md`` §12 for why this capability was
chosen as the manual pipeline's *second* proof (ADR-034 requires two
before any builder automation begins).

**This module defining a ``ToolDefinition`` does not make the tool live.**
Only ``register_v03e_proof2_tools`` being called from
``backend.tool_registry.build_default_registry`` wires it into the
process-wide registry -- and that one-line addition to
``backend/tool_registry.py`` is itself a protected-path change (ADR-031),
so it is expected to fail V0.3D's protected-path gate, exactly like proof
#1's did: a mechanical signal for explicit human review, not a bug to
route around. See ``docs/GATES_AND_RELEASE_SAFETY.md`` §9.
"""

from typing import Any

from backend.project_insight import MAX_PROJECT_ENTRIES, summarize_projects as _summarize_projects
from backend.runs import DATA_EXPOSURE_LOCAL
from backend.tool_registry import ToolRegistry
from backend.tool_types import (
    RISK_READ_ONLY,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionError,
)


TOOL_VERSION = "1"


# --- projects.overview ---------------------------------------------------------


def _projects_overview(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    project = arguments.get("project")
    try:
        return _summarize_projects(project=project)
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error


PROJECTS_OVERVIEW = ToolDefinition(
    name="projects.overview",
    version=TOOL_VERSION,
    description=(
        "Report an activity overview across MootOS projects: for each "
        "project, how many active memories, open and total Tasks, and "
        "conversations it has, plus when anything in it was last created "
        "or changed. Optionally "
        "scope to one project by name. Use this to answer questions like "
        "'what's going on in my projects', 'which project has been quiet', "
        "or 'how much do I have stored under Studio'. Returns counts and "
        "timestamps only -- never memory content, Task titles, "
        "conversation titles, or message text; use memory.search or "
        "tasks.list for actual content."
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
    executor=_projects_overview,
    capabilities=("projects.insight",),
    side_effects="None -- read-only.",
    idempotent=True,
    limitations=(
        "Returns counts and one last-activity timestamp per project, never "
        "any memory/Task/conversation content. Counts active memories only "
        "(archived and superseded memories are excluded from the count, "
        "though they still count as activity for the timestamp). Every "
        "project is listed even when it has no activity. Items not "
        "assigned to any project -- or assigned to a project name that no "
        "longer exists -- are reported together under 'unassigned', which "
        "is omitted when the call is scoped to a single project. At most "
        f"{MAX_PROJECT_ENTRIES} projects are returned; 'truncated' is true "
        "if there were more."
    ),
    depends_on=("projects.list",),
)


V03E_PROOF2_TOOLS = (PROJECTS_OVERVIEW,)


def register_v03e_proof2_tools(registry: ToolRegistry) -> None:
    """Register V0.3E proof #2's one tool on ``registry``.

    Always registered -- like ``tasks.status_summary`` and unlike
    ``web.search``, this tool needs no external service or credential, so
    there is no "unconfigured" state for it to conditionally hide behind.
    """
    for definition in V03E_PROOF2_TOOLS:
        registry.register(definition)
