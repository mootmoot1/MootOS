# CB-025 — contained single-slice trust-chain proof

## What this slice is

CB-025 proves that the already-merged Continuous Builder pieces compose into
**one bounded pipeline for exactly one tiny offline task**, and that a worker
never gets to declare itself correct anywhere along it.

```
tiny fixture task (system-declared)
  -> CB-014..CB-021 request / authorization / action / runtime foundation
  -> CB-022 contained Docker execution        (worker_runtime.py)
  -> CB-024 receipt-driven supervision        (supervisor.py)
  -> CB-023 artifact intake and quarantine    (worker_artifact.py)
  -> CB-025 blast-radius gate                 (blast_radius.py)          NEW
  -> CB-025 independent verifier              (candidate_verifier.py)    NEW
  -> CB-025 immutable proof receipt           (trust_chain_proof.py)     NEW
  -> human review, and nothing else
```

It is **not** the generalized verifier system (CB-026+), not provider routing,
not multi-worker orchestration, and not any form of merge, publication, queue
advancement, or Main authority. No network access, credentials, database
migrations, retries, or GitHub authority were added.

## Architecture law this slice enforces

> The system owns truth. The worker only proposes changes.

Every one of the following comes from trusted, deterministic, system-side
evidence, and never from worker-authored text:

| Claim | Owned by |
| --- | --- |
| execution happened, contained | CB-022 `WorkerExecutionReceipt` |
| termination / cleanup certainty | CB-024 `SupervisionReceipt` |
| artifacts are structurally safe | CB-023 `ArtifactIntakeReceipt` |
| artifacts stayed inside the fence | CB-025 `BlastRadiusReceipt` |
| the candidate is actually correct | CB-025 `CandidateVerificationReceipt` |
| the whole chain held | CB-025 `TrustChainProofReceipt` |

## The tiny fixture task

`backend/continuous_builder/proof_fixture.py` declares one deterministic,
offline, disposable task — `create_increment_value_task()`:

* trusted base fixture: `value.txt` containing `1\n`
* allowed path set: exactly `("value.txt",)`
* expected candidate: `value.txt` containing exactly `2\n`
* bounded artifact count: 1

The task contract is frozen and content-addressed (`task_sha256`), and the
acceptance rule has its own digest (`acceptance_rule_sha256`) so a later stage
cannot silently substitute an easier rule. Declaring a boundary that names a
forbidden path class — a dot-segment such as `.git/config`, an absolute path,
a `..` escape, `node_modules`, `__pycache__` — fails closed at construction.

The task deliberately does not target production MootOS source.

## Blast-radius gate

`backend/continuous_builder/blast_radius.py`, `evaluate_blast_radius()`.

It answers exactly one question about an already-quarantined artifact set:
**did the observed, admitted artifacts stay inside the declared boundary?**

It evaluates, independently of any worker claim:

* exact identity binding to the same execution, attempt, request, runtime
  policy, materialization receipt, workspace identity, intake receipt, and
  quarantine package digest (mismatch raises, it does not downgrade)
* path canonicalization, re-derived rather than trusted
* membership in the declared allowed-path set
* forbidden path classes (dot segments, `node_modules`, `__pycache__`)
* the bounded artifact count
* artifact filesystem type is `regular_file` — symlinks, devices, sockets and
  FIFOs are already rejected structurally at CB-023 intake
* the admitted payload set and every payload digest, re-derived from bytes

Statuses are `within_blast_radius_unverified` and `blast_radius_rejected`.
Any violation rejects. The receipt is frozen, content-addressed, byte-bounded,
and carries `worker_claim_considered=False` plus
`artifact_content_trusted / result_verified / publication_authorized /
queue_transition_authorized / github_authorized / merge_authorized = False`.

Passing this gate means **only** "the observed admitted artifact set stayed
inside the declared boundary". It is not safety, correctness, or trust.

## Independent verifier

`backend/continuous_builder/candidate_verifier.py`, `verify_candidate()`.

Deliberately narrow and fixture-specific. Its independence properties, each
asserted mechanically by the CB-025 tests:

