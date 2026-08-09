# MootOS Operations Runbook

**Last reviewed:** August 8, 2026  
**Environment:** Railway production deployment  
**Application model:** One FastAPI service, one process, one replica, one attached SQLite volume  
**Production entrypoint:** `backend.application:app`  
**Current schema:** `4 — tasks`

This is a **current operational document**. Historical deployment records and old ADRs may describe earlier schemas or entrypoints; use this runbook for the live post-PR-30 operating shape.

A V0.2A Tool Foundation (schema `5 — tool_system`, `docs/TOOL_SYSTEM.md`, ADR-027) exists on branch `claude/motos-v0.2a-tool-foundation-u46ew4` and is **not deployed to production**. When it merges, `4 — tasks` above becomes `5 — tool_system`; the deployment/rollback/readiness procedures below are unchanged by that migration (it is additive: new nullable `runs` columns and one new `tool_operations` table, no destructive changes to existing rows).

## 1. Production components

- GitHub repository: `mootmoot1/MootOS`
- Deployment branch: `main`
- Railway service: MootOS
- Railway volume: `mootos-volume`
- Volume mount: `/data`
- Production database: `/data/mootos.db`
- Current schema version: `4 — tasks`
- Public liveness endpoint: `/health`
- Public deployment-readiness endpoint: `/ready`
- Private chat interface: `/chat`
- Private memory interface: `/memory`
- Private profile interface: `/profile`
- Login interface: `/login`
- One Railway replica

Railway launches the composed application with:

```text
python -m uvicorn backend.application:app --host 0.0.0.0 --port $PORT
```

`railway.toml` uses `/ready` as the deployment health check. `/health` is process liveness only; it is not a substitute for database/schema readiness.

## 2. Current durable schema

Migrations are ordered and applied at startup:

1. `initial_schema`
2. `memory_lifecycle`
3. `model_runs`
4. `tasks`

Durable tables/domains include:

- `schema_migrations`
- `projects`
- `memories`
- `conversations`
- `messages`
- `runs`
- `tasks`

Do not edit `schema_migrations` manually to force compatibility.

## 3. Required private variables

Normal private production requires:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<secret>
OPENAI_MODEL=<configured model>
MOOTOS_PASSWORD=<secret>
MOOTOS_SESSION_SECRET=<long random secret of at least 32 characters>
```

Railway supplies deployment metadata such as:

```text
PORT
RAILWAY_ENVIRONMENT
RAILWAY_PUBLIC_DOMAIN
RAILWAY_VOLUME_MOUNT_PATH
```

Normal Railway production should not enable:

```text
MOOTOS_ALLOW_PUBLIC=true
MOOTOS_ALLOW_UNSAFE_DATABASE_PATH=true
MOOTOS_ALLOW_HARD_DELETE=true
```

Those are deliberate high-risk overrides for specific recovery/development cases, not normal production settings.

## 4. Normal release process

1. Create one focused branch.
2. Make the intended change.
3. Add or update tests.
4. Update current documentation when behavior or architecture changes.
5. Open a draft PR.
6. Review the diff and plain-language risk.
7. Wait for exact-head GitHub Actions.
8. Use independent read-only review for meaningful behavior changes.
9. Moot explicitly approves the merge.
10. Merge into `main`.
11. Railway deploys from `main`.
12. Confirm `/ready` succeeds.
13. Confirm `/health` succeeds.
14. Log in and manually test the changed behavior.
15. For schema/storage work, verify existing and new data.

A green `/ready` proves the running code can open the configured database and recognizes the current schema. It does not prove every user-facing feature works.

## 5. Post-deployment smoke test

1. Open the Railway domain.
2. Confirm the login page appears.
3. Confirm an incorrect password is rejected.
4. Log in successfully.
5. Confirm older conversations load.
6. Confirm saved active memories remain available.
7. Send a short normal chat message and receive an assistant response.
8. Refresh/reopen the conversation and confirm the turn persisted.
9. Confirm `/memory` opens.
10. If the release touched profile support, confirm `/profile` opens.
11. If the release touched Tasks, exercise the intended Task API/chat behavior with disposable data.
12. Log out and confirm protected routes require authentication.

## 6. Current behavior boundaries

MootOS currently has:

- normal OpenAI-backed chat through a replaceable provider boundary
- atomic successful normal chat persistence
- persistent conversations and projects
- long-term memory save/retrieval/lifecycle controls
- reviewed bootstrap-profile preview/import
- structured model Run logging
- Task create/list/get/complete/cancel
- explicit chat-driven Task creation

MootOS currently does **not** have:

- a background scheduler
- reminder delivery
- recurring reminders/tasks
- conditional trigger execution
- Redis/Celery or a distributed queue
- a separate worker
- external write-capable tools
- approval execution workflows
- multiple application replicas

An optional Task `due_at` value is stored scheduling metadata only. It does not cause anything to fire automatically.

## 7. Readiness and liveness

### `/health`

Expected success shape:

```json
{
  "status": "healthy"
}
```

This is intentionally minimal process liveness.

### `/ready`

Railway uses `/ready` for deployment readiness. Readiness verifies the configured production database can be opened without silently creating a replacement and that the schema matches the version supported by the running application.

A readiness failure should return a generic error and must not expose secrets, database paths, private content, schema details, or provider configuration to unauthenticated callers.

## 8. Startup failures

### Railway says auth variables are required

MootOS detected Railway but normal private auth configuration is missing.

Response:

1. Confirm both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` exist on the correct service.
2. Confirm the session secret meets the current minimum length.
3. Restore the correct values.
4. Redeploy.
5. Do not use `MOOTOS_ALLOW_PUBLIC=true` as a shortcut.

