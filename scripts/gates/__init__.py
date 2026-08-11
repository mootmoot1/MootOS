"""V0.3D mechanical release gates for MootOS.

Converts the protected-core and release-safety rules recorded in ADR-031
(`docs/ADR-031-protected-core-mechanical-gates.md`) from documentation into
enforced, deterministic checks. See `docs/GATES_AND_RELEASE_SAFETY.md` for
the full design and `docs/CAPABILITY_ARCHITECTURE.md` Sec6 (V0.3D) for the
architecture this implements.

This package is itself a protected path (`scripts/gates/` is listed in
`policy.DENIED_PATHS`) — a diff cannot rewrite the policy or the gate
scripts that enforce it to grant itself permission. CI additionally runs
this tooling from a trusted extraction of the base branch, not from the
proposed branch's own working tree, so a PR cannot blind the gate that
evaluates it by editing this package in the same PR. See
`.github/workflows/python-package.yml` and
`docs/GATES_AND_RELEASE_SAFETY.md` "Self-protection" for the full
mechanism.

Every gate here is a **mechanical, deterministic check** (ADR-031/ADR-032):
it may block a merge. It never asks a model for judgment, and it is never
itself a source of merge/install/deploy authority — that remains with a
human, always (ADR-032).
"""
