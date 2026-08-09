# ADR-029 — The model-facing capability manifest/catalog is generated from installed registry metadata

## Status

Accepted and implemented, merged to `main` as part of V0.3A. Recorded
August 9, 2026, as part of the V0.3/V0.4 architecture lock. See
`docs/CAPABILITY_ARCHITECTURE.md` §5 and `docs/TOOL_SYSTEM.md` §16 for the
concrete result (`backend/capability_catalog.py`).

## Context

`backend/model_input.py`'s `CAPABILITY_MANIFEST` (ADR-022) is the fixed,
code-owned prose sent to the model on every turn describing what MootOS can
and cannot do. It was a deliberate improvement over relying on provider
personality for capability honesty, and it remains correct as of V0.2A: it
was hand-updated when the four V0.2A tools were added, and tests verify its
presence in every prepared request.

But it is still hand-maintained text describing registry contents by hand.
Nothing mechanically prevents it from going stale the next time a tool is
added, removed, or changed — exactly the drift risk ADR-028 identifies for
a hypothetical second registry, except this one already exists.

## Decision

**The model-facing capability manifest/catalog must eventually be
generated from the actual registered tool/capability metadata, not
authored by hand.**

- The registry (extended per ADR-028/V0.3A) becomes the single input the
  manifest is derived from.
- Generation does not need to happen in one step. V0.3A's job is making the
  registry metadata rich enough (descriptions, limitations, risk, side
  effects) that a generated manifest can be as clear as the current
  hand-written one.
- Until generation is fully in place, any hand-maintained capability text
  must not assert a capability the registry doesn't actually back — the
  existing capability-honesty rules in `CAPABILITY_MANIFEST` continue to
  apply in the interim.
- The model's own memory is never authoritative for installed capabilities,
  generated manifest or not — see `docs/CAPABILITY_ARCHITECTURE.md` §4.

## Consequences

### Positive

- Closes an already-real drift risk instead of leaving it as an accepted
  limitation indefinitely.
- The registry becomes provably the single source of truth for both
  execution and description, not just execution.
- Reduces a category of future review burden: reviewers stop having to
  manually check "does the manifest still match the registry" on every
  tool change.

### Tradeoffs

- A generated manifest needs to remain as readable to the model as the
  current hand-tuned prose — ADR-022's production testing found that vague
  or ambiguous capability wording caused real behavior problems (e.g. the
  model asking for confirmation instead of calling a tool). Generation
  must preserve that same clarity, which may require richer per-tool
  description/guidance fields, not just a mechanical dump of the schema.
- This ADR does not specify the generation mechanism or timing within
  V0.3A — that remains an implementation decision for when V0.3A is built.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §5 and §6 (V0.3A) for scope.
