# ADR-020 — Railway storage fail-closed validation and readiness

**Status:** Proposed  
**Date:** August 2, 2026

## Context

MootOS stores its production conversations and memories in SQLite on one Railway
volume. Before this decision, database-path resolution preferred an explicit
`MOOTOS_DATABASE_PATH`, then `RAILWAY_VOLUME_MOUNT_PATH`, and finally a
repository-local development path.

That fallback is useful on a developer machine, but unsafe on Railway. A missing
volume mount or accidental path override could allow the service to start against
a new temporary database. The process-level `/health` route would still report
success even though the intended production database was unavailable.

The system remains one FastAPI process, one Railway service and replica, and one
SQLite database. This hardening must not add a new database, migration, replica,
or external service.

## Decision

MootOS will validate production storage before migrations run.

On Railway:

- Normal production requires `RAILWAY_VOLUME_MOUNT_PATH`.
- The mount path must be absolute and exist as a directory.
- Without an explicit database override, the database remains
  `<mount>/mootos.db`.
- `MOOTOS_DATABASE_PATH` is rejected by default.
- A deliberately unsafe Railway database override requires both an absolute
  `MOOTOS_DATABASE_PATH` and `MOOTOS_ALLOW_UNSAFE_DATABASE_PATH=true`.
- Failure produces a clear startup error instead of creating a temporary local
  database.

Outside Railway, the existing local-development behavior remains available.

MootOS also separates liveness from readiness:

- `/health` proves the FastAPI process is alive.
- `/ready` opens the existing configured database in read-write mode without
  creating it, performs a small query, and requires the exact schema version
  supported by the running code.
- Railway uses `/ready` as its deployment health check.
- Public readiness responses reveal no database path, record count, schema name,
  provider configuration, secret, or private content.

## Why readiness does not run migrations

Startup owns configuration validation and migrations. Readiness must not repair,
create, or modify storage. A failed readiness response should stop traffic and
prompt investigation rather than hide a missing database by creating another one.

## Consequences

Positive:

- Missing or unavailable Railway storage fails closed.
- Accidental production database overrides require a separate explicit opt-in.
- Railway no longer treats process liveness as proof that persistent data is ready.
- Local development remains simple.
- No schema change or data rewrite occurs.

Tradeoffs:

- A legitimate deployment with incorrect volume metadata will refuse to start.
- The high-risk override remains possible for controlled recovery or isolated
  testing, so operators must treat it as exceptional.
- Readiness proves database and schema availability, not complete application or
  provider correctness.

## Rejected alternatives

### Keep documentation-only warnings

Rejected because the existing runbook already warns about wrong database paths,
but code still allowed the unsafe startup path.

### Make `/health` perform every readiness check

Rejected because liveness and readiness answer different operational questions.
Keeping both makes failure diagnosis clearer.

### Add PostgreSQL or a second storage service

Rejected as unnecessary for the current single-user, one-replica Version 0.1
system.

## Verification requirements

Automated tests must prove:

- Local database overrides still work outside Railway.
- Railway refuses startup without a volume.
- Railway refuses an unavailable mount.
- Railway rejects `MOOTOS_DATABASE_PATH` without the high-risk override.
- The high-risk override requires an absolute path.
- Readiness does not create a missing database.
- Readiness accepts the exact latest schema and rejects an unsupported version.
- `/ready` remains public for Railway but returns only generic failure details.
- `railway.toml` points deployment health checks to `/ready`.
