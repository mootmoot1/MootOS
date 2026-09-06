# GP-B — Task Decomposer & Scope-Preserving Planner

Trusted Main base: `b448dcaf679861b23cc690186fc96815776a6e3d` (PR #95 roadmap
architecture-economy checkpoint merged). This phase is **planning-only**.
**ZERO AUTHORITY** — nothing here executes a coding provider, merges,
advances Main, changes trusted policy/TCB/verifier, admits capability
(GP-C), expands scope, or mutates production. **DO NOT MERGE AUTOMATICALLY.**

## Purpose

GP-B turns a **frozen task intent contract** into a **revisable execution
plan** without silently changing approved intent, scope, acceptance,
budgets, descriptive risk ceilings, required gates, or contract identity.
Planning success is never execution permission.

```text
FrozenTaskContract (GP-B1)  -- FROZEN intent envelope
    |
    v
DecompositionNode tree (GP-B2) + ScopePreservationRules (GP-B3)
    |
    +-- Impact evidence from System Model only (GP-B4)
    |
    v
Deterministic decomposer (GP-B5) -> ExecutionPlan
    |
    +-- Plan revision without contract drift (GP-B6)
    |
    v
DecompositionReceipt provenance (GP-B7)
Decomposition eval/adversarial corpus (GP-B8)
```

## Module inventory

| Module | Lines | Slice |
| --- | ---: | --- |
| `gpb_task_contract.py` | 353 | B1 |
| `gpb_decomposition_node.py` | 326 | B2 |
| `gpb_scope_rules.py` | 529 | B3 |
| `gpb_impact_evidence.py` | 310 | B4 |
| `gpb_decomposer.py` | 553 | B5 |
| `gpb_plan_revision.py` | 390 | B6 |
| `gpb_decomposition_receipt.py` | 244 | B7 |
| `gpb_eval_corpus.py` | 524 | B8 |

Every module follows the GP-A / trusted_policy idiom: frozen dataclass,
private construction token, digest re-derived in `__post_init__`, all
authority flags structurally `False`. Shared primitives come from
`gpa_eval_schema` (canonical JSON, SHA-256, UNKNOWN, path checks,
`AUTHORITY_FLAGS`). GP-A taxonomy class IDs are reused — no competing
taxonomy/baseline/evidence framework.

## Guarantees

1. **Frozen vs revisable split**: `FrozenTaskContract` identity/intent/scope/
   acceptance/budget/risk-ceiling/gates/base_sha/baseline binding cannot be
   silently revised by plan ops; widenings escalate.
2. **Scope preservation**: children cannot exceed parent/contract envelopes;
   forbidden inclusion, relaxed acceptance, removed gates, budget/risk
   increases, out-of-scope deps, cycles, duplicate IDs are explicit violations.
3. **System Model only for deps/impact**: `collect_impact_evidence` uses CB-028
   queries; UNKNOWN is valid; no invented edges.
4. **Deterministic, no LLM**: `decompose_task_contract` is rule-based.
5. **Valid plan ≠ approved to execute**: `approved_to_execute` and
   `execution_authorized` are always False on plans/receipts/revisions.
6. **Risk descriptive only**: `risk_classification_descriptive_only=True` and
   `capability_admission_deferred_to_gpc=True` on every contract.
7. **Evaluator non-leakage**: GP-B8 worker views strip evaluator expectations.

## Non-guarantees

- Does **not** admit trusted capability / permissions (GP-C).
- Does **not** route or launch Claude/Codex/Grok/GPU workers.
- Does **not** change TCB registry, verifier, sandbox, or approval policy.
- Does **not** merge, publish, or advance Main.
- Does **not** perform schema/DB migrations or production mutations.
- Does **not** claim optimal decompositions — only deterministic, scope-safe
  proposals.
- Ownership mapping for multi-owner scopes uses conservative path/test splits
  when SM returns unique owners without per-path maps; UNKNOWN remains valid.

## How GP-C consumes this output

GP-C (trusted capability admission) should treat:

- `FrozenTaskContract` as the immutable intent envelope to evaluate against
  capability policy (never re-derived from a plan).
- `ExecutionPlan` + `DecompositionReceipt` as **proposals** whose digests
  bind provenance; capability grants must be a separate sealed decision.
- `requires_escalation` / scope violations as hard stops before any
  capability consideration.
- Descriptive `risk_ceiling_indicators` as hints only — GP-C owns real
  admission.

GP-C must **not** treat `approved_to_execute=False` plans as executable by
flipping a flag in these modules.

## Deferred (explicit)

- Trusted risk classification / capability permissions (GP-C)
- Provider execution / routing (later golden-plan slices)
- Automatic contract-change approval workflow (human / premium architect)
- Richer per-path ownership maps inside impact evidence (SM enhancement)

## Architecture-economy observations

**Reused primitives**: `gpa_eval_schema.canonical_json/sha256_hex/require_*`,
`AUTHORITY_FLAGS`, `canonicalize_repo_path`, GP-A taxonomy IDs,
`ArchitectureBaselineManifest` digest binding field, System Model query
API (`component_for_path`, `dependencies_of`, `dependents_of`,
`impacted_components`, `model_tcb_classification`), Context Engine
`ENGINE_VERSION` + source digest pattern from GP-A1.

**Intentional duplication**: sealed dataclass + token + digest idiom per
trust-boundary artifact (contract, node, plan, receipt, scope result) —
same pattern as GP-A/TCB, not a shared "god serializer" that could blur
authority boundaries.

**Accidental duplication avoided**: no second taxonomy, no second path
canonicalizer, no second UNKNOWN sentinel, no parallel baseline inventory.

**Largest modules**: decomposer and scope rules are the largest GP-B units;
none intentionally exceed ~700–900 lines. No speculative provider wrappers.

## Reproduction

```bash
# From repo root at this branch:
python3 -m pytest tests/test_continuous_builder_gpb_*.py -q
python3 -m pytest tests/test_continuous_builder_gpa_*.py -q
python3 -c "from backend.continuous_builder.trusted_policy import create_trusted_policy_snapshot as s; t=s(); print(t.registry_sha256, t.protected_path_count, t.component_count)"
```

## Status legend

| Claim | Status |
| --- | --- |
| Frozen contract sealed with zero authority + GP-C-deferred risk flags | **PROVEN** |
| Variable-depth nodes without forced ceremony | **PROVEN** |
| Scope preservation escalates widenings | **PROVEN** |
| Impact evidence from System Model only; UNKNOWN valid | **PROVEN** |
| Deterministic decomposer; no LLM | **PROVEN** |
| Plan revision preserves contract or escalates | **PROVEN** |
| Receipt binds identities; never approved_to_execute | **PROVEN** |
| Adversarial corpus + non-leakage worker view | **PROVEN** |
| Capability admission / provider execution | **OUT OF SCOPE — GP-C+** |

## Trust review (TCB)

None of `gpb_*.py` is added to `create_mootos_tcb_registry_v1()`. TCB
digest/path/component counts must remain unchanged by this phase.
