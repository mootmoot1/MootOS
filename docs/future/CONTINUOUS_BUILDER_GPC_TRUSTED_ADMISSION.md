# GP-C — Trusted Risk & Capability Admission

Trusted Main base: `33f7fe0cf24f1e5871d4b2950086730a6112b99b` (PR #96 GP-B
merged). This phase is **admission-only**. **ZERO EXECUTION AUTHORITY** —
nothing here executes a coding provider, merges, advances Main, changes
trusted policy/TCB/verifier/approval rules, expands credentials/network,
or mutates production. **DO NOT MERGE AUTOMATICALLY.**

## Purpose

GP-C answers: **what capabilities may this frozen task + proposed plan
request/receive under trusted policy?**

It does **not** replace the worker, router, LLM risk judge, decomposer,
executor, approval system, merge, or deploy path.

```text
FrozenTaskContract + ExecutionPlan (GP-B proposals)
    |
    v
CapabilityRequest[] (GP-C1) -- sealed, zero authority
    |
    v
AdmissionInput (GP-C2) -- bind contract/plan/TCB/policy/vocabulary
    |
    +-- PolicyMatrix lookup (GP-C3)
    +-- Scope / risk / TCB rules (GP-C4)
    +-- Budget / constraint checks (GP-C5)
    |
    v
AdmissionDecision + AdmissionReceipt (GP-C6)
    |
    v
Eval / adversarial corpus (GP-C8)
```

**Descriptive risk estimation** (GP-A taxonomy / GP-B ceilings) is
separate from **trusted capability admission** (this phase). Descriptive
risk never grants or denies by itself; deterministic rules do.

## Module inventory

| Module | Role | Slice |
| --- | --- | --- |
| `gpc_trusted_admission_core.py` | **TRUSTED** — sole authoritative admission algorithm + facts/decision DTOs | C-trusted |
| `gpc_capability_vocabulary.py` | UNTRUSTED request sealing; re-exports outcome/capability tables from core | C1 |
| `gpc_admission_input.py` | UNTRUSTED assembler (binds GP-B + vocabulary + TCB identity) | C2 |
| `gpc_policy_matrix.py` | Thin re-export of core matrix | C3 |
| `gpc_scope_risk_tcb.py` | Thin re-export of core scope/risk/TCB rules | C4 |
| `gpc_budget_constraints.py` | Thin re-export of core budget checks | C5 |
| `gpc_admission_decision.py` | Thin adapter: AdmissionInput → TrustedAdmissionFacts → core | C6/C7 |
| `gpc_eval_corpus.py` | UNTRUSTED eval / adversarial corpus | C8 |

Shared primitives: `gpa_eval_schema` digests/paths/`AUTHORITY_FLAGS`/
UNKNOWN; GP-A taxonomy class IDs; GP-B `FrozenTaskContract` /
`ExecutionPlan`; `trusted_policy` registry query helpers
(`is_tcb_path`, `classify_tcb_path`, snapshots). No competing permission
system.

## Guarantees

1. **System owns truth; worker only proposes.** Requests and plans are
   proposals; admission is deterministic and fail-closed.
2. **Default-deny.** UNKNOWN / unsupported capability ids never
   `allow_within_bound`.
3. **Descriptive risk ≠ grant.** Low risk cannot override forbidden /
   OOS / TCB deny.
4. **Worker / model / provider / benchmark never grant.** Claims are
   recorded as ignored reason codes.
5. **Valid GP-B plan ≠ capability.** Plan validity does not admit
   capability; GP-B `requires_escalation` blocks silent auto-allow.
6. **TCB-adjacent ≠ ordinary write.** Protected paths force human gate
   / escalate; change_policy `human_only` / `protected_core_review`
   recorded.
7. **Main merge / advance always human-gated.** Never appear in
   `admitted_within_bound`; `main_merge_auto_approved` structurally
   False.
8. **Decision / receipt cannot execute.** `execution_authorized`,
   `approved_to_execute`, `capability_runtime_granted` always False.
9. **Tamper / drift fail closed.** Stale base, TCB digest mismatch,
   request/contract/plan digest mismatch, gate removal, budget
   increase, forged decision digest rejected.

## Human-gated (may package, never auto-approve)

- Main merge / Main advancement
- Trusted policy / TCB / verifier / approval-rule changes
- Broader credentials / network
- Production deploy / destructive ops / migrations
- Frozen scope / risk / capability / budget expansion
- Removal of human gates

## Deferred / non-guarantees

- **Runtime enforcement** of admitted bounds → **GP-D / GP-F**.
- **Persistence** of decisions into queue / job store → **GP-D**.
- **Provider routing / launch** → later phases; never here.
- **TCB registry membership** — authorized follow-up added exactly one
  protected path: `backend/continuous_builder/gpc_trusted_admission_core.py`
  under new component `cb_capability_admission` / category
  `capability_admission` (human_only). Corpus, admission_input, GP-B,
  System Model, Context Engine, and tests remain outside TCB.
- Does not merge, publish, or advance Main.
- Does not claim optimal or complete capability coverage — only
  deterministic admission over the sealed vocabulary.

## How GP-D should persist decisions

1. Accept only sealed `AdmissionDecision` whose digests re-verify.
2. Bind decision digest to job / attempt identity (like
   `WorkerDispatchAuthorization`).
3. Treat `allow_within_bound` as **admission evidence**, not launch
   permission — GP-D still requires separate dispatch authorization.
4. Persist receipt alongside decision; never promote
   `approved_to_execute`.
5. Re-check TCB registry digest + policy version at persist time;
   drift → reject.
6. Human-gated outcomes require explicit human approval records before
   any downstream packaging.

## Architecture economy

Reuses GP-A schema, taxonomy, baseline binding; GP-B contracts/plans;
trusted_policy queries; AUTHORITY_FLAGS zero-authority idiom; CB
naming from worker_authorization / PR publication auth. Does **not**
create a second tool registry or competing approval authority.

Trusted core concentrates the algorithm (matrix + scope/risk/TCB +
budget + facts + decision) in one auditable module; wrappers are thin.
Correctness > security > determinism > maintainability > simplicity > size.

## Adversarial invariants (must hold)

- UNKNOWN ≠ ALLOW
- Low risk ≠ override forbidden
- Worker/model/provider/benchmark never grant
- GP-B valid plan ≠ capability
- Scope widen / gate remove / stale never auto-admit
- TCB specially controlled
- Main merge human-gated
- Decision/receipt cannot execute
- Forged fail closed

## STOP points obeyed

Only the authorized +1 TCB path for the trusted core; no other TCB / verifier / approval edits;
no schema/DB migration; no production/deploy; no network/cred
expansion; no destructive ops; no provider execution; no Main merge.
