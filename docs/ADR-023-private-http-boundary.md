# ADR-023: Private HTTP boundary hardening

## Status

Accepted for Version 0.1 Hardening Pass #2.

## Context

MootOS Version 0.1 already requires a password and signed session in normal Railway
production, but the surrounding HTTP boundary still had several avoidable weaknesses:

- repeated password guesses had no application-owned cooldown
- `MOOTOS_SESSION_SECRET` could be configured with an arbitrarily short value
- private HTML and JSON responses did not explicitly disable browser/proxy caching
- basic anti-sniffing, anti-framing, and referrer headers were absent
- the legacy permanent `DELETE /memories/{memory_id}` route remained available on
  Railway even though the normal user-facing lifecycle is recoverable archive/restore

Per-client throttling based on raw `X-Forwarded-For` was considered, but the current
application does not own or validate a trusted proxy chain. Treating that header as an
authoritative client identity would let a caller rotate or spoof values and avoid the
limit.

## Decision

### Process-global login cooldown

One running MootOS process keeps a small in-memory failed-login budget:

- five failed login attempts are allowed before cooldown
- the fifth failure starts a 60-second cooldown
- requests during cooldown receive HTTP `429` and a `Retry-After` header
- the budget is process-global and does not use `X-Forwarded-For`
- expiration clears the cooldown automatically
- a successful login clears accumulated failures

This is intentionally a Version 0.1 boundary for one Railway service, process, and
replica. It is not a distributed rate limiter.

### Minimum session-secret length

When private authentication is configured, `MOOTOS_SESSION_SECRET` must contain at
least 32 characters. Startup fails closed when the value is shorter. Rotating the
secret invalidates existing browser sessions, which is expected.

### Private response caching and basic browser headers

Every normal response receives:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`

Dynamic/private responses also receive `Cache-Control: no-store`. Public liveness,
readiness, install metadata, and static assets remain outside the no-store rule:

- `/health`
- `/ready`
- `/manifest.webmanifest`
- `/static/*`

A full Content Security Policy, HSTS policy, and Permissions Policy are deliberately
deferred until their deployment effects can be designed and tested separately.

### Railway hard-delete policy

Permanent memory deletion is disabled on Railway by default. The route returns HTTP
`403` before touching storage and tells the caller to archive the memory instead.

An operator can deliberately re-enable the legacy hard-delete route only by setting:

```text
MOOTOS_ALLOW_HARD_DELETE=true
```

Local development keeps the existing hard-delete behavior by default. Recoverable
archive and restore remain available in all environments and remain the normal user
path.

## Consequences

- A burst of bad passwords can briefly delay the legitimate owner for up to 60
  seconds, but cannot create a permanent application lockout.
- Restarting the single process clears the in-memory login budget.
- Multi-process or multi-replica deployment would require a shared limiter before the
  same guarantee could be claimed across replicas.
- A session secret shorter than 32 characters now prevents startup instead of
  silently weakening signed sessions.
- Private browser/API responses explicitly resist storage in caches and embedding in
  frames.
- Accidental permanent memory deletion is unavailable in normal Railway production.
- No schema migration, dependency, provider, chat, memory-ranking, or frontend change
  is introduced.

## Rejected alternatives

### Trust raw `X-Forwarded-For`

Rejected because MootOS does not currently validate a trusted proxy chain. A spoofed
or rotating header would make a per-address limit misleading.

### Permanent account lockout

Rejected because MootOS has one owner and no independent account-recovery flow. A
short automatic cooldown reduces guessing without creating a support or recovery
trap.

### Remove the hard-delete route everywhere

Deferred to preserve local/API compatibility while normal Railway production moves
to the safer archive/restore path.

### Add full CSP/HSTS immediately

Deferred because those policies can break development, documentation, or proxy
behavior when added without a separate inventory and controlled rollout.
