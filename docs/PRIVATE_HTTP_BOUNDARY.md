# Private HTTP boundary

This document is the current operator and implementation truth for MootOS Version
0.1 authentication throttling, response headers, cache policy, and Railway permanent
delete controls.

## Current behavior

### Login cooldown

MootOS keeps one in-process failed-login budget for the entire running application.
It intentionally does not trust raw `X-Forwarded-For` values.

- Attempts 1 through 4 with a wrong password return `401 Incorrect password`.
- Attempt 5 starts a 60-second cooldown and returns `429`.
- Requests made during cooldown return `429` with `Retry-After`.
- The cooldown expires automatically; there is no permanent lockout.
- A successful login clears prior failures.

This boundary assumes the current production shape: one Railway service, one process,
and one replica. A later multi-replica deployment needs a shared limiter such as
Redis or a database-backed lease before claiming a deployment-wide budget.

### Session-secret requirement

Private authentication still requires both values together:

```text
MOOTOS_PASSWORD
MOOTOS_SESSION_SECRET
```

`MOOTOS_SESSION_SECRET` must be at least 32 characters. Use a long random value rather
than a phrase. Never put the value in chat, screenshots, logs, commits, or issue
comments.

Changing the session secret invalidates existing signed cookies. The owner will need
to log in again after the next deployment.

### Response headers

MootOS adds these headers to normal responses:

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
```

Dynamic/private HTML and JSON responses also receive:

```text
Cache-Control: no-store
```

The no-store rule excludes only:

- `/health`
- `/ready`
- `/manifest.webmanifest`
- `/static/*`

The login page, redirects, authentication responses, chat/memory pages, API JSON,
OpenAPI JSON, and protected error responses are no-store.

### Permanent memory deletion

The user-facing Memory page continues to use recoverable actions:

- `POST /memories/{id}/archive`
- `POST /memories/{id}/restore`

On Railway, `DELETE /memories/{id}` is disabled by default and returns `403` without
modifying storage. Normal production should leave this value false or unset:

```text
MOOTOS_ALLOW_HARD_DELETE=false
```

The only deliberate override is:

```text
MOOTOS_ALLOW_HARD_DELETE=true
```

That override is high risk. It should be temporary, documented, and removed after the
specific authorized maintenance action. It does not bypass existing correction-chain
protections.

Local development keeps hard delete available by default for compatibility and test
cleanup.

## Railway deployment preparation

Before merging or deploying this change:

1. Open Railway variables without exposing their values.
2. Confirm `MOOTOS_PASSWORD` is configured.
3. Confirm `MOOTOS_SESSION_SECRET` contains at least 32 characters.
4. If it is too short, replace it with a new long random value. Expect existing
   browser sessions to be signed out.
5. Confirm `MOOTOS_ALLOW_HARD_DELETE` is absent or exactly `false`.
6. Do not change `MOOTOS_ALLOW_PUBLIC`, database-path, or volume settings as part of
   this deployment.

A short session secret causes startup to fail closed. Railway should keep the prior
healthy deployment active until configuration is corrected or the release is rolled
back.

## Controlled production verification

After Railway reports the new deployment Active:

1. Verify `/ready` returns `{"status":"ready"}`.
2. Verify `/health` returns `{"status":"healthy"}`.
3. Confirm the login page loads and a correct password still opens MootOS.
4. In browser developer tools or a header viewer, confirm the login page and a
   private JSON route include `Cache-Control: no-store`, `nosniff`, `DENY`, and
   `same-origin`.
5. Confirm `/health` and `/ready` still work without authentication.
6. Use a disposable test memory and confirm archive then restore still work.
7. Do not enable the hard-delete override merely to test production deletion. Exact-
   head automated tests cover the disabled and override paths.
8. A login-throttle production test should be deliberate because it creates a
   process-global 60-second cooldown. Automated tests are the primary proof; at most,
   perform it when a brief owner lockout is acceptable.

## Failure and rollback

- Repeated `429` responses: wait for the `Retry-After` period. Do not restart solely
  to avoid the cooldown unless handling a real incident.
- Startup failure mentioning session-secret length: replace the Railway secret with a
  32+ character random value or roll back. Do not reveal the value.
- Unexpected delete `403`: use archive/restore. Check the high-risk override only when
  permanent deletion was explicitly authorized.
- Header regression or login regression: redeploy the prior main revision. No database
  rollback or migration action is required.

## Explicit boundaries

This change does not provide:

- distributed or per-account rate limiting
- trusted proxy/client-IP attribution
- CAPTCHA, OAuth, or multi-user identity
- full CSP, HSTS, or Permissions Policy
- session revocation lists
- automatic secret rotation
- a new backup or restore mechanism

Those remain separate future decisions.