### Database storage validation fails

Normal Railway production requires the attached volume. MootOS should fail closed instead of silently falling back to a repository-local database.

Response:

1. Confirm `mootos-volume` still exists.
2. Confirm it is attached to the correct service at `/data`.
3. Confirm `RAILWAY_VOLUME_MOUNT_PATH` resolves to an existing directory.
4. Confirm no unsafe database-path override was added accidentally.
5. Do not create significant new data until the active database is understood.

### Database schema is newer than this MootOS build

1. Stop rollback attempts.
2. Identify which application version created the newer schema.
3. Deploy schema-compatible or newer code.
4. Do not edit `schema_migrations` manually.
5. Treat database restoration as a separate high-risk operation.

### Database migration fails

1. Check the first migration error in Railway logs.
2. Keep the production volume attached.
3. Do not delete the database or migration table.
4. Determine whether the migration transaction rolled back.
5. Prepare a focused fix or verified restore plan.
6. Verify data before reopening normal use.

## 9. SQLite operational notes

Every application connection uses the shared policy including:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = NORMAL
busy_timeout = 5000 milliseconds
```

WAL may create:

```text
mootos.db-wal
mootos.db-shm
```

Do not delete those files while the application is running.

Keep production at one Railway replica. WAL improves SQLite concurrency for the current architecture; it does not provide multi-replica coordination.

## 10. Persistence verification

Use after storage, migration, volume, or deployment changes:

1. Create disposable recognizable data appropriate to the changed subsystem.
2. Confirm it exists.
3. Redeploy/rebuild.
4. Wait for `/ready` and `/health`.
5. Log in.
6. Confirm the test data remains.
7. Confirm older data remains too.

For memory lifecycle work, verify active/superseded/archived behavior rather than only row existence. For Tasks, verify lifecycle state and project/due-time normalization. For Runs, verify expected audit rows without relying on private prompt/response duplication.

## 11. Common incidents

### Application does not build

Check dependency installation, Python compatibility, syntax/import errors, GitHub Actions, and changed file paths. Do not repeatedly deploy the same failing commit.

### Application builds but never becomes ready

Check:

- `railway.toml`
- `PORT`
- `backend.application:app` import/composition
- auth startup validation
- volume attachment
- storage-path validation
- migration errors
- database permissions
- schema compatibility

Expected production start command:

```text
python -m uvicorn backend.application:app --host 0.0.0.0 --port $PORT
```

### Login fails

Check both private auth variables, the current browser domain, and whether the process-global login cooldown is active after repeated failures. Rotating `MOOTOS_SESSION_SECRET` intentionally invalidates existing signed sessions.

### OpenAI-backed chat fails

Check `AI_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_MODEL`, provider billing/availability, Railway network access, and sanitized application logs. Never expose provider keys or private model input while troubleshooting.

### Old data appears missing

Treat this as a storage incident. Confirm the volume, mount path, service attachment, database resolution, and unsafe override variables before creating more production data.

### Reads work but writes fail

Check Railway logs for SQLite errors, available volume space, file permissions, repeated busy-timeout failures, unexpected processes, and whether the error is actually provider-related rather than storage-related.

## 12. Rollback

Preferred code rollback:

1. Revert through a focused PR or select a known-good Railway deployment.
2. Confirm the selected code supports the current database schema.
3. Deploy.
4. Verify `/ready`, `/health`, login, chat, and persistence.

Do not roll back by deleting the database, detaching the volume, or rewriting migration history.

Code rollback and data rollback are separate operations.

## 13. Volume safety

Never casually:

- delete `mootos-volume`
- detach or replace it
- change its mount path
- mount an empty replacement at `/data`
- add an unrelated database-path override
- scale above one application replica
- delete WAL/SHM files while running
- edit `schema_migrations`

Before destructive storage changes, create a verified backup, record the current schema, define rollback, test separately, and get explicit approval.

## 14. Backup and restore status

Current state:

- normal redeployment persistence has been verified
- a WAL-safe production snapshot was copied off-volume and hash-verified
- an isolated restore copy passed integrity/application-read checks
- automated encrypted backups are not implemented
- retention automation is not implemented
- recurring restore verification is not implemented
- automatic production restore and point-in-time recovery are not implemented

See `MANUAL_BACKUP_AND_RESTORE.md` and the dated backup/restore verification record.

## 15. Security incident response

If a secret may be exposed:

1. Revoke or rotate it immediately.
2. Update Railway variables.
3. Redeploy.
4. Review GitHub history/PRs and relevant provider/service logs.
5. Rotate related credentials when appropriate.

Examples:

- OpenAI key: revoke and replace.
- Session secret: replace to invalidate signed sessions.
- Login password: replace; consider also rotating the session secret.

## 16. Before declaring an incident resolved

Confirm:

- Railway is online
- `/ready` succeeds
- `/health` succeeds
- login works
- unauthenticated private APIs are blocked
- normal chat works
- existing conversations and memories remain
- new writes work
- the volume is attached at `/data`
- schema 4 is supported by the deployed build
- no secrets were committed
- the resolution is documented

## 17. Escalation rule

Stop and investigate when:

- the active source of truth is uncertain
- two database files may exist
- a migration may have partially failed
- the schema is newer than the code
- a volume was deleted or replaced
- secrets may be exposed
- data appears corrupted
- rollback could destroy newer data

Avoid irreversible recovery shortcuts.

See `DATA_AND_PERSISTENCE.md`, `FOUNDATION_HARDENING.md`, `RAILWAY_STORAGE_AND_READINESS.md`, and `PRIVATE_HTTP_BOUNDARY.md` for deeper implementation details.