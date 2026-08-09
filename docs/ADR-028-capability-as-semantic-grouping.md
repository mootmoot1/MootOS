# ADR-028 — Capability is semantic grouping over the Tool Registry, not a parallel executable registry

## Status

Accepted. Recorded August 9, 2026, as part of the V0.3/V0.4 architecture
lock. See `docs/CAPABILITY_ARCHITECTURE.md` for the full model this ADR is
one piece of.

## Context

V0.2A (ADR-027) established `backend/tool_registry.py` as the single,
explicit, fail-closed source of truth for what MootOS can invoke. Planning
for the next phase considered adding a separate "Capability Registry" —
a second data model describing abilities, inputs/outputs, permissions, and
so on — sitting above or alongside the Tool Registry.

That would create two systems that both claim to describe what MootOS can
do, with no mechanical guarantee they stay in agreement. The existing
`CAPABILITY_MANIFEST` (`backend/model_input.py`, ADR-022) is a small,
already-real example of this exact risk: it is hand-written prose that has
to be kept in sync with the registry by a human remembering to do it, and
nothing enforces that it actually is.

## Decision

**A capability is a semantic grouping/ability backed by one or more
registered tools. It is not a second executable system.**

- The Tool Registry remains the only executable source of truth (`docs/
  CAPABILITY_ARCHITECTURE.md` §2).
- A capability composes one or more `ToolDefinition`s already registered
  through the existing registry. A capability with no backing tool is a
  gap (see ADR-030), not an alternate way to make something runnable.
- Capabilities never execute anything themselves. Only a registered tool's
  executor, invoked through `backend/tool_executor.py`, ever runs code.
- No new registration path, no new fail-closed lookup mechanism, no new
  place a model or client could add something invocable is introduced by
  this decision.

Concretely, this means V0.3A's work is extending `ToolDefinition` with
additional metadata (side effects, idempotency, limitations, dependencies,
capability/category references) rather than building a parallel schema.

## Consequences

### Positive

- One executable source of truth stays true by construction — there is no
  second system for it to drift from.
- Future integrations keep plugging into the same proven registry/executor
  boundary (`docs/TOOL_SYSTEM.md`) instead of a second permission model.
- Capability-level reasoning (grouping, gap analysis) can be built as a
  read-only layer over the registry, which is inherently easier to review
  and harder to make into a bypass than a second write-capable system.

### Tradeoffs

- Some capability-level metadata (e.g. "capability X requires tools A and
  B together") has to live somewhere; V0.3A adds it to tool metadata and/or
  a thin, non-executable grouping structure, not to the registry's
  execution contract itself. Exactly where this metadata lives is a V0.3A
  implementation detail, not re-litigated by this ADR.
- This decision does not by itself solve manifest drift (ADR-029 does) or
  gap reasoning (ADR-030 does) — it only rules out the wrong shape for
  solving them.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §3 (conceptual model) and §6 (V0.3A)
for the concrete metadata additions this decision implies.
