# ADR-037 — Continuous Builder is a control plane over existing coding workers

## Status
Proposed future decision; not implemented.

## Context
MootOS already has a controlled capability-build pipeline and Codex worker boundaries. The future system should not throw that work away and invent an unrelated coder.

## Decision
Build a Chief/Continuous Builder above existing coding machinery. It owns roadmap/dependency/priority/handoff/review/staging logic while coding workers remain replaceable executors.

The Chief Builder may recommend, dispatch within approved policy, monitor, review, and learn. It does not silently redefine Moot's product vision or gain Main merge authority.

## Consequences
- Existing V0.4 work becomes bootstrap infrastructure.
- Codex/Claude become specialists, not the source of architectural truth.
- The planning artifacts under `docs/future/` become future inputs after they are reconciled with current code.
