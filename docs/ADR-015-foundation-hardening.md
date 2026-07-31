# ADR-015 — Central SQLite Hardening and Versioned Migrations

**Status:** Proposed  
**Date:** July 31, 2026

## Context

MootOS Version 0.1 already stores projects, memories, conversations, and messages in one SQLite database. Production persistence was verified through a Railway volume mounted at `/data`.

Before this decision, database behavior was spread across `backend/memory.py` and `backend/conversation.py`. Each module opened SQLite independently. The schema was created with `CREATE TABLE IF NOT EXISTS`, but the database did not record which schema version had been applied.

The existing schema declared a foreign key from messages to conversations, but SQLite foreign-key enforcement was not enabled on every connection. Write-ahead logging, a deliberate busy timeout, and synchronous mode were also not configured consistently.

Railway authentication previously failed when only one auth variable was present, but a Railway deployment with both auth variables missing could start publicly. That behavior was acceptable for local development but unsafe as a production default.

## Decision

MootOS will use one central database layer in `backend/db.py`.

Every application database connection will enable:

- `PRAGMA foreign_keys = ON`
- `PRAGMA journal_mode = WAL`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA busy_timeout = 5000`
- A matching five-second SQLite connection timeout
- `sqlite3.Row` result objects
- Explicit commit, rollback, and close behavior through a context manager

MootOS will use a lightweight ordered migration runner in `backend/migrations.py`.

The migration system will:

- Record applied versions in `schema_migrations`
- Apply migrations in strict numeric order
- Serialize startup migration work with `BEGIN IMMEDIATE`
- Preserve an existing Version 0.1 database while adopting it as schema version 1
- Verify required tables, columns, and the message-to-conversation foreign key before recording migration success
- Roll back rather than falsely adopting an incompatible existing schema
- Refuse to start an older MootOS build against a database with a newer unknown schema
- Run automatically during application startup

Railway deployments will fail closed when both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are absent.

A public Railway deployment is allowed only when the operator explicitly sets:

```text
MOOTOS_ALLOW_PUBLIC=true
```

Local development may continue without authentication when Railway metadata is absent and both auth variables are absent.

Direct production and development dependencies, including CI lint tooling, will be pinned to exact versions tested by GitHub Actions.

## Why this decision

The goal is not to make SQLite pretend to be a distributed database. The goal is to make the current single-user, one-replica database predictable and harder to corrupt or misconfigure.

Central connection rules prevent different modules from silently using different safety settings.

Versioned migrations create a permanent record of schema evolution and make future upgrades testable.

Schema verification prevents a partially compatible or manually altered database from being marked migrated merely because its table names exist.

Fail-closed Railway authentication prevents an accidental missing-variable deployment from exposing the private application.

Pinned direct dependencies make rebuilds more repeatable and reduce surprise changes from newly released package versions.

## Consequences

### Positive

- Foreign keys are actually enforced.
- Readers and writers can coexist more safely under WAL mode.
- Temporary write contention waits for a defined period instead of failing immediately.
- Every connection commits, rolls back, and closes consistently.
- Existing production data is adopted without deletion or table replacement.
- Incompatible existing schemas fail safely instead of being falsely recorded as current.
- Future schema changes have a numbered path.
- An older application build cannot silently use a newer unknown schema.
- Railway is private by default.
- Dependency installs are reproducible at the direct-dependency level.

### Tradeoffs

- Startup now performs migration and schema-compatibility checks.
- WAL may create `mootos.db-wal` and `mootos.db-shm` beside the main database while the application is active.
- WAL and busy timeout improve concurrency but do not make multiple Railway replicas safe.
- Exact dependency pins require deliberate update PRs.
- `MOOTOS_ALLOW_PUBLIC=true` becomes a high-risk setting and must be used intentionally.

## Alternatives considered

### Keep `CREATE TABLE IF NOT EXISTS` without versions

Rejected because it cannot reliably describe or test future schema changes.

### Trust table names without validating their structure

Rejected because a partially created or manually changed table could be recorded as successfully migrated even when required columns or relationships were missing.

### Add Alembic immediately

Deferred. Alembic is capable, but a small ordered Python migration runner is easier to understand for the current project size. Alembic can be reconsidered if migration complexity grows.

### Move immediately to PostgreSQL

Rejected for Version 0.1. MootOS is still single-user and one-replica. A database-server migration would add operational complexity without solving a current requirement.

### Dual-write SQLite and another database

Rejected. It would create two competing sources of truth and difficult partial-failure recovery.

### Permit Railway to run publicly when auth variables are absent

Rejected as an unsafe production default. Public access now requires an explicit override.

## Verification

This decision is covered by automated tests for:

- SQLite connection PRAGMAs
- Clean database initialization
- Adoption of an existing schema without losing data
- Rejection of an incompatible existing schema without migration-history success
- Idempotent migration execution
- Rejection of a newer unknown schema
- Foreign-key enforcement
- Concurrent writes
- Railway auth fail-closed behavior
- Explicit public override behavior

Production verification after merge must confirm:

- Railway starts successfully with the existing auth variables.
- Existing conversations and memories remain available.
- New conversations and memories can be created.
- Data remains after a redeploy.

## Follow-up

This ADR does not add automatic backups, restore automation, multiple replicas, PostgreSQL, memory commands, or UI features. Those remain separate work.
