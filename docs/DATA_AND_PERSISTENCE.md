# MootOS Data and Persistence

**Applies to:** Version 0.1 with schema `2 — memory_lifecycle`

## Source of truth

Production data lives in one SQLite database:

```text
/data/mootos.db
```

GitHub stores code and documentation, not conversations, memories, credentials, or production backups. OpenAI generates normal chat responses but is not the history database; provider-side response storage is disabled.

## Database path

Resolution order:

1. `MOOTOS_DATABASE_PATH`
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`
3. Repository-local `data/mootos.db`

## Connection policy

All application connections use:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000 milliseconds
connection timeout = 5 seconds
row_factory = sqlite3.Row
```

Keep Railway at one replica while SQLite is the live database. WAL improves concurrency between connections to one file; it does not make independent replicas safe.

## Tables

- `schema_migrations`
- `projects`
- `memories`
- `conversations`
- `messages`

Messages have an enforced foreign key to conversations.

## Migrations

```text
1 — initial_schema
2 — memory_lifecycle
```

The migration runner acquires `BEGIN IMMEDIATE`, applies missing migrations in order, records them, verifies required columns and constraints, rejects unknown newer schemas, and rolls back on failure.

Do not edit an already-applied migration. Add a new migration instead.

## Memory lifecycle

Migration 2 added:

```text
status
updated_at
replaces_memory_id
superseded_by_id
```

Existing rows were preserved and backfilled as active with `updated_at = created_at`.

Lifecycle rules:

- Active rows are the only rows in normal model context.
- Correction inserts a new active row and marks the prior row superseded atomically.
- Archive changes the latest active row to archived.
- Restore changes the latest archived row back to active.
- Correction links do not change during archive or restore.
- Superseded and archived rows remain protected from legacy hard deletion.

No migration 3 is required for the recoverable-forget branch because `archived` already exists in schema 2.

## Production persistence verification

Verified:

- Conversations and memories survive Railway rebuilds.
- Explicit memory saves survive rebuilds.
- Schema 2 deployed while preserving existing records.
- A corrected active memory survived another rebuild.

This proves normal deployment persistence. It does not protect against volume loss, account loss, corruption, or accidental destructive operations.

## Backup status

One manual pre-migration safety checkpoint was completed on August 1, 2026:

- WAL-safe online SQLite snapshot
- Private off-volume copy
- Matching SHA-256
- `PRAGMA integrity_check = ok`
- Isolated application restore drill
- Known conversation and memory reads

See:

- [`MANUAL_BACKUP_AND_RESTORE.md`](MANUAL_BACKUP_AND_RESTORE.md)
- [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md)

Still missing:

- Automatic encrypted backups
- Retention rules
- Scheduled restore verification
- Point-in-time recovery
- Automated production restore

## Rollback rule

After schema 2, schema-1-only code must not be pointed at the production database. Roll back using schema-2-compatible code or an explicitly approved verified restore. Never edit `schema_migrations` to force compatibility.

## When to reconsider SQLite

Keep SQLite while MootOS remains single user, one replica, moderate write volume, and operational simplicity matters most.

Consider PostgreSQL when real requirements include multiple users, multiple replicas, high write concurrency, richer access controls, or managed point-in-time recovery.
