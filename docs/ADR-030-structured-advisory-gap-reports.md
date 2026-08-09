# ADR-030 — Gap reports are structured, logged, advisory artifacts

## Status

Accepted; implemented on branch `claude/v0.3b-structured-gap-reasoning`
(`backend/gap_reasoning.py`), pending merge. Recorded August 9, 2026, as
part of the V0.3/V0.4 architecture lock. See `docs/CAPABILITY_ARCHITECTURE.md`
§6 (V0.3B) and `docs/GAP_REASONING.md` for the concrete result.

## Context

The product vision requires MootOS to take a natural-language goal ("I want
you to be able to do X") and determine what it can already do, what's
missing, and whether the gap is reasonably closeable. Natural-language goal
interpretation cannot be made fully deterministic — pretending otherwise
would produce a system that is either falsely confident or unusable for any
goal that isn't already phrased as a structured request.

## Decision

Gap reasoning is split into two stages with a hard seam between them:

```text
user goal (natural language)
  -> model interpretation                      [non-deterministic]
  -> structured proposed capability requirements
  -> deterministic resolution against the installed registry/catalog   [deterministic]
```

- Only the second stage — checking a structured requirement list against
  what's actually registered (ADR-028's registry) — is deterministic and
  auditable.
- The first stage's output is always treated as a proposal, logged as such,
  never as fact.
- Every goal is classified into exactly one of: **already possible**,
  **composable** from existing capabilities, **capability gap**, or
  **impossible / externally blocked**.
- Gap reports are logged using the existing Run-audit pattern (`docs/
  TOOL_SYSTEM.md` §8), so a wrong or hallucinated gap claim is visible and
  reviewable after the fact, the same honesty discipline `CAPABILITY_
  MANIFEST` already applies to capability claims (ADR-022).
- **A gap report can never itself make anything executable.** Turning a
  "capability gap" classification into an actual registered tool always
  goes through the human-approved build pipeline (ADR-034), never
  automatically, regardless of how confident the interpretation stage is.

## Consequences

### Positive

- Gap reasoning gets real, useful structure without a false claim of
  determinism that later reasoning or review would have to un-teach.
- Because gap reports are Run-logged, a pattern of wrong gap claims becomes
  visible over time instead of being an untracked, unverifiable model
  opinion.
- The hard seam at "gap report is advisory, never itself authorizing
  execution" closes the most dangerous failure mode Grok's review flagged:
  a model talking itself into believing a capability exists or should
  exist, and that belief propagating into action.

### Tradeoffs

- The interpretation stage will sometimes misclassify a goal (call
  something "impossible" that's actually composable, or vice versa).
  That's an accepted, expected error mode for a non-deterministic stage,
  not a bug to eliminate — it's why the report stays advisory and
  human-reviewed rather than acted on directly.
- This ADR does not specify the exact structured schema (field names,
  storage shape) — that is a V0.3B implementation detail.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3B) for the classification
categories and logging expectations in full.
