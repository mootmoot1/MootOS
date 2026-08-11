"""One-off script that produced capability_specs/projects_overview.json.

Same role as ``build_proof_record.py`` did for proof #1: not a runtime
module and not imported by anything, kept in the repository so the exact
sequence of explicit, human-attributed lifecycle transitions used for
V0.3E proof #2 is reproducible and auditable rather than a JSON file with
no visible origin. Re-running it regenerates the same file byte-for-byte
except for the ``at`` timestamps.

Deliberately stops at ``ready_for_pr``. The ``merged`` transition is not
called here -- V0.3E proof #2's instructions are explicit: do not open a
PR, do not merge. That final transition is a human action taken outside
this script, after a real PR is opened and merged. See
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
    VERDICT_CONCERNS_NOTED,
    VERDICT_NO_CONCERNS,
    AdvisoryReview,
)
from scripts.capability_pipeline.spec import spec_from_dict


OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "capability_specs" / "projects_overview.json"
)


SPEC = {
    "capability_id": "projects.insight",
    "human_readable_goal": (
        "Answer 'what's going on in each of my projects' -- how many "
        "active memories, open and total Tasks, and conversations each "
        "project holds, and when it was last touched -- in one "
        "deterministic call, instead of the model calling projects.list "
        "and then being unable to count anything per project."
    ),
    "tool_names": ["projects.overview"],
    "resource_or_connector": (
        "Project resource, joined across the existing memories, tasks, and "
        "conversations tables in local SQLite (no schema change). No "
        "external connector, no credentials, no network access."
    ),
    "input_contract": {
        "type": "object",
        "properties": {"project": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": [],
        "additionalProperties": False,
    },
    "output_contract": {
        "projects": (
            "One entry per project: name, active_memories, open_tasks, "
            "total_tasks, conversations, last_activity_at."
        ),
        "count": "Number of project entries returned.",
        "unassigned": (
            "Same count fields for items belonging to no project. Omitted "
            "when the call is scoped to a single project."
        ),
    },
    "side_effects": "None -- read-only. Issues four SELECT queries and writes nothing.",
    "has_side_effects": False,
    "idempotent": True,
    "risk": "read_only",
    "data_exposure": "local",
    "limitations": (
        "Counts and one last-activity timestamp per project only -- never "
        "memory content, Task titles, conversation titles, or message "
        "text. Counts active memories only (archived and superseded are "
        "excluded from the count, though they still count as activity for "
        "the timestamp). Every project is listed even with zero activity. "
        "Items with no project -- or naming a project that no longer "
        "exists -- are reported together under 'unassigned', which is "
        "omitted for a project-scoped call. At most MAX_PROJECT_ENTRIES "
        "(200) projects are returned, with an explicit 'truncated' flag. "
        "The four aggregates are separate statements outside an explicit "
        "transaction, so a concurrent writer could produce a slightly "
        "inconsistent rollup; accepted for a single-user deployment."
    ),
    "required_tests": [
        "every existing project appears even with no activity",
        "counts span memories, tasks, and conversations",
        "open vs total task counts are distinct",
        "archived memories are excluded from active counts",
        "projects do not leak counts into each other",
        "unassigned items are reported separately, not silently dropped",
        "project scoping is case-insensitive and echoes the canonical name",
        "last_activity_at takes the newest across all three resources",
        "a nonexistent project fails closed",
        "hostile project strings (SQL metacharacters, LIKE wildcards) fail closed",
        "empty and overlong project strings are rejected by schema validation",
        "output never contains memory/task/conversation content",
        "the implementation modules contain no SQL write verb at all",
        "repeated calls are idempotent and change no state",
        "the capability is absent from every V0.3A derived view before registration",
        "V0.3B resolves it missing before registration and installed after",
        # Added after advisory review found real defects -- each of these
        # is a regression test for a specific reported bug.
        "differently-cased project rows accumulate instead of overwriting",
        "rows naming a project that no longer exists land in unassigned",
        "completing a Task moves last_activity_at forward",
        "archiving the newest memory never moves last_activity_at backward",
        "any of the three resources can be the last-activity winner",
        "superseded memories are excluded from active counts",
        "no projects at all returns a clean empty result",
        "results are capped and truncation is reported honestly",
        "count always equals the number of entries returned",
        "each entry has exactly the documented key set",
        "explicit null project means unscoped (documented behavior)",
        "length boundaries are one-off correct on the accepting side",
    ],
    "rollback_notes": (
        "Revert the merge commit (or the specific commits) that added "
        "backend/project_insight.py, backend/tools_project_insight.py, and "
        "the register_v03e_proof2_tools() call in "
        "backend/tool_registry.py. No migration was added, so there is no "
        "schema to reverse. No persisted state is specific to this tool -- "
        "it only reads existing rows and writes nothing -- so reverting "
        "the code is the entire rollback; no data cleanup step exists. "
        "Once reverted and redeployed, projects.overview immediately stops "
        "appearing in self.state / the V0.3A catalog / the generated "
        "manifest, because all three are generated from the live registry "
        "on every call, never cached or hand-maintained. Proven "
        "structurally by "
        "tests/test_capability_proof2_invariants.py::"
        "test_not_calling_the_registration_makes_it_disappear_again."
    ),
    "registration_requirement": (
        "One explicit call, `register_v03e_proof2_tools(registry)`, added "
        "inside backend/tool_registry.py's build_default_registry(), "
        "following the exact same explicit-reference pattern as "
        "register_reference_tools, register_v03c_tools, and proof #1's "
        "register_v03e_tools. This edits a protected-core file "
        "(backend/tool_registry.py is in scripts/gates/policy.py's "
        "DENIED_PATHS), so V0.3D's protected-path gate is expected to (and "
        "does) fail on this change -- the intended signal for explicit, "
        "elevated human review before merge, not a bug to route around. "
        "See docs/GATES_AND_RELEASE_SAFETY.md Sec9."
    ),
    "dependencies": ["projects.list"],
    "protected_core_impact": ["backend/tool_registry.py"],
    "requires_human_registration_review": True,
}


# The three advisory reviews, recorded as reported. Each role was run as a
# separate model instance with its own independent context, reviewing the
# same immutable commit (f483ae1) with read-only tools -- a deliberate
# process improvement over proof #1, where one model wrote all three
# reviews in sequence. Verdicts are recorded as returned, including the
# security role's `concerns_noted`; see docs/CAPABILITY_BUILD_PIPELINE.md
# §13 for what was done about it.
REVIEWS: dict = {
    ROLE_CORRECTNESS: {
        "role": ROLE_CORRECTNESS,
        "reviewer": "Claude Opus 5 (independent reviewer instance, correctness role)",
        "summary": (
            "The core arithmetic is sound for the data shapes this app produces today, "
            "and the diff breaks nothing (944 passed). The lexicographic-timestamp claim "
            "is true in conclusion but false in its stated reason: isoformat() is NOT "
            "fixed-width (25 chars vs 32 when microseconds are exactly zero); it happens "
            "to order correctly because '+' (0x2B) sorts before '.' (0x2E). A 3000-sample "
            "randomized check found 0 lex/chrono mismatches and all six write paths use "
            "the same UTC constructor. The two real correctness defects are that the "
            "casefold merge OVERWRITES instead of accumulating (reproduced: 3 memories "
            "reported as 1), and that last_activity_at is not 'last touched' -- completing "
            "a task does not move it and archiving a memory moves it BACKWARD (both "
            "reproduced). The test file is broad but shallow: several tautological or "
            "vacuous assertions, and the module's one self-declared correctness detail "
            "(case merging) had zero coverage. One assertion updated in this diff is a "
            "genuine CI regression under a supported configuration."
        ),
        "findings": (
            "DEFECT (fixed): the casefold merge assigned rather than accumulated, so two "
            "GROUP BY rows differing only in case collapsed and the last row silently "
            "evicted the other spelling's counts; reproduced as 2+1 memories reported as 1.",
            "DEFECT (fixed): rows whose project value is absent from the projects table "
            "were dropped from BOTH the per-project entries and unassigned, directly "
            "defeating the docstring's stated reason for having an unassigned bucket.",
            "DEFECT (fixed): last_activity_at used MAX(created_at) for memories/tasks but "
            "MAX(updated_at) for conversations, so complete_task() did not move it even "
            "though the tool description promised 'when it was last touched'.",
            "DEFECT (fixed): last_activity_at could move backward during normal use -- "
            "archiving the newest active memory dropped it from the status='active' "
            "aggregate -- and neither the docstring nor the declared limitations said so.",
            "DEFECT (fixed): the module docstring claimed timestamps are 'always the same "
            "fixed-width shape', which is false; the ordering conclusion holds for a "
            "different reason, and a reader relying on fixed width (e.g. slicing) would "
            "be misled.",
            "REGRESSION (fixed): the new exact-sequence assertion in test_model_input.py "
            "terminates with 'and tasks.status_summary', so with MOOTOS_SEARCH_API_KEY set "
            "-- a supported configuration -- the manifest ends '...and web.search' and the "
            "test fails; the diff adopted the fragile form of an assertion whose fragility "
            "the codebase already knew about.",
            "ACCEPTED, documented: the four SELECTs run outside an explicit transaction, so "
            "a concurrent writer between statements could produce an internally "
            "inconsistent rollup; low severity for a single-user app.",
            "TEST QUALITY (fixed): several vacuous assertions -- a uuid4 inequality "
            "tautology, an 'is not None' on a dict value that can never be None, a "
            "metadata test that never touched a registry, an idempotency test that never "
            "inspected the database, and a write-verb scan that included docstrings while "
            "missing REPLACE/ATTACH/VACUUM.",
            "TEST QUALITY (fixed): zero coverage of the case-merge path -- the module's own "
            "self-declared correctness detail, and the one that was broken; no zero-project "
            "test; no superseded-memory test; no test where a memory or task is the "
            "last-activity winner; and the explicit {'project': null} case was untested.",
            "Explicitly clean: the open-vs-total task computation, the scoped-name equality "
            "filter, _newer's NULL handling, the maxLength/Field(max_length=100) "
            "consistency, omitting unassigned when scoped, and backward compatibility -- "
            "nothing pre-existing regresses at runtime.",
        ),
        "verdict": VERDICT_CONCERNS_NOTED,
    },
    ROLE_SECURITY: {
        "role": ROLE_SECURITY,
        "reviewer": "Claude Sonnet 5 (independent reviewer instance, security role)",
        "summary": (
            "Every query in backend/project_insight.py is parameterized and the module "
            "imports no write function, no network, filesystem, logging, or subprocess "
            "call. Live testing against a scratch database with SQL metacharacters and "
            "LIKE wildcards (\"' OR '1'='1\", \"'; DROP TABLE projects; --\", '%', '_') "
            "failed closed every time with the same static 'Project does not exist' "
            "message, leaving the table intact -- no injection and no leakage of the "
            "input or any row content through the error path. The backend/tool_registry.py "
            "edit is exactly the two lines claimed (one import, one call); running the "
            "real V0.3D gates confirms only the protected-path gate fires on that file, "
            "with risk_metadata and registration_authority both passing. read_only/local "
            "classification is correct and read-only auto-execution is appropriate. The "
            "one real gap relative to precedent in this codebase is the complete absence "
            "of any result-size bound on the rollup, unlike sibling list-shaped tools."
        ),
        "findings": (
            "No write path exists, direct or indirect: an independent grep for "
            "INSERT/UPDATE/DELETE/DROP/ALTER/CREATE TABLE/executemany/.commit(/BEGIN "
            "across both new files finds nothing but doc-comment text.",
            "data_exposure=local is correct -- the only I/O is a local SQLite "
            "connection; no network, HTTP, or model-provider call exists in either module.",
            "No content leakage, confirmed live: planted memory content, task titles, and "
            "conversation titles never appeared in the serialized output, and the "
            "not-found error is a hardcoded string that never echoes the caller's input.",
            "All SQL is parameterized with ? placeholders; adversarial SQL "
            "metacharacters and LIKE wildcards produced only the generic not-found error "
            "and left the projects table fully intact.",
            "The f-string SQL construction used elsewhere in the codebase (runs.py, "
            "tasks.py, tool_operations.py) interpolates only static column-list "
            "constants and is entirely absent from both new modules.",
            "read_only auto-execution is not a bypass: execute_tool applies the "
            "documented two-layer policy unchanged, verified live with approved=False.",
            "The backend/tool_registry.py diff is minimal and matches the commit "
            "message exactly; ToolRegistry.register/.get and tool_executor.py's "
            "risk enforcement are untouched, so no registration-authority weakening, "
            "discovery mechanism, or bypass was added.",
            "Minor DoS/perf surface: summarize_projects imposes no cap on the number of "
            "project rows returned -- unlike memory.search/tasks.list, which bound "
            "results to 50/100 -- and each call performs three unbounded GROUP BY scans; "
            "low severity for a single-user local tool, but a real deviation from this "
            "codebase's own established pattern for list-shaped tools.",
            "The capability_catalog.py addition is a purely cosmetic label string with "
            "no effect on registration or enforcement.",
        ),
        "verdict": VERDICT_CONCERNS_NOTED,
    },
    ROLE_ARCHITECTURE: {
        "role": ROLE_ARCHITECTURE,
        "reviewer": "Claude Haiku 4.5 (independent reviewer instance, architecture role)",
        "summary": (
            "The cross-table per-project activity rollup is architecturally sound: it "
            "introduces a genuinely distinct capability (projects.insight, activity "
            "aggregation, versus projects.view, project listing), places the "
            "cross-domain logic in its own module appropriately, follows the "
            "established thin-adapter tool pattern exactly, and avoids duplicating "
            "existing query logic. It respects AGENTS.md domain boundaries and "
            "includes comprehensive test coverage with adversarial input verification."
        ),
        "findings": (
            "Module placement is correct: backend/project_insight.py appropriately "
            "houses the cross-domain rollup instead of blurring memory.py, tasks.py, or "
            "conversation.py domain boundaries.",
            "No duplication detected: the per-project cross-table GROUP BY pattern does "
            "not exist elsewhere in backend/; count_tasks_by_status is single-table by "
            "status, not cross-table by project.",
            "The Capability/Tool model is applied correctly -- projects.insight is a "
            "non-executable semantic grouping distinct from projects.view, backed by "
            "the single registered tool projects.overview, with no layer confusion.",
            "The tool-module pattern matches exactly: thin executor extracting "
            "arguments, calling the backing function, converting ValueError to "
            "ToolExecutionError, with complete and consistent ToolDefinition metadata.",
            "Metadata is consistent with proof #1: input schema, risk, data_exposure, "
            "idempotent, and the depends_on-on-the-base-tool pattern all align with "
            "tasks.status_summary.",
            "No docs/CAPABILITY_ARCHITECTURE.md §9 violations: no second registry, no "
            "generalized connector framework, no autonomous deployment, and no "
            "lifecycle machinery beyond the flat state model already in use.",
        ),
        "verdict": VERDICT_NO_CONCERNS,
    },
}


def build() -> None:
    spec = spec_from_dict(SPEC)

    record = new_record(
        spec,
        actor="Darrick (product owner)",
        note=(
            "Proposed as V0.3E manual-pipeline proof #2 (ADR-034 requires "
            "two). Chosen over four other candidates to exercise the "
            "pipeline on a different resource and a different query shape "
            "than proof #1 -- a cross-table per-project rollup rather than "
            "a single-table status count. Gap verified against the real "
            "pre-proof-#2 registry: see "
            "capability_specs/projects_overview.gap_report.json."
        ),
    )
    record = transition(
        record,
        STATE_SPECIFIED,
        actor="Darrick (product owner)",
        note=(
            "Capability spec reviewed and validated against the existing "
            "V0.3E schema (scripts/capability_pipeline/spec.py), unchanged "
            "from proof #1 -- no pipeline redesign was needed."
        ),
    )
    record = transition(
        record,
        STATE_IMPLEMENTED,
        actor="Claude (manual implementation, human-directed)",
        note=(
            "Implemented on branch claude/v0.3e-proof-2-capability: "
            "backend/project_insight.py (the cross-resource rollup), "
            "backend/tools_project_insight.py (the tool adapter), and the "
            "one-line registration in backend/tool_registry.py."
        ),
    )
    record = transition(
        record,
        STATE_TESTED,
        actor="Claude (manual implementation, human-directed)",
        note=(
            "First pass: tests/test_tools_project_insight.py (31 tests) "
            "and tests/test_capability_proof2_invariants.py pass; full "
            "existing suite green; V0.3D gates run against the real branch "
            "diff, failing only on backend/tool_registry.py as intended. "
            "This state was committed as f483ae1 and handed to the three "
            "reviewers as an immutable artifact."
        ),
    )

    for role in (ROLE_CORRECTNESS, ROLE_SECURITY, ROLE_ARCHITECTURE):
        record = attach_review(record, AdvisoryReview(**REVIEWS[role]))

    record = transition(
        record,
        STATE_REVIEWED,
        actor="Darrick (product owner)",
        note=(
            "All three advisory reviews read. Process improvement over "
            "proof #1: each role ran as a separate model instance with its "
            "own independent context and read-only tools, reviewing the "
            "same immutable commit (f483ae1), rather than one model "
            "writing three reviews in sequence. Two of the three returned "
            "concerns_noted, and the concerns were real: four correctness "
            "defects (case-merge overwriting instead of accumulating, "
            "orphaned project rows vanishing entirely, last_activity_at "
            "not moving when a Task is completed, and last_activity_at "
            "moving backward when a memory is archived), one CI regression "
            "this diff itself introduced, one false docstring claim, and "
            "an unbounded result size. All were fixed and covered by "
            "regression tests before this transition; the full suite was "
            "re-run green afterwards. Reviews remain advisory only -- this "
            "transition is the human decision that the fixes are "
            "sufficient, not an automatic consequence of the reviews."
        ),
    )
    record = transition(
        record,
        STATE_READY_FOR_PR,
        actor="Darrick (product owner)",
        note=(
            "Implementation, tests, gates, and reviews complete on the "
            "isolated branch. Per this phase's explicit instructions no PR "
            "is opened and nothing is merged in this session -- the final "
            "'merged' transition happens only when a human actually merges "
            "a real PR."
        ),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_record(record, OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH} at state={record.state}")


if __name__ == "__main__":
    build()
