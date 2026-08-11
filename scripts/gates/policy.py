"""The protected-core path policy (V0.3D, ADR-031).

This is the single source of truth for which paths a mechanical gate
refuses to let an ordinary diff touch. It is deliberately data, not logic
— `protected_paths.py` contains the evaluation code; this file only lists
paths and the reasoning for each.

**This file is itself listed in `DENIED_PATHS` (see `scripts/gates/`
below).** A diff that edits this policy to weaken it is, by definition, a
diff touching a protected path, and fails the same gate every other
protected-path change fails. Combined with CI running the gate from a
trusted extraction of the base branch rather than the proposed branch's own
copy (`docs/GATES_AND_RELEASE_SAFETY.md`), a single PR cannot both weaken
this policy and have that weakening take effect against itself.

Changing this file legitimately (a human, reviewed, deliberate policy
update) remains possible — it just means the PR will show the
protected-path gate as failed, which is the intended signal for human
maintainers to give it elevated scrutiny before merging outside the
automated path. See ADR-031's Consequences: "Extending it later does not
require a new ADR unless the kind of thing being protected changes."
"""

# --- Denied paths ------------------------------------------------------------
#
# Exact repository-relative file paths, or directory prefixes (trailing
# "/"), that an ordinary diff may never touch. Each entry maps to a
# concrete ADR-031 protected area; see the inline reasoning.
#
# Deliberately NOT included, and why:
#
# - backend/migrations.py: migration machinery and historical migrations
#   ARE protected, but through migration_safety.py's function-level
#   AST diff instead of this blunt file-level gate -- ADR-031 explicitly
#   distinguishes "rewriting history" (always blocked) from "adding a new,
#   additive migration" (allowed through a higher review gate), which a
#   whole-file block cannot express. See migration_safety.py.
# - backend/tools_reference.py, backend/tools_web.py, and any future
#   backend/tools_*.py: these are exactly where new tool modules belong.
#   V0.3E/V0.4A's future capability-build pipeline must be able to add a
#   new tool module -- protecting this class of file would make that
#   workflow impossible, which ADR-031's own "important design question"
#   (docs/GATES_AND_RELEASE_SAFETY.md "Registration authority without
#   blocking legitimate registration") explicitly requires staying open.
# - docs/, tests/, ADRs, requirements*.txt: not named in ADR-031's
#   protected-area list, and legitimate future capability work needs to
#   freely add tests and docs (V0.3E's own pipeline requires both).
DENIED_PATHS: tuple[str, ...] = (
    # --- Tool permission/risk enforcement (ADR-031) ---
    # The centralized executor: the only code path allowed to call a tool's
    # executor callable, and the second (defensive) place risk/approval is
    # enforced (docs/TOOL_SYSTEM.md Sec7).
    "backend/tool_executor.py",
    # The model<->tool conversation loop: decides read_only auto-executes,
    # internal_write routes to approval, high_risk is refused. Weakening
    # this would let a write-capable tool run without human approval.
    "backend/tool_conversation.py",
    # Per-turn call budget / loop protection -- part of the same centralized
    # execution-safety boundary.
    "backend/tool_budget.py",
    # The contract: ToolDefinition, the risk taxonomy (RISK_READ_ONLY /
    # RISK_INTERNAL_WRITE / RISK_HIGH_RISK), and ToolExecutionContext
    # (whose `approved` flag only backend/tool_operations.py may set True).
    "backend/tool_types.py",
    # Tool-argument schema validation, which tool_executor.py relies on
    # before authorizing execution.
    "backend/tool_validation.py",
    # The approval state machine (ADR-031's named protected area): frozen
    # operations, the pending/executing/succeeded/rejected/failed/expired
    # states, and the duplicate-claim/expiry safety guarantees.
    "backend/tool_operations.py",
    # --- Core registration authority (ADR-031) ---
    # ToolRegistry's fail-closed register()/get() contract and
    # build_default_registry()/get_tool_registry(), the sole explicit
    # registration entry point. A future legitimate registration-entry
    # addition (V0.3E/V0.4A) still touches this file and will still trip
    # this gate -- that is the intended elevated-review signal, not a bug;
    # see docs/GATES_AND_RELEASE_SAFETY.md.
    "backend/tool_registry.py",
    # --- Auth/session enforcement + secret/env handling (ADR-031) ---
    "backend/auth.py",
    # --- Production routing for /chat and /tool-operations (ADR-031) ---
    # main.py holds both session/security-header middleware AND the /chat
    # route; tool_routes.py holds /tool-operations; application.py is the
    # composition root wiring routers (including tool_operations_router)
    # into the app -- removing that wiring would silently disable the
    # approval review endpoints.
    "backend/main.py",
    "backend/tool_routes.py",
    "backend/application.py",
    # --- Production deployment configuration (ADR-031) ---
    "railway.toml",
    # The CI workflow itself: without this, a diff could simply delete the
    # step that runs these gates and pass "cleanly".
    ".github/workflows/",
    # --- Self-protection ---
    # This gate's own policy and scripts. See the module docstring.
    "scripts/gates/",
)

# --- Explicit exceptions ------------------------------------------------------
#
# Exact repository-relative paths that are permitted despite falling under
# a DENIED_PATHS prefix. Empty today -- no current change needs one. This
# exists as a documented mechanism for a future, deliberately-reviewed
# narrow carve-out (e.g. a new test fixture file that must live under a
# denied directory for an unrelated structural reason), not as a
# general-purpose escape hatch. Adding an entry here is itself a change to
# this protected file, so it goes through the same elevated-review path as
# any other policy change.
ALLOWED_EXCEPTIONS: tuple[str, ...] = ()
