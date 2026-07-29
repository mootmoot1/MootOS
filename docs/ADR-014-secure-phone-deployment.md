# ADR-014: Secure Single-User Phone Deployment

- **Status:** Proposed
- **Date:** 2026-07-29
- **Decision owners:** Moot and MootOS

## Context

MootOS now has a working mobile chat interface, persistent conversations, projects, and memory. The Codespaces URL is useful for development, but the Codespace and FastAPI server must remain active. Moot needs a stable phone URL that continues working after leaving the studio and that can receive approved updates from GitHub.

Publishing the existing interface without protection would expose private conversations and memories and could allow strangers to spend money through Moot's OpenAI API key. SQLite data would also disappear on normal cloud redeployments unless it is placed on persistent storage.

## Decision

MootOS v0.1 will use a small single-user deployment boundary:

1. Railway is the first supported cloud host.
2. Railway builds the repository from GitHub and starts the existing FastAPI application.
3. The server listens on Railway's injected `PORT` value.
4. `GET /health` remains public for deployment health checks.
5. Every other application page and API is protected when `MOOTOS_PASSWORD` is configured.
6. A correct password creates a signed, HTTP-only browser session cookie.
7. The cookie is marked Secure automatically on Railway and uses SameSite=Lax.
8. `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are configured as Railway variables and are never committed.
9. Authentication is optional only in local development when both variables are absent.
10. SQLite uses `RAILWAY_VOLUME_MOUNT_PATH/mootos.db` when a Railway volume is attached.
11. A Railway volume should be mounted at `/data`.
12. The phone interface includes logout and web-app install metadata.
13. A merge into the Railway-connected `main` branch triggers a new deployment.

## Why this approach

This is the smallest secure path from a development Codespace to an everyday phone experience. It keeps MootOS as one Python service, does not add a separate identity provider, does not expose the OpenAI key to the browser, and preserves the local-first SQLite design through an attached volume.

The signed session uses standard-library HMAC rather than adding a new authentication framework. That is appropriate for one owner and one private password. A multi-user product would require a different identity design.

## Consequences

### Positive

- Moot can open MootOS from one stable phone URL.
- The Codespace no longer has to remain running.
- Conversations and memories survive deployments and service restarts.
- Anyone who finds the URL still needs the private password.
- Secrets remain in Railway variables instead of GitHub.
- Approved merges can automatically deploy.
- The interface can be added to the phone Home Screen.

### Negative

- Railway and OpenAI usage have separate costs.
- This is single-user password protection, not a full account system.
- Losing the password requires changing the Railway variable.
- Losing or wiping the Railway volume deletes locally stored MootOS data unless a backup exists.
- A single SQLite volume means the service should remain at one replica.
- Initial Railway project, variables, domain, and volume setup still require a few dashboard taps.

## Security boundaries

- Never put `OPENAI_API_KEY`, `MOOTOS_PASSWORD`, or `MOOTOS_SESSION_SECRET` in GitHub.
- Use a unique, strong MootOS password.
- Generate a long random session secret unrelated to the password.
- Keep the Railway service at one replica while SQLite is the database.
- Keep `/health` free of private data.
- Do not share the public Railway URL and password together.

## Rejected alternatives

### Keep Codespaces running permanently

Rejected because Codespaces is a development environment, stops when inactive, and still requires terminal access to recover the server.

### Publish the current interface without authentication

Rejected because it would expose private data and OpenAI usage to anyone with the link.

### Add a full OAuth or multi-user account system now

Rejected because MootOS v0.1 has one owner. A full identity platform would add substantial complexity before it is needed.

### Replace SQLite with a hosted database immediately

Rejected because the current system is working and a persistent volume is enough for the single-user v0.1 workload. Hosted database migration remains an option when multi-device synchronization or multiple replicas are required.

## Follow-up work

- Add database backup/export controls.
- Add rate limiting and basic usage visibility.
- Consider passkeys or an external identity provider before supporting more users.
- Revisit the database choice before horizontal scaling.
- Add natural memory controls after the phone deployment is stable.
