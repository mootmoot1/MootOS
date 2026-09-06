# CB-028A–F — System Model v1

Trusted Main base: `a43272719ceeade643569976aa82aa874f6d7d06` (after CB-027
phase / PR #91). This phase introduces a descriptive, evidence-only System
Model of a trusted repository tree. **ZERO AUTHORITY** — no publication,
queue, GitHub, merge, Main advancement, or worker-output trust is granted.
**DO NOT MERGE AUTOMATICALLY.**

## Purpose

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.

Workers cannot declare architecture as trusted. The System Model is built only
from trusted repo-root evidence the system itself inventories. Evidence is not
authorization.

## Architecture

```text
trusted repo root + pinned base_sha
  -> build_repository_inventory()     [CB-028B]
       regular files only; no symlink follow; bounded
       TCB flags via create_mootos_tcb_registry_v1() only
  -> ownership + SystemComponent set  [CB-028C]
  -> static Python import graph       [CB-028C]
       internal / external / unresolved / ambiguous
  -> sealed SystemModel               [CB-028A]
       model_version, digests, repo/base binding
  -> read-only queries / impact       [CB-028E]
       UNKNOWN / POSSIBLE IMPACT when unsure
```

## Trust review (TCB)

System Model is **descriptive evidence and read-only query**. It has no
enforcement power over admission, queue, or publication. Therefore
`backend/continuous_builder/system_model.py` stays **OUTSIDE** the TCB
registry (still 12 protected paths; CB-027 digest unchanged).

If a future change grants System Model referee/enforcement authority: **HOLD**
and expand TCB only through `create_mootos_tcb_registry_v1()` — never by
duplicating protected-path lists inside System Model.

## Status legend

| Claim | Status |
| --- | --- |
| Immutable sealed contracts with SHA256 identity | **PROVEN** |
| Deterministic inventory from trusted root | **PROVEN** |
| Exclusion policy (.git/caches/WAL/SHM/build junk) | **PROVEN** |
| Symlink non-follow / no path escape | **PROVEN** |
| Conservative ownership + static import graph | **PROVEN** |
| TCB flags/classification via canonical registry only | **PROVEN** |
| Missing protected paths detected | **PROVEN** |
| Read-only query + conservative impact | **PROVEN** |
| Zero authority flags on model/snapshot/impact | **PROVEN** |
| Adversarial suite items 1–28 | **PROVEN** |
| Integration Cases A–J on real MootOS | **PROVEN** |
| System Model outside TCB (descriptive only) | **PROVEN** / **DESIGNED** |
| Embeddings / semantic similarity | **DEFERRED** |
| Full call graph / type inference | **DEFERRED** |
| Runtime tracing | **DEFERRED** |
| LLM interpretation of architecture | **DEFERRED** |
| Context Engine / Task Decomposer | **DEFERRED** |
| Autonomous worker loop / GPU | **DEFERRED** |

## Inventory rules

* Exact repository-relative POSIX paths only (via `canonicalize_repo_path`)
* Regular files only; symlinks never followed
* Content SHA256 + size + category + optional Python package hint
* TCB membership from `create_mootos_tcb_registry_v1()` only
* Explicit excludes: `.git`, `__pycache__`, tool caches, `node_modules`,
  build/dist, `mootos.db-{wal,shm,journal}`, `* 2.*` duplicate markers,
  `job_created` / `scope_frozen` name markers
* Bounds: file count, per-file bytes, total bytes
* No import/exec of inventoried modules; no network; no credentials

## Component ownership

Deterministic path→component mapping (e.g. `backend.continuous_builder`,
`backend`, `tests`, `scripts`, `docs`, `frontend`, `config`, `root`).
Ownership states: `owned` / `ambiguous` / `unowned` / `excluded` / `unknown`.
Ambiguity is explicit — never invented certainty.

## Dependency graph

Static `ast` parse of Python imports only. Edge kinds:
`internal_import`, `external_import`, `unresolved_import`, `ambiguous_import`.
Longest component-id match wins; relative imports stay unresolved/ambiguous.
Small reliable graph preferred over speculative completeness.

## Query + impact

`component_for_path`, `files_for_component`, `dependencies_of`,
`dependents_of`, `model_tcb_classification`, `changed_components`,
`impacted_components`. Impact states: `impacted` / `possible_impact` /
`not_impacted` / `unknown`. No code generation, queue, dispatch, or approval.

## Authority check

All authority flags on `SystemModel`, `SystemModelSnapshot`, and
`ImpactAssessment` are structurally false. System Model cannot authorize
queue transitions, publication, GitHub, merge, Main advancement, or
worker-output trust.

## Deferred

* Embeddings / vector retrieval
* Full call graph, data-flow, and runtime tracing
* LLM-proposed architecture interpretation
* Context Engine / Librarian
* Task Decomposer
* Autonomous worker loop / GPU / provider router
* Expanding TCB to include System Model (requires HOLD + trust redesign)

## Recommendation

Ready for human review as descriptive System Model v1. Do not merge
automatically. Do not treat model output as authorization.
