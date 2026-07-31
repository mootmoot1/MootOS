# MootOS Operations Runbook

**Environment:** Railway production deployment  
**Application model:** One FastAPI service, one replica, one attached SQLite volume

This runbook explains how to operate the live MootOS deployment without guessing.

## 1. Production components

- GitHub repository: `mootmoot1/MootOS`
- Deployment branch: `main`
- Railway service: MootOS
- Railway volume: `mootos-volume`
- Volume mount: `/data`
- Production database: `/data/mootos.db`
- Current schema version: `1 — initial_schema`
- Public health endpoint: `/health`
- Private interface: `/chat`
- Login interface: `/login`
- One Railway replica

Railway automatically deploys commits merged into `main`.

## 2. Required private variables

Normal private production requires:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5-mini
MOOTOS_PASSWORD=<secret>
MOOTOS_SESSION_SECRET=<long random secret>
```

Railway supplies:

```text
PORT
RAILWAY_ENVIRONMENT
RAILWAY_PUBLIC_DOMAIN
RAILWAY_VOLUME_MOUNT_PATH
```

Do not set this for normal private production:

```text
MOOTOS_ALLOW_PUBLIC=true
```

That variable is an explicit high-risk override allowing Railway to start without password protection.

## 3. Normal release process

1. Create one focused branch.
2. Make the intended changes.
3. Add tests.
4. Update relevant documentation in the same PR.
5. Open a draft PR.
6. Review the plain-language summary and risk.
7. Wait for GitHub Actions.
8. Moot explicitly approves the merge.
9. Merge into `main`.
10. Railway builds automatically.
11. Wait until Railway reports online.
12. Confirm `/health`.
13. Log in and manually test the changed behavior.
14. For database work, verify old and new data.

A green health check proves startup, not complete user-facing correctness.

## 4. Expected health response

```json
{
  "status": "healthy"
}
```

The public health endpoint must not expose secrets, database paths, private data, provider configuration, or environment values.

## 5. Post-deployment smoke test

1. Open the Railway domain.
2. Confirm the login page appears.
3. Confirm an incorrect password is rejected.
4. Log in.
5. Confirm older conversations are listed.
6. Open an older conversation and confirm messages load.
7. Confirm saved memories remain.
8. Send a short message.
9. Confirm an assistant response returns.
10. Refresh and reopen the conversation.
11. Log out and confirm protected routes require login.

## 6. Hardening deployment verification

After merging the foundation-hardening PR:

1. Confirm Railway reaches online status.
2. Confirm the existing password still works.
3. Open at least one conversation created before hardening.
4. Confirm its messages remain.
5. Confirm at least one older memory remains.
6. Create one new conversation or memory.
7. Redeploy once.
8. Confirm old and new data remain.

The first hardened startup creates `schema_migrations` and records migration version 1. It does not intentionally drop or replace existing data.

## 7. Startup failures after hardening

### Railway says auth variables are required

Expected error meaning:

- Railway metadata was detected.
- Both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` were absent.
- MootOS refused to start publicly.

Response:

1. Confirm both variables exist on the correct Railway service.
2. Restore missing values.
3. Redeploy.
4. Do not bypass the protection with `MOOTOS_ALLOW_PUBLIC=true` unless a public deployment is deliberately intended.

### Auth variables must be configured together

Exactly one private auth variable is present.

Response:

- Configure both values, or remove both only in local non-Railway development.

### Database schema is newer than this MootOS build

The database migration version is higher than the deployed code understands.

Response:

1. Stop rollback attempts.
2. Identify the application version that created the newer schema.
3. Deploy a compatible or newer application build.
4. Do not edit `schema_migrations` to force startup.
5. Treat data rollback as a separate high-risk operation.

### Database migration fails

Check Railway logs for the first migration error.

Response:

1. Do not repeatedly restart without understanding the failure.
2. Keep the volume attached.
3. Do not delete the database or migration table.
4. Determine whether the transaction rolled back.
5. Prepare a focused fix or restore plan.
6. Verify data before reopening normal use.

## 8. SQLite operational notes

MootOS now uses:

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

A five-second busy timeout reduces short lock failures. Repeated `database is locked` errors still require investigation.

Keep one Railway replica. WAL does not make SQLite safe for multiple application replicas.

## 9. Persistence verification