1. **Never reuses the worker's mutable execution workspace.** CB-022 has
   already destroyed it; the verifier never had a path to it either.
2. **Operates from trusted inputs plus quarantined payloads only** — the
   task's trusted base bytes and acceptance rule, and the exact bytes CB-023
   admitted, bound by digest to one execution.
3. **Re-derives every digest from bytes** rather than believing the digests
   recorded in the quarantine inventory.
4. **Reconstructs the candidate tree** (trusted base, overlaid with admitted
   payloads) and compares against the system's own expected bytes.
5. **Reads no worker-authored channel.** An AST test asserts the module never
   references `stdout_sample`, `stdout_sha256`, `stderr_sample`, or any other
   worker output attribute, so a worker asserting "tests passed" is inert.
6. Deterministic, offline, no subprocess, no network, no database, no GitHub.

Statuses are `verification_passed` and `verification_failed`. A pass
authorizes nothing.

Extra, unexpected paths are intentionally *not* the verifier's concern — that
is the gate's question. This split is what makes the negative control sharp:
a cheating worker can produce a genuinely correct `value.txt` and still be
rejected.

## Proof receipt

`backend/continuous_builder/trust_chain_proof.py`,
`build_trust_chain_proof()`.

One immutable, content-addressed object binding base SHA, task and acceptance
digests, attempt / execution / request / policy / materialization identity,
workspace identity, and the CB-022, CB-024, CB-023, blast-radius and verifier
receipt digests, plus the final classification and `proof_sha256`.

Fail-closed classifications, evaluated in chain order:

| Classification | Cause |
| --- | --- |
| `contained_verified_candidate` | every stage held |
| `rejected_runtime` | supervision classified failed / crashed / timed out / stalled / cancelled |
| `rejected_supervision` | termination or cleanup uncertain, containment violation, open breaker |
| `rejected_artifact_security` | CB-023 rejected the artifacts |
| `rejected_blast_radius` | artifacts crossed the declared fence |
| `rejected_verification` | the candidate is not what the task requires |
| `rejected_uncertain_state` | anything the chain cannot classify |

`contained_verified_candidate` means exactly one thing: *this candidate
survived this bounded trust chain*. It still carries, and structurally cannot
carry anything else:

```
human_review_required          = True
result_trusted                 = False
worker_output_trusted          = False
externally_verified            = False
publication_authorized         = False
queue_transition_authorized    = False
github_authorized              = False
merge_authorized               = False
main_advancement_authorized    = False
```

The proof also **re-derives both CB-025 gates itself** from the quarantine
package and rejects any supplied receipt whose digest does not match the one
it just recomputed. A hand-built "passing" blast-radius or verification
receipt is therefore useless even when its own internal digest is
self-consistent.

## Known limitation: artifact provenance is NOT proven (Section G outcome)

This is the honest, load-bearing caveat of the slice, and it is recorded in
the proof receipt itself rather than only in prose.

**CB-022 gives a contained worker no artifact egress channel at all.**
`DockerWorkerRuntime.execute()` creates the container with `--read-only`,
mounts `/workspace` as a container-local **tmpfs**, and
`_verify_enforcement()` asserts there is exactly **one** mount — the
read-only `/source` bind. There is no `docker cp`, no export, and no writable
bind mount or volume anywhere in the runtime. A tmpfs is torn down when the
container stops, so anything the worker wrote to `/workspace` is gone *before*
the `finally` block's `docker rm --force` and `_remove_workspace()` even run.

Consequently `intake_worker_artifacts()` can only ever scan a supervisor-owned
staging root that **some other party populated** — today, only tests. Nothing
in `backend/` populates `ARTIFACT_INTAKE_ROOT`. CB-023 already reports this
honestly by hard-coding
`artifact_intake_completed_before_destructive_teardown = False`.

This slice therefore took **Outcome 2** of the CB-025 brief's Section G. No
bridge was built, because every available bridge is a material change to
CB-022 or CB-023 and a security decision that deserves its own reviewed slice
behind its own human stop:

* a writable bind mount or named volume for `/workspace` would **weaken**
  the enforced single-read-only-mount and read-only-rootfs containment;
