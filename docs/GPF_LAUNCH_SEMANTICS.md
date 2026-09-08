# GP-F narrow trusted semantic launch-eligibility kernel

Resume: 5d470d2ab04771fd9e3defba30759bcc0f95e3ec.

This third slice answers exactly one question over trusted, current facts:
**is this exact launch candidate eligible right now?** It produces
deterministic blocker codes and a `TrustedLaunchEligibility` verdict. It is
not a supervisor, scheduler, Context Engine, System Model, provider or worker
runtime, and it mints no authority. `launch_authorized` remains False and no
`TrustedLaunchAuthorization` exists. Eligibility is explicitly **not**
authorization, and must never be persisted as permission to execute later.

## Why the previous stop is resolved

The blocker was that reusing the F3/F4 supervisor/preparation validation graph
drags 28 local modules, including Context Engine and System Model, into the
trusted closure. That expansion is refused.

The measured cause is `gpf_binding_resolution` -> `gpe_protocol` ->
`context_engine`/`gpb_*`/`system_model`, and `gpd_job_store` (31 modules)
which reaches the same stacks. The GP-D lifecycle contract itself does not:
`gpd_job_state` has an 8-module closure and pulls none of them. So the kernel
reuses the *authoritative* GP-D reducer directly and never touches the
supervisor graph. No partial state machine is duplicated.

## Two narrow modules

`gpf_launch_state_projection.py` reads only the fixed system-owned GP-D
sources already bound by the assignment, through the protected assignment
module's own bounded, symlink-refusing readers. It reconstructs the real
`DurableJobHeader` and `JobEvent` records from sealed rows and reduces state
with `gpd_job_state.reduce_job_state`. Lease, reconciliation and reservation
rows are read as already-sealed records and normalized into booleans and IDs.
It decides nothing.

`project_launch_state(facts, request_bytes)` revalidates the facts, reads
lifecycle, then revalidates again, and fails closed if any source token moved.
It returns `(fresh_facts, projection)` so a consumer cannot pair a projection
with a different snapshot.

`gpf_launch_semantics.py` is the referee. `evaluate_launch_eligibility(facts,
projection, approvals)` accepts only trusted-constructed records plus original
`(receipt_bytes, detached_signature, signer_key_id)` triples, which it
reverifies itself through the protected Ed25519 verifier. It accepts no
caller-supplied root, store, clock, ceiling, gate list or boolean; expiry is
judged against this process's clock. It reloads the authoritative binding at
the decision boundary rather than believing the record it was handed.

`gpf_approval_authority.verify_human_approval_subject` was added so the
referee can read the *signed* approved scope/capabilities/expiry instead of
duplicating a second receipt parser. It performs the same signature check and
decides nothing.

## Normalized trusted facts consumed

From facts/currentness: `job_id`, `attempt_id`, `request_id`,
`request_sha256`, `header_sha256`, `binding_sha256`, `facts_sha256`,
`source_tokens` (as `source_tokens_sha256`).

From the projection: `derived_state`, `current_attempt_id`,
`attempt_is_current`, `cancellation_requested`, `cancelled`,
`execution_unknown`, `reconciliation_required`, `reconciling`, `stalled`,
`timed_out`, `failed`, `lease_present`, `lease_expired`, `lease_reconciled`,
`lease_ambiguous`, `reservation_present`, `reservation_sha256`,
`reservation_identity`, `correlation_verified`, `admission_decision_id`,
`admission_decision_sha256`, `trusted_policy_version`, `tcb_registry_sha256`,
`tcb_snapshot_sha256`, `required_gates`, `allowed_scope`, `forbidden_scope`,
`admitted_capability_ids`.

From reverified signatures only: authenticated gate ids, approved scope,
approved capability ids, receipt identity digests and `valid_until`.

## Blocker codes

Canonical deterministic order, always emitted in exactly this order:

`facts_stale`, `binding_missing`, `binding_mismatch`, `reservation_missing`,
`reservation_mismatch`, `attempt_superseded`, `cancellation_requested`,
`cancelled`, `execution_unknown`, `reconciliation_required`, `reconciling`,
`stalled`, `timed_out`, `failed`, `job_terminal`, `lease_ambiguous`,
`product_correlation_unverified`, `admission_incompatible`,
`required_gate_missing`, `approval_invalid`, `approval_expired`,
`approval_wrong_attempt`, `approval_wrong_request`, `scope_widening`,
`capability_widening`.

