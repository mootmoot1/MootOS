# MootOS Phone Deployment Checklist

This guide deploys MootOS as one private Railway service connected to GitHub and preserves SQLite data on an attached volume.

## Verified production status

As of July 31, 2026:

- MootOS is deployed from `main`.
- The Railway service is online.
- Private login works.
- The phone-friendly chat interface works.
- The Railway volume `mootos-volume` is attached at `/data`.
- MootOS stores production data at `/data/mootos.db`.
- Saved conversations and memories survived three consecutive deployments.

These checks verify normal deployment persistence. Automatic backups and disaster-recovery restores are not implemented yet.

## Repository requirements

The repository includes:

- `railway.toml` with the FastAPI start command
- Public `/health` endpoint
- Password login and signed sessions
- Automatic SQLite path selection for an attached Railway volume
- Web-app manifest for adding MootOS to a phone Home Screen
- Automated authentication and deployment-configuration tests

## Create the Railway service

1. Sign in to Railway and create a project.
2. Choose **Deploy from GitHub repo**.
3. Connect GitHub if Railway asks.
4. Select `mootmoot1/MootOS`.
5. Set the deployment branch to `main`.
6. Add private variables before relying on the public domain.

## Add private variables

Add these service variables in Railway. Never paste their real values into GitHub.

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<your real OpenAI API key>
OPENAI_MODEL=gpt-5-mini
MOOTOS_PASSWORD=<a strong private password>
MOOTOS_SESSION_SECRET=<a long random secret unrelated to the password>
```

The session secret should be long, random, and different from the login password.

Railway automatically provides `PORT`, and `railway.toml` starts Uvicorn on that port.

## Add persistent storage

1. Open the MootOS service in Railway.
2. Add a volume.
3. Name it clearly, such as:

```text
mootos-volume
```

4. Set its mount path to exactly:

```text
/data
```

5. Review the staged Railway change.
6. Deploy the change.
7. Wait until the service reports online.

Railway supplies `RAILWAY_VOLUME_MOUNT_PATH` automatically. MootOS then stores its SQLite database at:

```text
/data/mootos.db
```

Keep the service at **one replica** while SQLite is in use.

## Initial deployment verification

1. Wait for the deployment to pass the `/health` check.
2. Generate a public Railway domain.
3. Open the domain.
4. Confirm it redirects to the MootOS login page.
5. Confirm an incorrect password is rejected.
6. Sign in with `MOOTOS_PASSWORD`.
7. Create a uniquely named test conversation.
8. Add a message containing the current date and `persistence test`.
9. Confirm the conversation appears in history.
10. Redeploy the service.
11. Wait until the service is online.
12. Sign in again.
13. Confirm the test conversation and message remain.
14. Repeat the redeploy test when first validating the volume.

## Put MootOS on an iPhone Home Screen

1. Open the Railway domain in Safari.
2. Sign in.
3. Tap Safari's **Share** button.
4. Tap **Add to Home Screen**.
5. Name it `MootOS` and add it.

The icon opens the `/chat` experience in a standalone browser window.

## Normal development after deployment

1. Moot requests a focused change.
2. ChatGPT or another coding agent reads the actual repository.
3. Work is prepared on a separate branch.
4. A draft pull request is opened.
5. GitHub Actions tests behavior-changing work.
6. Documentation is updated in the same PR when behavior changes.
7. Moot reviews the plain-language explanation.
8. Moot explicitly approves the merge.
9. The merge reaches `main`.
10. Railway automatically builds and deploys the updated branch.
11. The changed feature is manually verified in production.

No phone terminal commands are required for the normal workflow.

## Recovery notes

- If login stops working, verify or change `MOOTOS_PASSWORD` in Railway and redeploy.
- If all sessions must be invalidated, rotate `MOOTOS_SESSION_SECRET` and redeploy.
- If OpenAI requests fail, verify `OPENAI_API_KEY`, the configured model, and provider billing.
- If data disappears, stop and verify the volume is attached at `/data` before creating significant new production data.
- Check that `MOOTOS_DATABASE_PATH` is not overriding the volume path unexpectedly.
- Do not wipe, detach, replace, or remount the volume without a backup and rollback plan.
- Do not increase Railway replicas while SQLite is the live database.

For incident response and rollback, read [`OPERATIONS_RUNBOOK.md`](OPERATIONS_RUNBOOK.md).

For database design, backups, and migration rules, read [`DATA_AND_PERSISTENCE.md`](DATA_AND_PERSISTENCE.md).
