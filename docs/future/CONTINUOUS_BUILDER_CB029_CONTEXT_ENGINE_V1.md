# CB-029A–H — Context Engine v1

Trusted Main base: `ccd6bbe9e6a20939d2b7978286a5a618fa9c06cf` (after CB-028
System Model / PR #92). This phase introduces a read-only evidence librarian
over the System Model map. **ZERO AUTHORITY** — retrieval cannot grant
permission, enlarge scope, authorize queue/GitHub/merge/Main, or trust worker
output. **DO NOT MERGE AUTOMATICALLY.**

## Purpose

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.

NO MODEL NEEDS ALL OF MOOTOS — reconstruct the smallest sufficient context.
Context Engine = descriptive librarian. Visibility ≠ write permission.

## Architecture

```text
frozen ContextTaskRequest (intent only)
  + sealed SystemModel (CB-028)
  -> plan_context_selection()     [deterministic; no LLM]
  -> extract_excerpt()            [secret-safe; regular files]
  -> enrich_interface_summary()   [ast only; no exec/import]
  -> retrieve_* docs/tests        [deterministic path rules]
  -> assemble_context_package()   [hard budgets + receipt]
  -> fulfill_supplement()         [capped; denial codes]
```

## Trust review (TCB)

Context Engine is **descriptive only**. Policy independently checks
permissions. `backend/continuous_builder/context_engine.py` stays **OUTSIDE**
the TCB registry (still 12 protected paths; CB-027 digest unchanged).

If a future change would alone authorize execution/scope/TCB/policy: **HOLD**
and expand TCB only via `create_mootos_tcb_registry_v1()`.

## Status legend

| Claim | Status |
| --- | --- |
| Frozen request/scope/budget seals with SHA256 identity | **PROVEN** |
| Trusted excerpt extraction (no symlink/traversal) | **PROVEN** |
| Fail-closed secret exclusion (.env/keys/creds/Bearer) | **PROVEN** |
| Deterministic System Model planner (no LLM) | **PROVEN** |
| Visibility ≠ edit permission | **PROVEN** |
| Static AST interface enrichment | **PROVEN** |
| Deterministic ADR/arch/docs/tests retrieval | **PROVEN** |
| Package assembly + hard budgets + receipt | **PROVEN** |
| Completeness descriptive only | **PROVEN** |
| Supplement protocol with denials + hard cap | **PROVEN** |
| Adversarial suite items 1–48 | **PROVEN** |
| Integration Cases A–O on real MootOS | **PROVEN** |
| Context Engine outside TCB | **PROVEN** / **DESIGNED** |
| Provider adapters (Codex/Grok/GPU) | **DEFERRED** |
| Embeddings / vector / LLM retrieval | **DEFERRED** |
| Full call graph / runtime tracing | **DEFERRED** |
| Task Decomposer / autonomous loop | **DEFERRED** |

## Budgets

* Default package budget: 256 KiB
* Hard max package budget: 1024 KiB
* Default excerpt budget: 16 KiB (hard max 64 KiB)
* Seeds ≤ 64, depth default 1 max 2, components ≤ 64, excerpts ≤ 128
* Supplements ≤ 8 per package; supplement budget ≤ 64 KiB

### Assembly priority (when full)

1. task contract
2. authority / non-goals
3. editable paths
4. acceptance
5. TCB warnings
6. interfaces
7. deps
8. tests
9. arch
10. supporting excerpts

Never silently drop critical evidence — mark `incomplete` / `needs_review`.

## Performance measurements (real worktree sample)

| Metric | Value |
| --- | --- |
| files_considered | 455 |
| files_selected | 64 |
| excerpt_count | 28 |
| package_bytes | 524245 |
| token_estimate | 131062 |
| wall_clock_ms | 281.842 |
| dep_expansion_components | 2 |

## Authority check

All authority flags on request/plan/excerpt/package/receipt/supplement are
structurally false. Context Engine cannot authorize queue transitions,
publication, GitHub, merge, Main advancement, or worker-output trust.

## Deferred

* Codex / Grok / xAI / Claude / GPU provider adapters
* Embeddings / semantic similarity / vector DB
* Full call graph, data-flow, runtime tracing
* Task Decomposer
* Autonomous worker loop / queue automation
* Expanding TCB to include Context Engine (requires HOLD + trust redesign)

## Recommendation

Ready for human review as descriptive Context Engine v1. Do not merge
automatically. Do not treat context packages as authorization.