`job_terminal` is the one code added beyond the required vocabulary: a job
already in `terminal_success`/`terminal_failure` has no launch to authorize,
and silently returning `eligible=True` for it would be unsafe. `cancelled`
keeps its own code rather than collapsing into it.

Identity failures (`facts_stale`, `binding_missing`, `binding_mismatch`) are
reported alone: every downstream lifecycle claim is meaningless once the
snapshot is not the live one.

## Preserved safety laws

An expired lease is never proof that nothing executed: it stays
`lease_ambiguous` until an explicit reconciliation clears that exact attempt,
and it also raises `reconciliation_required`. `execution_unknown`,
reconciliation-required and reconciling always block. A superseded or
non-current attempt always blocks. A missing or invalid human gate always
blocks. An authenticated signature can only ever remove
`required_gate_missing`; it never overrides another blocker, and blockers
accumulate rather than cancel. An approved subject may only narrow admitted
scope/capabilities -- widening or touching forbidden scope blocks. Binding,
request, attempt and reservation must match exactly. Source currentness must
still hold at the decision boundary.

A reconciliation record clears its attempt only when GP-D positively set
`retry_eligible_after` and the verdict is not an unresolved
`side_effect_conflict`. Any other record -- including `needs_human` and
`unsafe_to_retry`, which GP-D already forbids from re-enabling retry -- keeps
`reconciliation_required` set. This is deliberately conservative: an
unrecognised reconciliation history blocks rather than launches.

Live trusted-policy and TCB identity are rechecked against the bound header:
drift is `admission_incompatible` and requires explicit readmission.

## Protected closure and TCB delta

Two components, two paths, both `worker_authorization` / `human_only`:

- `cb_launch_state_projection` -> `gpf_launch_state_projection.py`
  (`system_owned_launch_state_projection`)
- `cb_launch_eligibility_semantics` -> `gpf_launch_semantics.py`
  (`trusted_launch_eligibility_referee`)

Cumulative from `5d470d2`: two paths, two components; **19 protected paths /
15 components**.
Registry digest: `989f05d88ef634c980c2d65250cb3afcee69cdd8867f9c8a4909f00b63c9a837`.

Complete local import closure of `gpf_launch_semantics` (14 modules, checked
by an AST test): `gpf_launch_semantics`, `gpf_launch_state_projection`,
`gpf_launch_facts`, `gpf_launch_candidate_binding`, `gpf_approval_authority`,
`gpc_trusted_admission_core`, `gpd_job_state`, `gpd_job_events`,
`gpd_job_header`, `gpa_eval_schema`, `timestamps`, `trusted_policy`, `paths`,
`text_safety`. No Context Engine, System Model, GP-E object stack,
`gpd_job_store`/`gpd_recovery`, supervisor/preparation graph, worker runtime,
provider SDK, GitHub or network code enters it.

### Open review item

`gpd_job_state`, `gpd_job_events`, `gpd_job_header`, `gpa_eval_schema` and
`timestamps` are now inside a trusted closure but are **not** protected paths.
This follows existing precedent (`paths` and `text_safety` are already
unprotected members of the GP-F trusted closure) and this slice deliberately
does not expand the registry unilaterally. Whether the GP-D lifecycle contract
should become its own protected component is a human decision and is recorded
here rather than silently taken.

## What is still missing

`TrustedLaunchEligibility` can reach `eligible=True`. That is the intended
outcome of this slice and it grants nothing: every authority flag is
structurally False, and no consumer that could mint launch authority exists.
`TrustedLaunchAuthorization` was deliberately not implemented -- one-shot
consumption, post-authorization race closure and the dispatch boundary are a
separate authority contract that must be reviewed before it is written.

The kernel refuses launch-unsafe lifecycle states; it does not decide launch
*readiness* or scheduling order. That remains the supervisor's boundary and is
not folded in here.

No worker or provider has run. No real private key was read, opened, copied,
logged or used; tests use ephemeral synthetic Ed25519 keys only. F10 must
still prove ordinary workers cannot reach `/Users/freeman/.mootos` or the
coordinator-only binding store before any real launch.
