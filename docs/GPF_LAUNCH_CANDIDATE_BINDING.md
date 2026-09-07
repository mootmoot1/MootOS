# GP-F authoritative launch assignment

This slice implements identity assignment only. It never establishes lifecycle
eligibility, human approval, dispatch, launch, publication, or result trust.

## Ownership and provisioning

`gpf_launch_candidate_binding.py` is the coordinator's authoritative writer and
fixed-source reader. `_AUTHORITATIVE_ROOT` and `_PRODUCT_DATABASE` are protected
configuration constants, initially None. Unprovisioned calls fail closed. No
caller root/path/connection/correlation callback or environment override exists.
Real source paths must be explicitly provisioned through human review; this
slice does not guess a deployment root or access any production store.

The trusted coordinator supplies its selected blueprint/version/slice and the
canonical request packet as assignment input. The writer reloads the GP-D
header and complete attempt chain, verifies the latest started attempt, exact
deterministic request ID, request/header/attempt digests, contract/admission
references, repository/base, scope/capability/gate and budget ceilings. Product
membership and immutable version/digest identifiers come from fixed read-only
parameterized SQLite queries against builder_blueprints joined to builder_slices.
This source owns those identities; no lifecycle interpretation is performed.
No private key, approval receipt, or worker claim creates assignment truth.

This is a runtime authority API, not an untrusted worker endpoint. Python
constructor privacy cannot authenticate who invokes it. F10 must enforce that
only the system coordinator can invoke it or access the authoritative root.
The current repository has no deployed coordinator dispatch flow to wire: future
integration MUST call assign_launch_candidate successfully BEFORE downstream
dispatch preparation. Assembly of a non-authoritative WorkerRequest is not
launch eligibility; the existing F4 preparation continues to forbid launch.
A writer exception, including durability failure, must keep the request
ineligible. Do not add a “later attach assignment” compatibility fallback.

## Record and storage

Fixed layout:

    <protected authoritative root>/launch_bindings/<job_id>/<request_id>.json

GP-D source files remain under the same configured root's jobs/<job_id>/ tree.
Product SQLite remains separate product truth. No schema migration is added.

Exact identity fields: schema_version, job_id, header_sha256, attempt_id,
request_id, request_sha256, blueprint_id, blueprint_version, blueprint_sha256,
slice_id, slice_version, admission_decision_id, admission_decision_sha256,
created_at, binding_sha256. created_at is the coordinator's stable assignment
creation time, supplied again unchanged on replay; it is not a revision token.

The canonical record also has structurally false launch, dispatch, publication,
GitHub, merge, Main advancement, queue transition, result-trust and worker-output
trust flags. Its digest covers the body excluding binding_sha256. Records are
not bearer authority; consumers load them again from the protected source.

Paths use bounded identifiers and descriptor-relative traversal with O_NOFOLLOW.
Directories/files must be owned by the coordinator OS user and not group/world
writable. Symlinks, nonregular files, hard-linked records, malformed data,
noncanonical bindings, incorrect path identities and conflicting content fail.
Root ancestors are traversed without following symlinks. Source ownership and
worker exclusion remain necessary against same-user hostile path replacement.

Publication writes a private temporary file, flushes/fsyncs it, atomically links
it into the final name with create-if-absent semantics, removes the temporary
name and fsyncs the directory. No replace() overwrite is used. A loser in a race
must validate the existing record and compare exact bytes. Identical content is
idempotent replay; different content permanently conflicts while the write-once
source exists. Malformed existing files are never repaired or overwritten.
A crash leaving a temporary hard link may make reads fail closed (nlink != 1);
human recovery is required. This intentionally favors refusal over ambiguous
recovery or dispatch. Filesystem writers must support hard links and directory
fsync; unsupported operations fail closed.

Source identities are reread before returning success. This is not a cross-store
transaction, and the historical binding does not freeze future lifecycle state.
Fresh facts/currentness checks remain required immediately before authorization.

## TCB and validation

One new component: cb_launch_assignment_authority / worker_authorization /
human_only / system_owned_launch_candidate_assignment. One protected path:
backend/continuous_builder/gpf_launch_candidate_binding.py.

Registry at this commit: 16 paths / 12 components;
9fbe94a110e527cf48ab91a0feb38c0b90515facc22cf55ff585852ed938b108.
Import closure is standard library only. No GP-E, Context Engine, System Model,
GP-D object graph, provider, worker runtime, network client or cryptography import.

Focused tests use temporary file-backed GP-D sources and temporary SQLite only.
Coverage includes initial durable assignment, exact replay, permanent conflict,
concurrent conflict, stale/mismatched requests/attempts/headers/admission,
product membership, traversal/symlinks, malformed records, file types, durability
failure, fixed source signatures and zero authority.

F10 hard requirement: workers must have no access to the authoritative root,
the assignment capability, /Users/freeman/.mootos, or unrestricted host home.
0600 does not isolate same-user processes. Verify actual sandbox/broker denial
using synthetic canaries before real execution. No real key is read by this slice.

Validation: 61 focused tests and 922 targeted regressions passed. Full flake8
for new code and repository blocking flake8 passed.
