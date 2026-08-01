# MootOS Data and Persistence

**Applies to:** MootOS Version 0.1 with memory lifecycle migration 2 and the recoverable-forget branch

This document explains where MootOS stores data, how SQLite is configured, how schema migrations work, how memory lifecycle states persist, what the Railway volume protects, what is still not backed up, and when the database design should change.

## 1. Current database choice

MootOS uses SQLite.

For the current single-user, one-replica deployment, SQLite provides:

- Simple local development
- Low operational cost
- Fast reads and writes for a personal workload
- Easy portability to a future local computer
- One database file that can be backed up and restored
- A small dependency footprint

SQLite is used because it fits the present workload and local-first direction, not because it is the newest database.

## 2. What is stored

The SQLite database contains:

- Applied schema migration history
- Projects
- Long-term memories and lifecycle status
- Preserved memory-correction versions
- Conversations
- User messages
- Assistant messages
- Provider and model metadata for assistant messages

Source code, frontend assets, secrets, and Railway configuration are not stored in SQLite.

## 3. Database path selection

MootOS selects the database path in this order:

1. `MOOTOS_DATABASE_PATH`
2. `<RAILWAY_VOLUME_MOUNT_PATH>/mootos.db`
3. Repository-local `data/mootos.db`

The approved Railway volume mount is:

```text
/data
```

Production therefore uses:

```text
/data/mootos.db
```

## 4. Central connection policy

All application database access goes through `backend/db.py`.

Every connection enables:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA synchronous = NORMAL
PRAGMA busy_timeout = 5000
```

The SQLite connection timeout is also five seconds.

The shared context manager:

- Commits successful work
- Rolls back failed work
- Closes every connection

This avoids separate modules silently using different SQLite behavior.

## 5. What the SQLite settings mean

### Foreign-key enforcement

SQLite does not enforce foreign keys merely because they are declared in a table. Enforcement must be enabled per connection.

MootOS enables it every time. A message cannot be inserted for a nonexistent conversation through a correctly configured application connection.

Memory correction links are application-managed rather than SQLite foreign keys because migration 2 added them to an existing table through `ALTER TABLE`.

### WAL mode

Write-ahead logging allows readers to continue while another connection writes and reduces some reader-writer blocking.

Active WAL databases may have:

```text
mootos.db
mootos.db-wal
mootos.db-shm
```

Do not manually delete the WAL or shared-memory files while MootOS is running.

### Busy timeout

When the database is temporarily locked, MootOS waits up to five seconds before failing. This helps with short write contention but does not make long locks safe.

### Synchronous mode

`NORMAL` synchronous mode is used with WAL as a practical reliability and performance balance for the current service.

## 6. Versioned schema migrations

Schema initialization is handled by `backend/migrations.py`.

Applied migrations are stored in:

```text
schema_migrations
```

Current migrations:

```text
1 — initial_schema
2 — memory_lifecycle
```

The migration runner:

1. Opens a hardened SQLite connection.
2. Starts `BEGIN IMMEDIATE` to serialize migration work.
3. Creates `schema_migrations` when absent.
4. Reads the current version.
5. Refuses a version newer than the application understands.
6. Applies missing migrations in numeric order.
7. Records each applied migration.
8. Verifies required tables, columns, status values, and foreign keys.
9. Commits or rolls back as one startup operation.

The recoverable-forget branch reuses schema 2. It does not add migration 3.

## 7. Existing production database adoption

The first hardened deployment adopted the existing Railway database.

Migration 1 uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` for default projects. It does not drop tables, replace the database, or delete records.

The expected first hardened startup was:

```text
Existing /data/mootos.db
        |
        v
Create schema_migrations
        |
        v
Confirm current Version 0.1 tables
        |
        v
Record migration 1
        |
        v
Start MootOS
```

Automated tests verified adoption of an existing database while preserving saved data. Production deployment also preserved older conversations.

## 8. Memory lifecycle migration 2

Migration 2 altered the existing `memories` table in place. It added:

```text
status
updated_at
replaces_memory_id
superseded_by_id
```

Existing rows were preserved and backfilled as active:

```text
status = active
updated_at = created_at
replaces_memory_id = null
superseded_by_id = null
```

Two indexes support active-memory listing and correction-chain traversal.

