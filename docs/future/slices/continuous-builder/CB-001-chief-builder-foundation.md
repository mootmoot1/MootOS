# CB-001 — Chief Builder Foundation

**Status:** Designing

## Purpose
Create the coordinator layer above the existing coder/capability-build foundation. It must understand planned work and current capabilities without writing code itself.

## In scope
- Read approved future planning artifacts and current capability truth.
- Identify candidate Ready slices.
- Recommend the next slice and explain why.
- Report capability gaps that prevent execution.
- Remain advisory/read-only in this slice.

## Out of scope
No worker dispatch, PR creation, staging, Main merge, architecture mutation, runtime tool registration, or autonomous loop.

## Dependencies
Current V0.4 capability-build artifacts and current self/capability inspection must be rechecked before implementation.

## Acceptance
Given a small slice queue, returns the next eligible slice, reasoning, dependencies, blockers, and confidence without changing repository/runtime state.

## Tests
Deterministic ranking eligibility tests, blocked dependency cases, empty queue, ambiguous capability cases, and no-write/no-dispatch assertions.
