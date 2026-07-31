# MootOS Operations Runbook

**Environment:** Railway production deployment  
**Application model:** One FastAPI service, one replica, one attached SQLite volume

This runbook explains how to operate the live MootOS deployment without guessing.

## 1. Production components

The live system currently consists of:

- GitHub repository: `mootmoot1/MootOS`
- Deployment branch: `main`
- Railway service: MootOS
- Railway volume: `mootos-volume`
- Volume mount path: `/data`
- Production database: `/data/mootos.db`
- Public health endpoint: `/health`
- Private application interface: `/chat`
- Login interface: `/login`
- One Railway replica

Railway automatically deploys new commits merged into `main`.

## 2. Normal release process

1. Create one focused branch.
2. Make and test the intended changes.
3. Update documentation when behavior changes.
4. Open a draft pull request.
5. Review the plain-language summary.
6. Wait for GitHub Actions.
7. Moot explicitly approves the merge.
8. Merge into `main`.
9. Railway starts a new build automatically.
10. Wait until Railway reports the service online.
11. Open `/health` and confirm a successful response.
12. Log in and manually verify the changed feature.
13. For storage-related changes, verify old conversations and memories remain available.

A green Railway deployment only proves that the service started and passed its health check. It does not prove every user-facing feature works.

## 3. Expected health response

`GET /health` should return:

```json
{
  "status": "healthy"
}
```

The health endpoint is intentionally minimal and public.

Do not add secrets, database paths, memory contents, environment-variable values, or account details to the public health response.

## 4. Post-deployment smoke test

After a normal deployment:

1. Open the Railway domain.
2. Confirm the site redirects to the login page when not authenticated.
3. Confirm an incorrect password is rejected.
4. Log in with the private password.
5. Open the conversation list.
6. Confirm older conversations are visible.
7. Open one old conversation and confirm its messages load.
8. Send a short test message.
9. Confirm an assistant response is returned.
10. Refresh the page and confirm the conversation remains.
11. Log out and confirm protected routes require login again.

## 5. Persistence verification

Use this test after changing the volume, database path, deployment service, or storage code.

1. Create a conversation with a unique title or message.
2. Include the date and the phrase `persistence test`.
3. Confirm it is visible before deployment.
4. Redeploy the service.
5. Wait until Railway reports the service online.
6. Log in again.
7. Reopen the same conversation.
8. Confirm the exact test message remains.
9. Repeat across more than one deployment when validating a new volume.

On July 31, 2026, production data survived three consecutive deployments with the `/data` volume attached.

## 6. Railway variables

Expected application variables:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5-mini
MOOTOS_PASSWORD=<secret>
MOOTOS_SESSION_SECRET=<long random secret>
```

Railway-supplied values include:

```text
PORT
RAILWAY_ENVIRONMENT
RAILWAY_PUBLIC_DOMAIN
RAILWAY_VOLUME_MOUNT_PATH
```

Never paste real values into GitHub, pull requests, screenshots intended for public sharing, documentation, or chat messages.

## 7. Common incidents

### Application does not build

Check:

- Railway build logs
- Python dependency installation errors
- Syntax or import errors
- Whether the latest commit changed file locations
- Whether GitHub Actions passed

Response:

- Do not keep redeploying the same broken commit.
- Identify the first meaningful error in the logs.
- Revert the merge or prepare a focused fix PR.

### Application builds but does not become healthy

Check:

- Start command from `railway.toml`
- Railway-provided `PORT`
- Startup exceptions
- Missing environment variables
- Authentication configuration mismatch
- Database path permissions
- Whether the volume is attached

Expected start command:

```text
python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

### Login page appears but password fails

Check:

- `MOOTOS_PASSWORD` is set on the correct Railway service
- No leading or trailing spaces were added
- The browser is using the current deployment domain

Response:

- Update the password variable if necessary.
- Redeploy.
- Do not place the password in GitHub.

### Existing sessions should be invalidated

Rotate:

```text
MOOTOS_SESSION_SECRET
```

Then redeploy.

Effect:

- Existing signed cookies become invalid.
- Users must log in again.

### OpenAI requests fail

Check:

- `AI_PROVIDER=openai`
- `OPENAI_API_KEY` exists and is valid
- The OpenAI account has usable billing or credits
- `OPENAI_MODEL` is available to the account
- Railway can reach the external API
- The error returned by `/chat`

Do not expose the API key while troubleshooting.

### Old conversations disappear

Treat this as a storage incident.

Immediately check:

- The Railway volume still exists
- The volume is attached to the MootOS service
- The mount path is exactly `/data`
- `RAILWAY_VOLUME_MOUNT_PATH` is present
- `MOOTOS_DATABASE_PATH` is not overriding the production path unexpectedly
- The service was not duplicated without the volume

Do not create large amounts of new production data until the active database path is understood. New writes could create a second database and make recovery more confusing.

### New messages fail but old data remains

Check:

- Railway logs for SQLite errors
- Available volume storage
- File permissions
- Provider errors
- Request validation errors

Remember that provider failure after the user message is stored may leave a user message without an assistant response in the current implementation.

## 8. Rollback

Use rollback when a newly merged change breaks production and a quick fix is not already proven.

Preferred options:

1. Revert the breaking commit through a pull request.
2. Redeploy the last known-good commit or deployment through Railway when appropriate.
3. Verify health, login, chat, and persistence after rollback.

Do not roll back by deleting the database or detaching the volume.

A code rollback and a data rollback are different operations. Never replace production data unless the restore source and consequences are understood.

## 9. Volume safety

Never casually:

- Delete `mootos-volume`
- Detach it from the service
- Change the mount path
- Mount another empty volume at `/data`
- Set an unrelated `MOOTOS_DATABASE_PATH`
- Scale the service to multiple replicas

Before a volume change:

- Create a backup
- Record the current mount path
- Record the current database path
- Define the rollback procedure
- Verify the replacement volume separately
- Receive explicit approval

## 10. Database backup and restore status

Current state:

- Normal deployment persistence is verified.
- Automatic backup is not implemented.
- Automatic restore is not implemented.
- Point-in-time recovery is not implemented.

A future backup feature must include both backup creation and restore testing. A backup that has never been restored is not fully verified.

## 11. Security incident response

If a secret may have been exposed:

1. Rotate the exposed secret immediately at the provider.
2. Update the Railway variable.
3. Redeploy.
4. Review GitHub history and pull requests for accidental commits.
5. Remove the exposed value from current files, while understanding that Git history may still contain it.
6. Review service logs and provider usage for abuse.
7. Rotate related secrets when necessary.

Examples:

- OpenAI key exposure: revoke and replace the key.
- Session-secret exposure: replace it and force all sessions to log in again.
- Password exposure: replace it and consider rotating the session secret too.

## 12. Before declaring an incident resolved

Confirm:

- Railway reports the service online
- `/health` succeeds
- Login works
- Protected APIs reject unauthenticated access
- Chat returns a real response
- Existing conversations remain
- Existing memories remain
- The volume is attached at `/data`
- No secrets were committed
- The resolution is documented in the relevant PR or checkpoint

## 13. Escalation rule

Stop making changes and investigate before proceeding when:

- The source of truth is uncertain
- Two different database files may exist
- A migration partially completed
- A volume was deleted or replaced
- Secrets may be exposed
- Production data appears corrupted
- A rollback could destroy newer data

Speed matters less than avoiding irreversible damage.
