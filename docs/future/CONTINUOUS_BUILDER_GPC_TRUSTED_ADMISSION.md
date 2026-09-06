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

| Module | Approx lines | Slice |
| --- | ---: | --- |
| `gpc_capability_vocabulary.py` | ~689 | C1 |
| `gpc_admission_input.py` | ~332 | C2 |
| `gpc_policy_matrix.py` | ~258 | C3 |
| `gpc_scope_risk_tcb.py` | ~233 | C4 |
| `gpc_budget_constraints.py` | ~100 | C5 |
| `gpc_admission_decision.py` | ~589 | C6/C7 |
| `gpc_eval_corpus.py` | ~908 | C8 |

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
- **TCB registry membership for GP-C modules** — this autonomous run
  **did not** edit `trusted_policy.py` or add GP-C paths to the TCB
  registry (CRITICAL TCB RULE). Registering
  `gpc_admission_decision.py` / matrix / vocabulary under a new or
  existing TCB component is a **human-gated follow-up** if desired;
  smaller design avoids it by treating GP-C as consumer of TCB (like
  GP-A/GP-B) rather than TCB itself until review.
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

Largest modules: `gpc_eval_corpus.py` (~908), `gpc_capability_vocabulary.py`
(~689), `gpc_admission_decision.py` (~589). Correctness > security >
determinism > maintainability > simplicity > size.

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

No trusted_policy / TCB / protected-path / verifier / approval edits;
no schema/DB migration; no production/deploy; no network/cred
expansion; no destructive ops; no provider execution; no Main merge.
