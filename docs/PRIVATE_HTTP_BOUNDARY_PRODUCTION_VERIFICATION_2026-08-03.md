# Private HTTP Boundary Production Verification — August 3, 2026

## Purpose

Record non-private production evidence that PR #23 deployed successfully and that the strengthened private HTTP boundary works without breaking normal MootOS login, chat access, or recoverable memory lifecycle controls.

## Reviewed change

- Pull request: `#23 — hardening: strengthen private HTTP boundary`
- Reviewed PR head: `20c551aeb71cf36f0b9ae4127d75845e8f3fde35`
- Squash merge commit on `main`: `a3c4aa3e5759d0b2e658d945086e2a4d0b55bc1e`
- Production platform: Railway
- Production shape: one service, one process, one replica, SQLite on the attached volume

## Production checks completed

After Railway deployed the merged `main` revision:

1. `GET /ready` returned `{"status":"ready"}`.
2. `GET /health` returned `{"status":"healthy"}`.
3. The normal MootOS chat interface loaded successfully.
4. A private/incognito browser session showed the password login flow.
5. One correct-password attempt opened MootOS normally.
6. Browser developer tools confirmed the private HTML response included:
   - `Cache-Control: no-store`
   - `Referrer-Policy: same-origin`
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
7. A disposable memory completed the recoverable lifecycle:
   - active memory visible
   - archive succeeded
   - archived row remained available
   - restore succeeded
   - the same memory returned to active state

## Deliberately not tested manually

The process-global login cooldown was not intentionally triggered in production. Five failed attempts would create a 60-second process-wide cooldown for the current single running process. Exact-head automated tests remain the primary proof for the fifth-failure `429`, `Retry-After`, automatic expiry, and successful-login reset behavior.

The Railway permanent-delete override was not enabled merely for testing. `MOOTOS_ALLOW_HARD_DELETE` remained false or absent, and production verification used the supported recoverable archive/restore path instead.

## Result

PR #23 is production-verified for the controlled checks above:

- deployment readiness and liveness remained healthy
- private login remained functional
- the normal application remained usable
- required private-response cache and browser-security headers were active
- recoverable memory archive and restore remained functional
- no production hard-delete override was required

## Privacy

This record contains no password, session secret, cookie, Railway variable value, memory content, conversation content, database file, private path, or API key.