Use after storage, migration, volume, or deployment changes:

1. Create a unique test conversation or memory.
2. Include the date and `persistence test`.
3. Confirm it exists.
4. Redeploy.
5. Wait for online status.
6. Log in.
7. Confirm the exact test data remains.
8. Confirm older data remains too.

Production data survived three deployments before hardening. Repeat verification after hardening is merged.

## 10. Common incidents

### Application does not build

Check:

- Dependency installation
- Python compatibility
- Syntax or import errors
- GitHub Actions
- Changed file paths

Do not repeatedly deploy the same failing commit. Revert or prepare a focused fix.

### Application builds but never becomes healthy

Check:

- Start command in `railway.toml`
- Railway `PORT`
- Auth startup validation
- Migration errors
- Database permissions
- Volume attachment
- Database schema compatibility

Expected start command:

```text
python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

### Login fails

Check:

- `MOOTOS_PASSWORD` is on the correct service
- `MOOTOS_SESSION_SECRET` is also present
- No accidental spaces were added
- The browser is using the current domain

To invalidate all sessions, rotate `MOOTOS_SESSION_SECRET` and redeploy.

### OpenAI requests fail

Check:

- `AI_PROVIDER=openai`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- Provider billing and availability
- Railway network access
- `/chat` error details

Never expose the key while troubleshooting.

### Old conversations disappear

Treat as a storage incident.

Immediately check:

- Volume still exists
- Volume is attached to MootOS
- Mount is exactly `/data`
- `RAILWAY_VOLUME_MOUNT_PATH` exists
- `MOOTOS_DATABASE_PATH` is not overriding the path
- Service was not duplicated without the volume

Avoid creating significant new data until the active database is understood. A second empty database can make recovery more confusing.

### New writes fail while reads work

Check:

- Railway logs for SQLite errors
- Available volume space
- File permissions
- Repeated lock timeouts
- Long-running requests or unexpected processes
- Provider errors versus database errors

## 11. Rollback

Preferred code rollback:

1. Revert the breaking commit through a PR, or select a known-good Railway deployment.
2. Confirm the selected code supports the current schema version.
3. Deploy.
4. Verify health, login, chat, and persistence.

Do not roll back by deleting the database, detaching the volume, or editing migration history.

Code rollback and data rollback are separate operations. A future migration may make older code incompatible.

## 12. Volume safety

Never casually:

- Delete `mootos-volume`
- Detach it
- Change the mount path
- Mount an empty volume at `/data`
- Set an unrelated `MOOTOS_DATABASE_PATH`
- Scale above one replica
- Delete WAL files while running
- Edit `schema_migrations`

Before volume or destructive database changes:

- Create a verified backup
- Record the current path and schema version
- Define rollback
- Test the replacement separately
- Receive explicit approval

## 13. Backup and restore status

Current state:

- Redeployment persistence is verified.
- Automatic backup is not implemented.
- Automatic restore is not implemented.
- Point-in-time recovery is not implemented.

A future backup feature must include restore testing. A backup that has never been restored is not fully verified.

## 14. Security incident response

If a secret may be exposed:

1. Revoke or rotate it immediately.
2. Update Railway.
3. Redeploy.
4. Review GitHub history and PRs.
5. Review provider and service logs.
6. Rotate related secrets when appropriate.

Examples:

- OpenAI key: revoke and replace.
- Session secret: replace to invalidate all cookies.
- Login password: replace, and consider rotating the session secret.

## 15. Before declaring resolution

Confirm:

- Railway is online
- `/health` succeeds
- Login works
- Unauthenticated APIs are blocked
- Chat returns a real response
- Existing conversations remain
- Existing memories remain
- New writes work
- Volume is attached at `/data`
- Schema version is supported
- No secrets were committed
- Resolution is documented

## 16. Escalation rule

Stop and investigate when:

- The source of truth is uncertain
- Two database files may exist
- A migration partially failed
- The schema is newer than the application
- A volume was deleted or replaced
- Secrets may be exposed
- Data appears corrupted
- Rollback could destroy newer data

Speed matters less than avoiding irreversible damage.

See [`FOUNDATION_HARDENING.md`](FOUNDATION_HARDENING.md) and [`DATA_AND_PERSISTENCE.md`](DATA_AND_PERSISTENCE.md).