Correction uses `BEGIN IMMEDIATE` so the selected row is rechecked under a serialized write transaction. The new active row and the old superseded row commit together or roll back together.

Migration 2 was covered by clean-install, schema-1 upgrade, data-preservation, rollback, history, concurrency, and active-context tests.

The pre-migration snapshot and isolated restore drill were completed before implementation. See [`BACKUP_RESTORE_VERIFICATION_2026-08-01.md`](BACKUP_RESTORE_VERIFICATION_2026-08-01.md).

Migration 2 was subsequently deployed to production. Existing data remained available, a selected memory was corrected through the UI, only the corrected active value was recalled, and the correction survived another Railway rebuild. See [`MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md`](MEMORY_CORRECTION_PRODUCTION_VERIFICATION_2026-08-01.md).

## 9. Memory lifecycle persistence

Memory rows use these lifecycle states:

```text
active
superseded
archived
```

### Active

Active rows are the only rows included in normal memory listings and model context.

### Superseded

A correction inserts a new active row and marks the selected prior row superseded. The two rows are linked through `replaces_memory_id` and `superseded_by_id`.

Superseded rows remain durable history. They are excluded from normal recall and available through direct retrieval and the correction-history API.

### Archived

The recoverable-forget branch changes one latest active row to archived after exact selection and confirmation.

An archived row:

- Remains in the same `memories` table
- Keeps the same ID, content, project, type, timestamps, and correction links
- Is excluded from active lists and model context
- Appears in `GET /memories?status=archived`
- Can return to active through the restore endpoint
- Cannot be hard-deleted through the legacy API

Forget is therefore recoverable archival, not secure erasure or permanent deletion.

## 10. Atomic archive and restore

### Archive

`archive_memory`:

1. Starts `BEGIN IMMEDIATE`.
2. Reloads the selected row.
3. Requires it to exist, remain active, and have no newer replacement.
4. Changes status to archived.
5. Updates `updated_at`.
6. Commits or rolls back.

### Restore

`restore_memory`:

1. Starts `BEGIN IMMEDIATE`.
2. Reloads the selected row.
3. Requires it to exist, remain archived, and have no newer replacement.
4. Changes status to active.
5. Updates `updated_at`.
6. Commits or rolls back.

Correction links do not change during archive or restore. A correction chain may end with either an active or archived latest version.

## 11. Normal recall boundary

Only active rows enter model instructions.

Current retrieval rules:

- A no-project conversation can load all active memories.
- A project conversation currently loads active global memory plus active memory assigned to that project.
- Archived and superseded rows are always excluded.
- At most twenty newest relevant active rows are supplied.

Projects are focus lenses, not permanent secrecy walls. Later keyword retrieval may rank relevant other-project memories without changing lifecycle filtering.

## 12. Newer-schema protection

An older MootOS build refuses to start against a database with a newer unknown migration version.

This prevents an accidental code rollback from silently using a schema it does not understand.

The correct response is to deploy a compatible application version or follow a documented data rollback. Do not edit `schema_migrations` merely to force startup.

Schema-1-only code must not be pointed at a schema-2 production database.

## 13. Verified production persistence

Verified production persistence includes:

- Railway volume `mootos-volume` attached at `/data`
- Conversations and memories surviving normal deployments
- Explicit memory saves surviving Railway rebuilds
- Migration 2 preserving existing records
- A corrected active memory surviving another rebuild

That verifies persistence across normal rebuilds. It does not prove protection from volume deletion, corruption, account loss, or every operational mistake.

Archive and restore still require production verification after PR #16 is reviewed, approved, merged, and deployed.

## 14. One-replica rule

Keep Railway at **one replica** while SQLite remains the live database.

WAL improves concurrency between connections using the same local database file. It does not make one SQLite file suitable for multiple Railway application replicas.

A move to multiple replicas requires a planned database architecture decision, likely including PostgreSQL.

## 15. Redundancy versus dual writing

MootOS should not write every record to SQLite and an unrelated second live database merely for redundancy.

Dual writing creates questions such as:

- Which write wins when one database fails?
- Which database is authoritative?
- How are partial writes repaired?
- How are conflicting IDs and timestamps reconciled?
- Which copy is safe to restore?

The current redundancy direction is:

```text
One live SQLite source of truth
        |
        v
Verified backup copies
        |
        v
Documented restore testing
```

