# CB-006 — Parallel Work and Conflict Engine

**Status:** Designing

## Purpose
Maximize safe simultaneous specialist work without stacking on unmerged assumptions.

## Detect
Overlapping files/modules, shared schema/contract changes, dependency on unmerged code, incompatible migrations, shared-service conflicts, and integration-order risks.

## Rule
Independent tracks may run concurrently. If independence is uncertain, do not guess; block/ask or create an explicit integration plan.

## Acceptance
Provides green/yellow/red concurrency decisions with evidence and confidence, including predicted conflicts before dispatch.