* a `docker cp` before teardown would add a new host-write egress path to the
  first-automated-worker-execution slice, and would in any case recover
  nothing, because the tmpfs is already unmounted by the time the container
  has exited;
* promoting worker stdout into the artifact channel would make a
  worker-authored envelope the source of the artifact set and would rewrite
  the CB-023 intake contract.

What CB-025 does prove is therefore precise:

* the **identity and authority chain** is complete, exact, and fail-closed;
* the **content** of the quarantine package is not provably the container's
  output, because CB-022 never extracted it.

The proof records this as machine-readable, immutable state:

```
artifact_intake_ordering_proven      = False
artifact_content_provenance_proven   = False
known_limitations                    = ("artifact_intake_ordering_unproven",
                                        "fixture_scoped_acceptance_rule")
```

Construction of a proof receipt that reports `artifact_intake_ordering_proven
= False` *without* the matching limitation code raises. The two provenance
booleans must agree. Nothing marks
`artifact_intake_completed_before_destructive_teardown = True`.

**Closing this gap is the next slice's work**, not this one's: it needs a
reviewed artifact-egress design for CB-022/CB-023 that keeps the single
read-only mount and read-only rootfs intact.

### Second known limitation

The acceptance rule is fixture-scoped (`fixture_scoped_acceptance_rule`). It
checks exact bytes at the task's expected paths for one tiny task. It is not
a general correctness verifier, and it does not run tests, lint, or gates —
that is CB-026 through CB-029.

### Trust model note

Like CB-022, CB-023 and CB-024, the CB-025 evidence types gate construction on
module-private factory tokens. That defends against accidental and
cross-module fabrication, not against arbitrary code already executing inside
this process. The proof's independent re-derivation of both gates is a
stronger, digest-based defense layered on top of it.

## Negative controls

The CB-025 suite requires the chain to reject cheating, not merely to accept
success.

1. **Working output is not enough if the worker crossed the fence.** A worker
   produces the genuinely correct `value.txt` (`2\n`) *and* an unauthorized
   `sneaky.txt`. The verifier really does pass on the desired file. The
   blast-radius gate rejects anyway, verifier success does not override it,
   and the proof is `rejected_blast_radius` — not eligible for human approval
   as a candidate.
2. **A worker claiming "tests passed" cannot verify itself.** The worker's
   stdout carries `{"reported":"all tests passed","result_verified":true}` and
   the artifact is wrong. The claim is present in the untrusted output channel
   on the execution receipt and changes nothing: the verifier fails and the
   proof is `rejected_verification`.
3. **Exceeding the bounded artifact count** is rejected even when every path
   is individually allow-listed.

## Tests

`tests/test_continuous_builder_trust_chain_proof.py` — 31 tests, all driving
the real merged CB-022/023/024 code paths (CB-022 against the existing fake
Docker CLI used by its own suite). Coverage:

* successful tiny contained trust-chain proof
* exact binding across execution, supervision, breaker, quarantine, blast
  radius, verifier and proof
* unauthorized extra artifact -> blast-radius rejection (negative control)
* bounded artifact count exceeded -> rejection
* "tests passed" worker claim cannot produce verification (negative control)
* wrong artifact contents -> verification failure
* missing expected artifact -> verification failure
* `termination_uncertain` blocks the proof
* `cleanup_uncertain` blocks the proof
* failed execution -> `rejected_runtime`
* artifact security rejection blocks the proof, and rejected artifacts cannot
  carry downstream evidence
* stale / mismatched request, attempt, execution and quarantine identity
  rejected across the gate, verifier and proof
* supervision that never observed the artifact intake receipt is rejected
* forged blast-radius, verifier, task and proof receipts rejected — including
  a forgery whose own digest was recomputed to be self-consistent
* every evidence object immutable and byte-bounded
* a successful candidate holds zero merge / publication / GitHub / queue /
  Main authority
* the unproven artifact ordering is recorded honestly
* proofs are deterministic and content-addressed over their evidence
* the four new modules import no subprocess, socket, HTTP, Docker, database,
  or GitHub facility, contain no file I/O, and the verifier references no
  worker-authored output attribute
