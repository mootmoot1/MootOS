"""One-off script that produced capability_specs/tasks_status_summary.json.

This is not a runtime tool and is not imported by anything -- it is kept
in the repository so the exact sequence of explicit, human-attributed
lifecycle transitions used for V0.3E's proof capability is reproducible
and auditable, rather than a JSON file with no visible origin. Re-running
it regenerates the same file byte-for-byte except for the ``at``
timestamps.

Deliberately stops at ``ready_for_pr`` -- the ``merged`` transition is not
called here, because V0.3E's instructions are explicit: do not open a PR,
do not merge. That final transition is a human action taken outside this
script, after a real PR is opened and merged. See
``docs/CAPABILITY_BUILD_PIPELINE.md``.
"""

from pathlib import Path

from scripts.capability_pipeline.lifecycle import (
    STATE_IMPLEMENTED,
    STATE_READY_FOR_PR,
    STATE_REVIEWED,
    STATE_SPECIFIED,
    STATE_TESTED,
    attach_review,
    new_record,
    save_record,
    transition,
)
from scripts.capability_pipeline.review import (
    ROLE_ARCHITECTURE,
    ROLE_CORRECTNESS,
    ROLE_SECURITY,
    VERDICT_NO_CONCERNS,
    AdvisoryReview,
)
from scripts.capability_pipeline.spec import spec_from_dict


OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "capability_specs" / "tasks_status_summary.json"


SPEC = {
    "capability_id": "tasks.status_insight",
    "human_readable_goal": (
        "Answer 'how many Tasks do I have, broken down by status' (and "
        "optionally per project) in one deterministic call, instead of "
        "the model calling tasks.list and counting rows itself."
    ),
    "tool_names": ["tasks.status_summary"],
    "resource_or_connector": (
        "Task resource, local SQLite storage (existing `tasks` table, no "
        "schema change). No external connector, no credentials, no "
        "network access."
    ),
    "input_contract": {
        "type": "object",
        "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": [],
        "additionalProperties": False,
    },
    "output_contract": {
        "counts": "Mapping of every TASK_STATUSES value to an integer count (0 when none).",
        "total": "Sum of all counts.",
        "project": "The project argument echoed back, or null when unscoped.",
    },
    "side_effects": "None -- read-only. Performs a single SQL SELECT ... GROUP BY.",
    "has_side_effects": False,
    "idempotent": True,
    "risk": "read_only",
    "data_exposure": "local",
    "limitations": (
        "Reports counts only, never task titles/content; use tasks.list for "
        "that. Every status in TASK_STATUSES is always present in the "
        "result, including as zero, so callers never have to distinguish "
        "'zero' from 'not computed'."
    ),
    "required_tests": [
        "count_tasks_by_status reports every status including zero on an empty DB",
        "count_tasks_by_status counts real open/completed/cancelled tasks correctly",
        "count_tasks_by_status scopes correctly to one project",
        "count_tasks_by_status rejects a nonexistent project",
        "tasks.status_summary returns exact counts through the real executor",
        "tasks.status_summary scopes to project through the real executor",
        "tasks.status_summary rejects unexpected arguments (schema validation)",
        "tasks.status_summary executes without approval, being read_only",
        "the tool definition existing does not register it on any registry",
        "the tool appears in a fresh registry only after register_v03e_tools is called",
    ],
    "rollback_notes": (
        "Revert the merge commit (or the specific commits) that added "
        "backend/tools_task_summary.py and the register_v03e_tools() call "
        "in backend/tool_registry.py. No migration was added, so there is "
        "no schema to reverse. No persisted state is specific to this tool "
        "-- it reads existing Task rows and writes nothing -- so reverting "
        "the code is the entire rollback; no data cleanup step exists. "
        "Once reverted and redeployed, tasks.status_summary immediately "
        "stops appearing in self.state / the V0.3A catalog / the generated "
        "manifest, because all three are generated from the live registry, "
        "never cached or hand-maintained."
    ),
    "registration_requirement": (
        "One explicit call, `register_v03e_tools(registry)`, added inside "
        "backend/tool_registry.py's build_default_registry(), following the "
        "exact same explicit-reference pattern as register_reference_tools "
        "and register_v03c_tools. This edits a protected-core file "
        "(backend/tool_registry.py is in scripts/gates/policy.py's "
        "DENIED_PATHS), so V0.3D's protected-path gate is expected to (and "
        "does) fail on this change -- that failure is the intended signal "
        "for explicit, elevated human review before merge, not a bug to "
        "route around. See docs/GATES_AND_RELEASE_SAFETY.md Sec9 and "
        "docs/CAPABILITY_BUILD_PIPELINE.md."
    ),
    "dependencies": ["tasks.list"],
    "protected_core_impact": ["backend/tool_registry.py"],
    "requires_human_registration_review": True,
}


