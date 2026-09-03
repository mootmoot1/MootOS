# ADR-039 — Evolution Lab is disposable and promotion is evidence-only

## Status

Proposed. No Lab is provisioned by this record.

## Decision

Evolution/Jarvis Lab is a separate disposable repository and control plane for high-volume experiments. It shares no writable Git repository, database, credentials, runtime, queue, or deployment authority with production MootOS. Production data and secrets are prohibited. Network access is denied by default and explicitly allowlisted per experiment.

Lab workers may iterate aggressively only within fixed compute, token, time, storage, concurrency, and attempt budgets. A kill switch cancels active work and prevents new leases. Checkpoints preserve bounded source artifacts, deterministic tests, architecture notes, provider/config identity, and failure evidence; they do not preserve credentials or raw environment dumps.

Lab output has no production authority. Promotion produces a bounded evidence package containing source provenance, exact patch/tree digests, tests, threats, dependencies, conflicts, rollback, and claimed value. A human may classify it `promote`, `defer`, or `reject`. `Promote` creates ordinary production planning input; it does not copy code, reprioritize the production queue, approve a build, publish, merge, or deploy.

## Boundary with production MootOS

- Production blueprints and policy may be copied into the Lab read-only at pinned versions.
- Lab-generated plans, tests, findings, and patches are untrusted inputs on return.
- Every promoted idea receives a new production slice ID, normal scope review, independent verification, and standard approval gates.
- Production failures and sensitive telemetry are not automatically exported to the Lab.
- Lab success cannot weaken production tests, policy, or trust boundaries.

## Deferred decisions

Provisioning, credential ownership, permitted network destinations, artifact transport, sandbox implementation, large-scale scheduling, and promotion ingestion require separate reviewed designs before the Lab exists.
