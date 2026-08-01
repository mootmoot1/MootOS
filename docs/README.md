# MootOS Documentation Index

This directory contains the operational and historical documentation for MootOS.

The documentation is divided into four types so readers can tell the difference between what exists now, how to operate it, why decisions were made, and what is planned for later.

## 1. Current system truth

These documents describe the code and deployment that exist today.

- [`CURRENT_CHECKPOINT.md`](CURRENT_CHECKPOINT.md) — latest verified project status and next milestone
- [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) — current modules, request flows, boundaries, and known limitations
- [`API_REFERENCE.md`](API_REFERENCE.md) — current HTTP routes, request fields, response shapes, and errors
- [`DATA_AND_PERSISTENCE.md`](DATA_AND_PERSISTENCE.md) — SQLite layout, database paths, Railway volume rules, backup guidance, migrations, and memory lifecycle persistence
- [`FOUNDATION_HARDENING.md`](FOUNDATION_HARDENING.md) — centralized SQLite settings, schema migrations, production auth safety, validation, and deployment checks
- [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md) — non-private evidence from the completed pre-migration backup and restore drill
- [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md) — non-private evidence that migration 2 and correction worked in production and survived a rebuild

When a statement in a future-looking document conflicts with these files, these files should be treated as the description of the current implementation.

## 2. Operations

These documents explain how to deploy, verify, recover, and maintain the live system.

- [`PHONE_DEPLOYMENT.md`](PHONE_DEPLOYMENT.md) — initial Railway and phone setup
- [`OPERATIONS_RUNBOOK.md`](OPERATIONS_RUNBOOK.md) — routine deployment, health checks, persistence verification, incident response, migration safety, and rollback
- [`MANUAL_BACKUP_AND_RESTORE.md`](MANUAL_BACKUP_AND_RESTORE.md) — WAL-safe manual snapshot, off-volume transfer, restore drill, and production restore safeguards

## 3. Architecture history

These documents preserve why important technical choices were made.

- [`ADR-011-project-system-v0.1.md`](ADR-011-project-system-v0.1.md)
- [`ADR-012-conversation-engine-and-model-router.md`](ADR-012-conversation-engine-and-model-router.md)
- [`ADR-013-mobile-chat-interface.md`](ADR-013-mobile-chat-interface.md)
- [`ADR-014-secure-phone-deployment.md`](ADR-014-secure-phone-deployment.md)
- [`ADR-015-foundation-hardening.md`](ADR-015-foundation-hardening.md)
- [`ADR-016-memory-lifecycle-and-correction.md`](ADR-016-memory-lifecycle-and-correction.md)
- [`ADR-017-recoverable-memory-forget-and-restore.md`](ADR-017-recoverable-memory-forget-and-restore.md)

The repository root also contains:

- [`../DECISIONS.md`](../DECISIONS.md) — original high-level decisions
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — long-term architecture vision

ADRs should not be silently rewritten to make history look cleaner. When a decision changes, add a new ADR and mark the older one as superseded when appropriate.

## 4. Planning and governance

- [`../ROADMAP.md`](../ROADMAP.md) — planned versions and future capabilities
- [`../V0.1_REQUIREMENTS.md`](../V0.1_REQUIREMENTS.md) — Version 0.1 release criteria
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — branch, testing, approval, security, and documentation rules
- [`DOCUMENTATION_POLICY.md`](DOCUMENTATION_POLICY.md) — rules for keeping documentation synchronized with the code

## Recommended reading order

For a new developer or AI coding agent:

1. `README.md`
2. `docs/CURRENT_CHECKPOINT.md`
3. `docs/CURRENT_IMPLEMENTATION.md`
4. `docs/DATA_AND_PERSISTENCE.md`
5. `docs/FOUNDATION_HARDENING.md`
6. `CONTRIBUTING.md`
7. The ADR related to the system being changed
8. The relevant code and tests

For operating the live Railway deployment:

1. `docs/OPERATIONS_RUNBOOK.md`
2. `docs/DATA_AND_PERSISTENCE.md`
3. `docs/FOUNDATION_HARDENING.md`
4. `docs/PHONE_DEPLOYMENT.md`

For planning a future feature:

1. `ROADMAP.md`
2. `V0.1_REQUIREMENTS.md`
3. `ARCHITECTURE.md`
4. Existing ADRs
5. `docs/CURRENT_IMPLEMENTATION.md` to verify what the system actually supports today

## Documentation ownership

Documentation is part of the product, not optional cleanup.

Any pull request that changes behavior, configuration, storage, deployment, security, or architecture should update the relevant documentation in the same pull request. Documentation-only pull requests may improve clarity but must not claim that unimplemented behavior exists.
