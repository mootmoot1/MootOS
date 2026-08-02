# Railway Storage and Readiness

## Purpose

MootOS production data must live on the attached Railway volume. This guardrail
prevents the service from appearing healthy while accidentally using a temporary
or second empty SQLite database.

This behavior applies to Railway production after the related hardening PR is
merged. It does not change the database schema or move existing data.

## Normal production configuration

Railway supplies the volume mount variable when the volume is attached:

```text
RAILWAY_VOLUME_MOUNT_PATH=/data
```

MootOS then resolves the production database to:

```text
/data/mootos.db
```

Normal Railway production should not set:

```text
MOOTOS_DATABASE_PATH
MOOTOS_ALLOW_UNSAFE_DATABASE_PATH=true
```

## Startup validation

Before migrations run, MootOS verifies that:

- Railway metadata is present.
- A volume mount path is configured.
- The mount path is absolute.
- The mount directory actually exists.
- Normal database resolution remains inside that mount.
- An explicit database path is not silently overriding the volume.

When one of those checks fails, startup stops with an explanatory error. MootOS
does not create a repository-local fallback database on Railway.

## High-risk override

A controlled recovery or isolated test may intentionally use an explicit Railway
database path. That requires both:

```text
MOOTOS_DATABASE_PATH=/absolute/path/to/database.db
MOOTOS_ALLOW_UNSAFE_DATABASE_PATH=true
```

This bypasses the normal volume-path protection. Do not use it to make a broken
production deployment start. Confirm the source database, backup, rollback plan,
and exact path before enabling it. Remove the override after the controlled work.

## Liveness and readiness

### `/health`

Returns:

```json
{"status":"healthy"}
```

This proves only that the application process can answer HTTP requests.

### `/ready`

Returns:

```json
{"status":"ready"}
```

only when the existing configured SQLite file:

- exists
- opens read-write without being created
- accepts a basic query
- reports the exact schema version supported by the deployed code

On failure it returns HTTP `503` with a generic message. It never returns a path,
record count, schema details, private data, provider configuration, or secret.

Railway deployment health checks use `/ready`.

## Failure response

If a deployment refuses startup because the volume is missing or unavailable:

1. Do not enable the unsafe override merely to make the service start.
2. Confirm `mootos-volume` is attached to the correct service.
3. Confirm the mount is `/data`.
4. Confirm `RAILWAY_VOLUME_MOUNT_PATH` is present.
5. Confirm `MOOTOS_DATABASE_PATH` is absent for normal production.
6. Keep one replica.
7. Preserve the volume and existing backup files.
8. Redeploy only after the storage source of truth is understood.

If `/health` succeeds but `/ready` fails, treat it as a storage or schema incident,
not a provider or browser problem.

## Production verification after merge

1. Confirm Railway reaches online status using `/ready`.
2. Confirm the existing login still works.
3. Confirm older conversations and memories remain.
4. Confirm one new conversation can be written and reopened.
5. Confirm `/health` returns liveness and `/ready` returns readiness.
6. Rebuild once and confirm old and new data remain.
7. Do not test the failure path by detaching or replacing the live production
   volume. Use automated tests or an isolated service instead.
