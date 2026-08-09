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

As of August 9, 2026:

- current database schema is `5 — tool_system`
- model Run logging exists
- Task v0.1 exists
- intelligent explicit chat memory correction exists
- explicit chat-driven Task creation exists
- the V0.2A Tool Foundation exists, merged to `main` and live-verified on
  Railway/OpenAI (`docs/TOOL_SYSTEM.md`, ADR-027)
- the V0.3A Capability-Aware Tool System exists, merged to `main`
  (`docs/TOOL_SYSTEM.md` §16, ADR-028/ADR-029)
- V0.3B Structured Gap Reasoning is implemented on branch
  `claude/v0.3b-structured-gap-reasoning`, **not yet merged**
  (`docs/GAP_REASONING.md`, ADR-030)
- scheduler/reminder delivery does **not** exist

The locked next-phase plan is `docs/CAPABILITY_ARCHITECTURE.md` and
ADR-028 through ADR-034's full V0.3/V0.4 sequence. Scheduler/Reminder v0.1
remains a deferred, planned capability (Decision 011, `ROADMAP.md`), not
the active next feature.

## Architecture and feature guides

Useful focused documents include:

- `CAPABILITY_ARCHITECTURE.md` — the locked V0.3/V0.4 plan: conceptual
  model, source-of-truth hierarchy, phase sequence, protected core,
  review roles, and deferred items
- `TOOL_SYSTEM.md` — the current, implemented, executable Tool System
- `GAP_REASONING.md` — V0.3B structured gap reasoning (not yet merged to
  `main` — see its own Status line)
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
- ADR-027 — Tool Foundation v0.2A (the executable Tool Registry/executor/
  approval system)
- ADR-028 — capability as semantic grouping over the Tool Registry, not a
  parallel executable registry
- ADR-029 — generated capability manifest instead of hand-maintained prose
- ADR-030 — structured, logged, advisory gap reports
- ADR-031 — protected core enforced mechanically before builder automation
- ADR-032 — multi-AI review is advisory with distinct, non-overlapping roles
- ADR-033 — Local Companion / automatic Codex dispatch are usage-gated
- ADR-034 — capability-build pipeline proven manually before automation

## Production verification records

Files with names such as `*_PRODUCTION_VERIFICATION_YYYY-MM-DD.md` are evidence records. They intentionally preserve what was true at that test date. Old schema/version wording in those records is not documentation drift and should not be mass-edited.

## Documentation maintenance rule

Behavior-changing PRs should update the smallest relevant current docs. Periodic synchronization PRs may update the central source-of-truth files after several rapid feature PRs, but must not rewrite historical evidence to make history look current.

Before a large external/AI architecture audit, synchronize the central current docs first, then instruct the reviewer to verify documentation claims against code rather than trusting documentation blindly.
