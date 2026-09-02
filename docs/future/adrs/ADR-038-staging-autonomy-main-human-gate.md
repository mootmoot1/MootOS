# ADR-038 — Staging may earn bounded autonomy; Main remains human-gated

## Status
Proposed future decision; not implemented.

## Decision
Future Continuous Builder may promote clearly independent low-risk changes into Staging after an inactivity window of about five hours only when all required evidence is clean: tests, dependency independence, security checks, Chaos findings, and rollback.

No time window authorizes automatic Main merge.

## Rationale
This keeps the system productive while Moot is away without turning production into an unattended experiment.
