# MootOS Phone Deployment Checklist

This guide describes the current private Railway deployment shape for MootOS.

## Current production shape

As of August 8, 2026:

- repository: `mootmoot1/MootOS`
- deployment branch: `main`
- Railway runs one service and one replica
- start command uses `backend.application:app`
- Railway deployment health check uses `/ready`
- private login/session protection is enabled
- persistent Railway volume is mounted at `/data`
- normal production SQLite database is `/data/mootos.db`
- current supported schema is `4 — tasks`
- conversations, memories, profile imports, Runs, and Tasks share the same SQLite source of truth

The deployment does **not** currently include a background worker, scheduler service, Redis, external queue, or second replica.

## Repository deployment configuration

`railway.toml` currently runs:

```text
python -m uvicorn backend.application:app --host 0.0.0.0 --port $PORT
```

and uses:

```text
/ready
```

as the Railway health-check path.

`backend.application:app` composes the core FastAPI app with focused feature routers, including the bootstrap-profile and Task APIs plus current chat Task command routing.

## Required production configuration

Normal private production requires the configured model provider plus private auth values. Secrets belong in Railway variables and must never be committed to GitHub.

The Railway volume must remain attached. Production storage validation fails closed when the expected persistent volume is unavailable rather than silently creating a temporary repository-local database.

## Normal deployment procedure

1. Railway is connected to `mootmoot1/MootOS`.
2. Deploy from `main`.
3. Keep one replica while SQLite is the live database.
4. Keep the persistent volume attached at `/data`.
5. Do not expose secret values in screenshots, logs, commits, or review prompts.
6. Wait for `/ready` to pass after a deployment.
7. Verify private login.
8. Verify the normal chat interface.
9. For behavior-changing releases, run the feature-specific production smoke test.

## Readiness versus liveness

`/health` confirms that the web process is alive.

`/ready` verifies the configured existing database can be opened and matches the exact schema version supported by the running build. Railway uses `/ready` because a process that cannot safely use its persistent database should not be considered deployable.

## Schema migrations

Migrations run during application startup in order. Current sequence:

1. initial schema
2. memory lifecycle
3. model Runs
4. Tasks

Do not edit `schema_migrations` manually to make an old binary accept a newer database.

Before a future migration 5 (for example scheduler/reminder state), keep the normal safety process: reviewed migration, CI, backup/recovery awareness, one replica, controlled deploy, and production verification.

## Authentication boundary

Production uses one private password and a signed session secret. Current hardening includes a minimum signing-secret length, secure HTTP-only cookies on Railway, a process-global login cooldown, and private-response no-store/security headers.

Railway hard-delete for memories is disabled by default unless the explicit high-risk override is enabled.

## Persistent data and backup boundary

The `/data` Railway volume protects state across normal service rebuilds. It is not a complete disaster-recovery system.

A manual off-volume backup and isolated restore drill has been completed. Automated encrypted backup scheduling, retention, point-in-time recovery, and automatic restore verification are not implemented yet.

## Current feature smoke tests

After ordinary deployments, verify at least:

- `/ready` returns ready
- private login succeeds
- chat opens
- an existing conversation can be reopened
- existing memory remains available

After specific feature changes, use their targeted tests. For example, PR #29 was production-verified by correcting a test memory and confirming a brand-new chat recalled only the replacement.

## Scheduler note

The next proposed Scheduler / Reminder feature may require either a loop in the current service or a separate Railway process/service. That decision has **not** been made yet. Do not create a second service, cron process, or worker merely because a Task has `due_at`; the scheduler design must first define durable claiming, duplicate prevention, restart recovery, and delivery semantics.
