# CB-003 — Dependency Graph Engine

**Status:** Designing

## Purpose
Make the roadmap a dependency graph rather than a numbered checklist, enabling linear upgrades and safe parallelism.

## Capabilities
- Hard and soft dependencies.
- Shared infrastructure dependencies.
- Capability-unlock edges.
- Cross-project edges.
- Circular dependency detection.
- Critical path and unblock analysis.
- Explain which completed slice unlocks which future work.

## Acceptance
The engine correctly blocks unmet hard dependencies, surfaces cycles, identifies parallel independent work, and explains downstream unlock value.