def build() -> None:
    spec = spec_from_dict(SPEC)

    record = new_record(
        spec,
        actor="Darrick (product owner)",
        note=(
            "Proposed from a V0.3B-shaped gap: no existing tool answers "
            "'how many open Tasks do I have' without the model manually "
            "counting tasks.list rows. See "
            "docs/CAPABILITY_BUILD_PIPELINE.md Sec2 for the full Gap "
            "Report this spec was drafted from."
        ),
    )
    record = transition(
        record,
        STATE_SPECIFIED,
        actor="Darrick (product owner)",
        note="Capability spec reviewed and validated against the schema (scripts/capability_pipeline/spec.py).",
    )
    record = transition(
        record,
        STATE_IMPLEMENTED,
        actor="Claude (manual implementation, this session)",
        note=(
            "Implemented on branch claude/v0.3e-manual-capability-pipeline: "
            "backend/tasks.py:count_tasks_by_status, "
            "backend/tools_task_summary.py, and the registration call in "
            "backend/tool_registry.py."
        ),
    )
    record = transition(
        record,
        STATE_TESTED,
        actor="Claude (manual implementation, this session)",
        note=(
            "tests/test_tools_task_summary.py (13 tests) and the updated "
            "tests/test_tool_registry.py exact-set assertion all pass; "
            "full existing suite re-run with zero regressions."
        ),
    )

    record = attach_review(
        record,
        AdvisoryReview(
            role=ROLE_CORRECTNESS,
            reviewer="Claude",
            summary=(
                "The aggregate query is a straightforward GROUP BY over the "
                "existing tasks table; the executor adapter follows the "
                "exact shape of every other read-only reference tool. "
                "Tests cover the zero-task case, mixed statuses, project "
                "scoping, a nonexistent project, and both the domain "
                "helper and the tool boundary."
            ),
            findings=(
                "count_tasks_by_status always returns every TASK_STATUSES "
                "key, including 0 -- verified by a dedicated test, so a "
                "caller can't mistake 'no data' for 'not computed'.",
            ),
            verdict=VERDICT_NO_CONCERNS,
        ),
    )
    record = attach_review(
        record,
        AdvisoryReview(
            role=ROLE_SECURITY,
            reviewer="Claude (acting in the security/permissions role)",
            summary=(
                "Read-only, RISK_READ_ONLY, DATA_EXPOSURE_LOCAL, no "
                "external network call, no new credential, no filesystem "
                "or shell access. Auto-executes without approval like "
                "every other read_only tool -- correct per the existing "
                "risk taxonomy, not a new exception. The one real-risk "
                "surface is the registration edit to "
                "backend/tool_registry.py, which is a protected path and "
                "correctly fails V0.3D's protected-path gate, forcing "
                "explicit human review before merge."
            ),
            findings=(
                "Input schema accepts only an optional bounded string "
                "'project' -- no way to inject SQL (parameterized query) "
                "or reach any path outside the tasks table.",
                "No write path exists anywhere in this change -- confirmed "
                "by re-running scripts/gates/registration_authority.py "
                "against the new backend files.",
            ),
            verdict=VERDICT_NO_CONCERNS,
        ),
    )
    record = attach_review(
        record,
        AdvisoryReview(
            role=ROLE_ARCHITECTURE,
            reviewer="Claude (acting in the architecture/duplication role)",
            summary=(
                "New capability id (tasks.status_insight) distinct from "
                "the existing tasks.manage grouping -- correctly modeled "
                "as a new capability per docs/CAPABILITY_ARCHITECTURE.md "
                "Sec3, not bolted onto an existing one. Lives in its own "
                "backend/tools_task_summary.py module rather than being "
                "appended to backend/tools_reference.py, matching the "
                "pattern documented for future capability modules "
                "(docs/GATES_AND_RELEASE_SAFETY.md Sec9). No duplicate "
                "aggregation logic -- reuses the same database_connection "
                "helper every other backend/tasks.py function uses."
            ),
            findings=(),
            verdict=VERDICT_NO_CONCERNS,
        ),
    )

    record = transition(
        record,
        STATE_REVIEWED,
        actor="Darrick (product owner)",
        note=(
            "All three advisory reviews read; no blocking concerns raised. "
            "Reviews remain advisory only -- this transition is the human "
            "decision to proceed, not automatic from the reviews themselves."
        ),
    )
    record = transition(
        record,
        STATE_READY_FOR_PR,
        actor="Darrick (product owner)",
        note=(
            "Implementation, tests, gates, and reviews are complete on the "
            "isolated branch. Per this phase's explicit instructions, no "
            "PR is opened and nothing is merged in this session -- the "
            "final 'merged' transition happens only when a human actually "
            "merges a real PR."
        ),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_record(record, OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH} at state={record.state}")


if __name__ == "__main__":
    build()