## 16. Current backup status

The Railway volume protects against normal redeployments. One manual WAL-safe snapshot was downloaded off-volume, matched by SHA-256, and opened through an isolated application restore drill on August 1, 2026.

MootOS still does not implement:

- Automatic scheduled backups
- Encrypted off-platform backup storage
- Retention policies
- One-click restore
- Automated restore tests
- Point-in-time recovery

The volume is persistent storage, not a complete disaster-recovery system.

## 17. Safe backup direction

A future backup feature should:

1. Use SQLite's backup mechanism or another consistent snapshot method.
2. Store copies separately from the live volume.
3. Encrypt private data.
4. Record time, size, checksum, and schema version.
5. Keep multiple historical copies.
6. Test restore away from production.
7. Require explicit approval before replacing live data.

The August 1 manual backup was restored and read successfully in isolation. Future backups still require the same verification discipline.

## 18. Manual persistence verification

After database, migration, or deployment changes:

1. Log in.
2. Open an older conversation.
3. Confirm old messages are present.
4. Confirm saved active memories are present.
5. Complete the feature-specific lifecycle check.
6. Create or use a uniquely identifiable test fact when needed.
7. Redeploy.
8. Wait for Railway to return online.
9. Log in again.
10. Confirm both old and new state remain.

For PR #16, production verification must prove archive exclusion from recall, archived visibility, restoration, renewed recall, and persistence through a rebuild.

Do not detach or replace the existing volume because a new deployment merely appears healthy.

## 19. Migration development rules

Every future schema change must:

- Receive the next numeric migration version
- Be safe on a clean database
- Be tested from the previous schema version
- Preserve existing data unless deletion is explicitly approved
- Document backup and rollback behavior
- Update current implementation and persistence documentation
- Use a focused PR
- Receive Moot's explicit approval before merge

Do not silently edit an already-applied migration. Add a new migration instead.

No new migration is needed merely to use an already-defined lifecycle state.

## 20. When to keep SQLite

Keep SQLite while most of these remain true:

- Moot is the only user
- Railway uses one replica
- Writes are relatively low volume
- The workload is conversation and memory storage
- The database fits comfortably on one volume
- Local-first portability matters
- Simplicity matters more than horizontal scaling

## 21. When to consider PostgreSQL

Consider PostgreSQL when real requirements include:

- Multiple independent user accounts
- Multiple application replicas
- Many simultaneous writers
- Managed backups and point-in-time recovery
- Strong server-side access controls
- Commercial hosted use by many customers
- Complex reporting or relational workflows
- Central cross-device synchronization

The central database layer and migration history make a future planned migration easier, but they do not perform that migration automatically.

## 22. DynamoDB and MongoDB

DynamoDB and MongoDB are valid databases, but larger-scale or newer branding does not automatically make them a better fit.

### DynamoDB

Useful for AWS-centered systems designed around known access patterns and distributed scale. It introduces stronger cloud coupling and a different modeling approach.

### MongoDB

Useful for document-shaped data that varies heavily. MootOS currently has clear relationships among conversations, messages, projects, and memories.

### PostgreSQL

The most likely future hosted upgrade because it preserves relational modeling, constraints, transactions, and SQL while supporting multiple users and replicas.

## 23. Source of truth

The live SQLite database on the Railway volume is the production source of truth.

GitHub stores code and documentation, not production conversations or memories.

OpenAI generates responses but is not MootOS's history database. Provider-side response storage is disabled, and MootOS stores its own history.

## 24. Rules before storage changes

Before changing storage:

- Create a focused branch and PR
- Identify the source of truth
- Explain migration and rollback in plain language
- Protect the current production database
- Add upgrade and clean-install tests
- Verify a backup when the change is destructive or difficult to reverse
- Test restore separately
- Keep secrets out of GitHub
- Keep one replica while SQLite is live
- Receive Moot's explicit approval

See [`FOUNDATION_HARDENING.md`](FOUNDATION_HARDENING.md), [`ADR-015-foundation-hardening.md`](ADR-015-foundation-hardening.md), [`ADR-016-memory-lifecycle-and-correction.md`](ADR-016-memory-lifecycle-and-correction.md), and [`ADR-017-recoverable-memory-forget-and-restore.md`](ADR-017-recoverable-memory-forget-and-restore.md).
