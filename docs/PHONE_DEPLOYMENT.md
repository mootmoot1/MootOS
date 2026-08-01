# MootOS Phone Deployment Checklist

This guide deploys MootOS as one private Railway service connected to GitHub and preserves SQLite data on an attached volume.

## Verified production status

As of July 31, 2026:

- MootOS is deployed from `main`.
- The Railway service is online.
- Private login works.
- The phone-friendly chat interface works.
- Railway volume `mootos-volume` is attached at `/data`.
- Production data is stored at `/data/mootos.db`.
- Saved conversations and memories survived three consecutive deployments.

Those checks verify normal deployment persistence. A manual off-volume backup and isolated restore drill were completed on August 1, 2026, but automatic backups, retention, and production disaster-recovery automation are not implemented.

## Repository requirements

The repository includes:

- `railway.toml` with the Uvicorn start command
- Public minimal `/health` endpoint
- Password login and signed sessions
- Railway auth that fails closed by default
- Automatic SQLite path selection for a volume
- Central SQLite connection settings
- Versioned schema migrations
- Web-app manifest for phone Home Screen installation
- Automated database, auth, and deployment tests

## Create the Railway service

1. Sign in to Railway and create a project.
2. Choose **Deploy from GitHub repo**.
3. Connect GitHub if asked.
4. Select `mootmoot1/MootOS`.
5. Set deployment branch to `main`.
6. Add private variables before relying on the public domain.

## Add private variables

Add these variables to the MootOS Railway service:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<your real OpenAI API key>
OPENAI_MODEL=gpt-5-mini
MOOTOS_PASSWORD=<a strong private password>
MOOTOS_SESSION_SECRET=<a long random secret unrelated to the password>
```

The session secret must be long, random, and different from the password.

Railway provides `PORT` automatically.

### Public-access warning

Do not add this to the normal private deployment:

```text
MOOTOS_ALLOW_PUBLIC=true
```

Without the private auth values, Railway startup now fails closed. The public override exists only for deliberately public deployments.

## Add persistent storage

1. Open the MootOS service.
2. Add a volume.
3. Name it clearly, such as:

```text
mootos-volume
```

4. Mount it at exactly:

```text
/data
```

5. Review staged changes.
6. Deploy.
7. Wait until the service reports online.

Railway supplies `RAILWAY_VOLUME_MOUNT_PATH`, and MootOS uses:

```text
/data/mootos.db
```

Keep **one replica** while SQLite is live.

## Database startup behavior

During startup MootOS:

1. Opens the database on the mounted volume.
2. Applies the central SQLite safety settings.
3. Checks `schema_migrations`.
4. Applies missing migrations in numeric order.
5. Refuses a newer unknown schema.
6. Starts FastAPI after migration success.

The first hardened deployment records:

```text
1 — initial_schema
```

It is designed to adopt the existing Version 0.1 database without deleting projects, memories, conversations, or messages.

## Initial deployment verification

1. Wait for `/health` to pass.
2. Generate a public Railway domain.
3. Open the domain.
4. Confirm it redirects to login.
5. Confirm an incorrect password is rejected.
6. Sign in.
7. Create a uniquely named test conversation.
8. Add a message containing the date and `persistence test`.
9. Confirm the conversation appears in history.
10. Redeploy.
11. Wait until online.
12. Sign in again.
13. Confirm the exact test content remains.
14. Repeat when first validating a new volume or migration system.

## Hardening-upgrade verification

After merging the foundation-hardening PR:

1. Confirm Railway starts with the existing private variables.
2. Open a conversation created before the upgrade.
3. Confirm its messages remain.
4. Confirm an older memory remains.
5. Create one new conversation or memory.
6. Redeploy once.
7. Confirm old and new data remain.

## Put MootOS on an iPhone Home Screen

1. Open the Railway domain in Safari.
2. Sign in.
3. Tap **Share**.
4. Tap **Add to Home Screen**.
5. Name it `MootOS` and add it.

The icon opens `/chat` in a standalone browser window.

## Normal development after deployment

1. Moot requests a focused change.
2. The coding agent reads the repository.
3. Work is prepared on a separate branch.
4. A draft PR is opened.
5. Tests are added or updated.
6. Documentation is updated in the same PR.
7. GitHub Actions runs.
8. Moot reviews the plain-language explanation.
9. Moot explicitly approves the merge.
10. Railway deploys merged `main`.
11. The changed behavior is manually verified.

No phone terminal commands are required for the normal workflow.

## Recovery notes

- Missing both auth values on Railway now causes startup failure instead of public access.
- If login fails, verify both `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET`.
- To invalidate all sessions, rotate `MOOTOS_SESSION_SECRET`.
- If OpenAI fails, verify key, model, and billing.
- If data disappears, stop and verify the `/data` volume before creating significant new data.
- Confirm `MOOTOS_DATABASE_PATH` is not overriding the volume.
- If the schema is newer than the application, deploy compatible code; do not edit migration history.
- Do not wipe, detach, replace, or remount the volume without a backup and rollback plan.
- Do not increase replicas while SQLite is live.
- Do not delete `mootos.db-wal` or `mootos.db-shm` while the service is running.

For incident response, read [`OPERATIONS_RUNBOOK.md`](OPERATIONS_RUNBOOK.md).

For database and migration rules, read:

- [`DATA_AND_PERSISTENCE.md`](DATA_AND_PERSISTENCE.md)
- [`FOUNDATION_HARDENING.md`](FOUNDATION_HARDENING.md)
