# MootOS Foundation Hardening

**Applies to:** Version 0.1 foundation hardening  
**Related decision:** `ADR-015-foundation-hardening.md`

This document explains the database and production-safety behavior introduced by the foundation-hardening change.

## What changed

MootOS now has one central SQLite layer:

```text
backend/db.py
```

Project, memory, conversation, and message storage all use that layer.

The central layer applies the same configuration to every connection:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000 milliseconds
```

Connections are committed or rolled back and then closed through one context manager.

Schema creation moved into a numbered migration system:

```text
backend/migrations.py
```

The current schema version is:

```text
1 — initial_schema
```

Applied versions are recorded in:

```text
schema_migrations
```

## Existing production database behavior

The first hardened deployment does not replace the Railway database.

At startup, MootOS:

1. Opens the existing `/data/mootos.db` file.
2. Creates `schema_migrations` inside the migration transaction if it does not exist.
3. Runs migration 1 using `CREATE TABLE IF NOT EXISTS`.
4. Verifies the required tables, columns, and message-to-conversation foreign key.
5. Keeps existing projects, memories, conversations, and messages.
6. Records schema version 1 only after compatibility verification succeeds.
7. Starts the application normally.

The migration does not drop tables, rename columns, or delete records.

If an existing table has an incompatible shape, startup fails and the migration transaction rolls back instead of falsely recording success.

## Startup serialization

Migrations run inside:

```sql
BEGIN IMMEDIATE
```

This prevents two startup processes from applying schema changes at the same time.

MootOS still remains a one-replica Railway service while SQLite is the live database.

## Schema compatibility verification

Migration history is not trusted by itself. During startup, MootOS verifies that the current database contains the required columns for:

- `projects`
- `memories`
- `conversations`
- `messages`
- `schema_migrations`

It also verifies that `messages.conversation_id` references `conversations.id`.

This protects against partially created, manually altered, or otherwise incompatible databases being marked as healthy merely because their table names exist.

## Newer-schema protection

MootOS refuses to start when the database reports a schema version newer than the application understands.

Example:

```text
database schema: 3
application supports: 2
```

Starting anyway could cause an older build to damage or misunderstand newer data. The safe response is to deploy the matching or newer application version instead of forcing startup.

## SQLite safety settings

### Foreign keys

SQLite requires foreign-key enforcement to be enabled per connection. MootOS now enables it every time.

This prevents a message from being inserted for a conversation that does not exist.

### WAL mode

Write-ahead logging allows readers to continue while another connection is writing. It also reduces some forms of writer-reader blocking.

WAL may create these files while the database is active:

```text
mootos.db
mootos.db-wal
mootos.db-shm
```

Do not delete the WAL or shared-memory file while the application is running.

### Busy timeout

MootOS waits up to five seconds when SQLite is temporarily busy.

This reduces immediate `database is locked` failures during short write contention. It does not guarantee that every long-running lock will succeed.

### Synchronous mode

`NORMAL` synchronous mode is used with WAL. It provides a practical reliability and performance balance for the current single-user service.

## Authentication hardening

Railway now requires both:

```text
MOOTOS_PASSWORD
MOOTOS_SESSION_SECRET
```

When Railway metadata is present and both values are absent, MootOS refuses to start.

This prevents an accidental environment-variable deletion from turning the private deployment into a public application.

A public Railway deployment must be explicitly approved with:

```text
MOOTOS_ALLOW_PUBLIC=true
```

That override should not be set for the normal private MootOS deployment.

Local development may continue without authentication when Railway metadata is absent and both auth values are absent.

## Dependency pins

Direct production and development dependencies are pinned to exact versions, including the lint tool used by GitHub Actions.

This makes future Railway and GitHub Actions installs more repeatable. Dependency updates should use a focused PR, run the complete test suite, and document any compatibility change.

## Automated verification

The hardening tests cover:

- Required SQLite PRAGMAs
- Clean database creation
- Existing database adoption without data loss
- Rejection of an incompatible existing schema without recording migration success
- Repeated migration safety
- Refusal of a newer unknown schema
- Foreign-key enforcement
- Concurrent writes
- Railway auth fail-closed behavior
- Explicit public override behavior

## Production verification after merge

After Railway deploys the merge:

1. Wait until the service is online.
2. Open the normal Railway domain.
3. Confirm the login page appears.
4. Log in.
5. Open at least one older conversation.
6. Confirm its messages are present.
7. Confirm saved memories are present.
8. Send one new message.
9. Create or use one new memory.
10. Redeploy once.
11. Confirm old and new data remain.

## Rollback warning

After a migration has changed the schema, code rollback and data rollback are separate decisions.

Migration 1 only adopts the existing schema and adds the migration-history table, so rollback risk is low. Future migrations may not be reversible by simply deploying older code.

Before every future schema migration:

- Create a verified backup.
- Define upgrade behavior.
- Define rollback behavior.
- Test from the previous real schema version.
- Test a clean install.
- Keep one source of truth.

## Still not included

This hardening work does not provide:

- Automatic database backups
- Encrypted off-volume backups
- Restore automation
- Point-in-time recovery
- Multiple Railway replicas
- PostgreSQL
- Natural-language memory commands
- Memory correction UI

Those remain separate focused changes.
