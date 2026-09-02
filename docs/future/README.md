# MootOS Future Architecture

This directory is the planning source of truth for capabilities that are not yet part of current `main`.

It must never be confused with `docs/CURRENT_IMPLEMENTATION.md`, the live Tool Registry, or current runtime behavior. Current code remains authoritative for what MootOS can actually do. This directory describes where the system is intended to go.

## Reading order

1. `architecture/MASTER_BLUEPRINT.md`
2. `architecture/CONSTITUTION.md`
3. `roadmap/ROADMAP.md`
4. `build-queue/QUEUE.md`
5. `build-queue/SLICE_CATALOG.md`
6. `slices/continuous-builder/`
7. `evolution-lab/README.md`
8. `evolution-lab/PROMOTION_PROTOCOL.md`
9. `adrs/`

## Bootstrap rule

Until the Continuous Builder exists, Codex/Claude remain workers controlled through the existing capability-build process and human review. The future documents do not grant new runtime authority. After the Continuous Builder is proven, it may read these planning artifacts and turn Ready slices into bounded worker handoffs.
