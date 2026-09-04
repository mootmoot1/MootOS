# Continuous Builder Phase 2 schema and rollback contract

## Status

Implemented (migrations 006 and 007, `backend/migrations.py`). Originally an approved implementation design for CB-008 describing only migration 006; migration 006 and this document's rollback contract have since been merged to `main`. Phase 2.5 hardening added migration 007 (below) and made the "safety and rollback" contract mechanically enforced rather than purely a documented promise.

## Tables

Migration 006 adds isolated `builder_*` tables for immutable blueprint snapshots, immutable slice versions, append-only queue events, attempts, leases, durable idempotency records, and bounded artifact references. Existing tables and columns are not rewritten or deleted.

Foreign keys bind every slice to its exact blueprint version and every event, attempt, lease, and artifact reference to that slice. Unique constraints bind blueprint content digests, event IDs/digests, one sequence per slice, attempt IDs, active lease ownership, and idempotency keys.

Migration 007 (Phase 2.5 hardening) is additive-only -- migration 006 is historical and is never edited in place (`scripts/gates/migration_safety.py` fails any diff that changes a historical migration function's source). It:

- adds `blueprint_id`/`blueprint_version`/`slice_version` columns to `builder_leases` and rescopes the active-lease uniqueness index from `(slice_id)` to `(blueprint_id, blueprint_version, slice_id, slice_version)`, so an in-flight lease against one blueprint version can no longer block or be confused with an identically-named slice in a different blueprint version;
- rebuilds `builder_events` (via SQLite's create-copy-swap procedure, since `ALTER TABLE` cannot add a foreign key to an existing table) to add `FOREIGN KEY (attempt_id) REFERENCES builder_attempts (attempt_id)`, so `builder_events.attempt_id` can never dangle -- a `NULL` attempt_id (transitions with no attempt yet) remains valid, only a *non-null* value must reference a real attempt;
- adds `builder_lease_reconciliations`, an audited trail for explicitly resolving expired-but-unreleased leases (see "Lease reconciliation" below).

## Safety and rollback

The migration is forward-only in production. Operational rollback disables Continuous Builder writers and restores the pre-migration database backup; dropping tables in place is not an approved production rollback. A test-only downgrade proof may drop the migration-006/007 tables in reverse dependency order on a disposable database (`tests/test_continuous_builder_audit.py::test_pre_migration_backup_is_restorable_on_disposable_database`).

**Mechanically enforced, not just documented:** `backend.migrations.run_migrations` refuses to apply any new migration when running on Railway (`RAILWAY_ENVIRONMENT`/`RAILWAY_PUBLIC_DOMAIN` set) unless `MOOTOS_MIGRATION_BACKUP_CONFIRMED=true` is set for that run, raising `MigrationBackupRequiredError` otherwise. This mirrors the existing Railway-only strictness pattern in `backend/db.py` (`validate_database_configuration`) rather than inventing a new one. Local development and the test suite are unaffected -- they run against disposable databases with no Railway environment variables set, so the gate never fires there.

The backup itself is taken with `backend.db_backup.create_sqlite_backup` (SQLite's online backup API, not a raw file copy, so it is safe against a live writer) and independently verified with `verify_sqlite_backup` (integrity check plus a table/row-count comparison against the source) before `MOOTOS_MIGRATION_BACKUP_CONFIRMED` should ever be set. Retain the backup until human acceptance of the new schema version. As of this Phase 2.5 pass, migration 006 (and 007) have still never been applied to the default MootOS/Railway database -- this refusal-by-default is what keeps that true mechanically, not only by convention.

## Lease reconciliation

Lease expiry alone never implies the worker stopped (`leases.inspect_lease` returns `expired_uncertain`, never a claim of `worker_stopped`). Redispatch against an expired, unreleased lease is not possible until `leases.reconcile_expired_lease` records an explicit, audited verdict in `builder_lease_reconciliations`: `worker_confirmed_stopped` releases the lease so a new attempt may be leased; `worker_confirmed_running` leaves the lease held and surfaces as `inspect_lease`'s `needs_human` status -- an explicit needs-human state, not a default. There is no silent takeover path anywhere in `leases.py`; `LeaseStatus.takeover_authorized` remains structurally present but is never set `True` by any code path in this phase.

Current state is reconstructed from the event chain. No mutable current-state row is authoritative.
