# ADR-031 — Protected core is enforced mechanically before capability-builder automation

## Status

Accepted. Recorded August 9, 2026, as part of the V0.3/V0.4 architecture
lock. **Implemented on branch `claude/v0.3d-protected-core-gates`, pending
merge** (August 2026) — see `docs/GATES_AND_RELEASE_SAFETY.md` for the
concrete gates, `scripts/gates/` for the implementation, and
`docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3D).

## Context

V0.2A's safety properties (fail-closed registry, frozen approval, risk
taxonomy) are enforced in code today, but the rules about what a future
automated process may or may not touch have so far existed only as written
policy (`ARCHITECTURE.md` §14, `AGENTS.md`'s Codex worker boundaries). Written
policy is sufficient while every change is authored and reviewed by a
person or by Claude/Codex under direct human instruction. It stops being
sufficient once MootOS or a builder process (V0.4A) can propose diffs on
its own initiative — at that point "the rules say not to touch auth" has to
become "a diff touching auth cannot pass," mechanically.

## Decision

Before any capability-builder automation is built (V0.4A), the protected
areas and release gates below become enforced checks, not just documented
rules.

**Protected areas** (at minimum): auth/session enforcement; Tool
permission enforcement (`backend/tool_executor.py`); the approval state
machine (`backend/tool_operations.py`); secret/env handling; production
deployment configuration (e.g. `railway.toml`); production `main`; and core
registration authority (`build_default_registry` and the explicit
registration call path).

**Migrations are nuanced, not blanket-blocked:** migration machinery
(`backend/migrations.py`) and existing migrations are protected — nothing
automated may change how migrations run or rewrite a past migration. A
*new, additive* migration proposed by an approved capability change may
pass through a higher review gate (stricter review, still human-approved)
rather than being unconditionally forbidden, matching how MootOS already
treats schema changes as routine but reviewed (see ADR-027's migration 5).

**Mechanical gates** (block automatically): tests pass; contract/schema
validity; required risk classification present and non-default;
protected-path check; secret scan; migration safety check per the nuance
above; no execution outside the central Tool path; no approval bypass;
exact branch/commit identity (a gate result only applies to the exact
commit it ran against).

AI review remains advisory (ADR-032); human approval controls merge,
install, and deploy regardless of gate results.

## Consequences

### Positive

- Converts the highest-stakes safety rules from something a reviewer has
  to remember to check into something that fails the build automatically.
- Establishes the gate infrastructure *before* there's an automated
  producer of diffs to gate — the order Grok's review specifically called
  out as necessary, and this document agrees with.
- The migration nuance avoids two failure modes at once: a blanket
  migration block that makes V0.4A unable to ever add real capability
  (most useful tools eventually need schema), and an unguarded migration
  path that lets automation quietly restructure the database.

### Tradeoffs

- Building real mechanical gates (not just documenting them) is
  nontrivial work that has to land before V0.4A, which lengthens V0.3D
  relative to treating it as "just write it down." This is an accepted
  cost — the alternative is shipping capability-builder automation without
  it.
- A protected-path check is only as good as the list of paths it checks;
  the list above is a minimum, not a promise it's exhaustive. Extending it
  later does not require a new ADR unless the *kind* of thing being
  protected changes.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3D) and §8 for how this
relates to advisory AI review.
