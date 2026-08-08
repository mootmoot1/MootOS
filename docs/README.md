# MootOS Documentation Index

This directory contains current architecture/operations documentation plus historical ADRs and production-verification records.

## Current source-of-truth reading order

For a reviewer trying to understand the repository **as it exists now**, use this order:

1. [`../README.md`](../README.md) — plain-language current system summary
2. [`CURRENT_CHECKPOINT.md`](CURRENT_CHECKPOINT.md) — latest verified project checkpoint
3. [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) — current architecture and behavior
4. [`API_REFERENCE.md`](API_REFERENCE.md) — current public/private API surface
5. [`../V0.1_REQUIREMENTS.md`](../V0.1_REQUIREMENTS.md) — current Version 0.1 requirements/status
6. [`../ROADMAP.md`](../ROADMAP.md) — current proposed development sequence
7. `backend/migrations.py` — authoritative current schema version and migration order

When these current documents conflict with an older PR verification record, branch-specific guide, or ADR scope statement, treat the older document as a historical snapshot and verify the present behavior against code.

## Important current checkpoint

As of August 8, 2026:

- current database schema is `4 — tasks`
- model Run logging exists
- Task v0.1 exists
- intelligent explicit chat memory correction exists
- explicit chat-driven Task creation exists
- scheduler/reminder delivery does **not** exist

The next proposed feature is Scheduler / Reminder v0.1, pending independent repository review.

## Architecture and feature guides

Useful focused documents include:

- `FOUNDATION_HARDENING.md`
- `CHAT_PROVIDER_PIPELINE.md`
- `MODEL_INPUT_AND_CAPABILITIES.md`
- `PRIVATE_HTTP_BOUNDARY.md`
- `MODEL_RUN_LOGGING.md`
- `TASKS.md`
- bootstrap profile guides
- memory lifecycle/retrieval guides

These may describe the specific feature checkpoint at which they were written. Do not automatically read an old statement such as `schema 2` or `no Tasks yet` as a claim about current `main`.

## ADRs

ADRs explain why a decision was made at a specific point in development. They should generally remain historically intact rather than being rewritten every time later capabilities are added.

Key later ADRs include:

- ADR-020 — Railway storage/readiness
- ADR-021 — atomic provider chat pipeline
- ADR-022 — model input/capability boundary
- ADR-023 — private HTTP boundary
- ADR-025 — model Run logging / execution-audit direction
- ADR-026 — Task v0.1 and Task-vs-Run-vs-future-Approval boundary

## Production verification records

Files with names such as `*_PRODUCTION_VERIFICATION_YYYY-MM-DD.md` are evidence records. They intentionally preserve what was true at that test date. Old schema/version wording in those records is not documentation drift and should not be mass-edited.

## Documentation maintenance rule

Behavior-changing PRs should update the smallest relevant current docs. Periodic synchronization PRs may update the central source-of-truth files after several rapid feature PRs, but must not rewrite historical evidence to make history look current.

Before a large external/AI architecture audit, synchronize the central current docs first, then instruct the reviewer to verify documentation claims against code rather than trusting documentation blindly.
