# Continuous Builder Phase 2 schema and rollback contract

## Status

Approved implementation design for CB-008. It describes migration 006; it does not itself apply a migration.

## Tables

Migration 006 adds isolated `builder_*` tables for immutable blueprint snapshots, immutable slice versions, append-only queue events, attempts, leases, durable idempotency records, and bounded artifact references. Existing tables and columns are not rewritten or deleted.

Foreign keys bind every slice to its exact blueprint version and every event, attempt, lease, and artifact reference to that slice. Unique constraints bind blueprint content digests, event IDs/digests, one sequence per slice, attempt IDs, active lease ownership, and idempotency keys.

## Safety and rollback

The migration is forward-only in production. Operational rollback disables Continuous Builder writers and restores the pre-migration database backup; dropping tables in place is not an approved production rollback. A test-only downgrade proof may drop only migration-006 tables in reverse dependency order on a disposable database.

Before any non-test application: take and verify a SQLite backup, stop writers, apply through `backend.migrations`, run schema/integrity checks, and retain the backup until human acceptance. This phase never applies migration 006 to the default MootOS database.

Current state is reconstructed from the event chain. No mutable current-state row is authoritative.
