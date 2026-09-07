# GP-F launch facts: source tokens and authoritative binding stop

Resume: 871dd66df7b692d48878fe4ba4ee2a18298e65e8.
This is a design contract, not an implemented facts factory or authorization API.
No cross-store transaction, launch, schema migration or TCB addition is made.

## Accepted currentness contract

Use fixed system-owned source locations, selected by protected configuration at
system initialization. Callers name job/attempt/request IDs and provide original
approval proofs; they cannot supply a ledger root, SQLite connection/path,
correlation callback, clock, source implementation or an authenticated boolean.

Capture tokens from each source, read facts, then capture fresh tokens again.
Require before == after for every source. Before evaluating launch authority,
repeat source reads with fresh SQLite snapshots and compare every bound token.
Any mismatch is facts_stale=True and no authorization; rebuild facts. Missing,
malformed, oversized, inconsistent, unavailable or ambiguous source records fail
closed. Recompute the facts and compare their canonical content too: a matching
source-token dictionary does not authenticate caller-modified facts.

The record is evidence, never a bearer capability. Facts construction and
revalidation grant no launch, dispatch, queue, GitHub, merge or worker-result
trust. Recheck lease and approval expiry against authoritative current time at
consumption, even if source bytes did not change.

This detects changes in the bound source representations. It is not a global
atomic transaction, and digest equality cannot prove that an unrestricted
writer never changed data and restored it. GP-D append-only/immutable source
rules and source-owner isolation are prerequisites. A later executor must again
check currentness immediately before dispatch; this slice does not close the
post-authorization execution race or make an authorization reusable.

## Deterministic GP-D token

For the selected job, hash a canonical, domain-separated manifest of exact file
names, existence, byte lengths and SHA-256 of bounded raw bytes:

- header.json
- events.jsonl
- attempts.jsonl (all attempts, not just the selected one)
- leases.jsonl
- heartbeats.jsonl
- checkpoints.jsonl
- side_effects.jsonl
- reconciliations.jsonl
- attempts/<attempt_id>/dispatch_reservation.json for every recorded attempt

Missing optional files have an explicit absent marker, distinct from empty
files. Required files missing block. Attempt enumeration is repeated with the
manifest so a new retry or reservation cannot be omitted. Reject traversal,
symlinks and unexpected source layouts; never follow arbitrary request paths.

Raw-byte coverage catches changed records even if embedded digests are stale.
The facts derivation must separately validate record digests, sequence/previous
hash chains, job/attempt identity, transitions, cancellation, unknown execution,
reconciliation, lease ambiguity, heartbeats and reservation replay/conflict.
Hashing records alone does not validate their semantics. Cached supervisor and
preparation records are not authoritative token sources.

No filesystem timestamp is used as revision proof. Timestamps retain their
separate meaning for expiry and time-based blockers.

## Fixed read-only product projection

Use sqlite3 directly, with a fixed database URI opened mode=ro, query_only=ON,
and bounded parameterized SELECTs. Do not import backend.db (environment-selected
paths), queue/projection objects, or product writers into the trusted reader.
Do not use immutable=1 with a live database or hash just the SQLite main file:
committed WAL contents must be visible.

Within a short SQLite read transaction collect deterministic ordered rows for:

- builder_blueprints: the exact blueprint version/content digest/canonical data;
- builder_slices: the exact slice/version and declared dependency identities;
- builder_events: the relevant ordered event chains, including dependencies;
- builder_attempts and builder_leases: relevant product-plane occupancy facts.

SHA-256 of a versioned canonical projection is the product content token. Include
row identities and all fields interpreted by eligibility checks. Verify declared
content/event digests and lifecycle transitions independently. Duplicate,
missing or ambiguous identities block. Never infer GP-D execution from product
ready/building/done. A new read transaction is mandatory on each token pass;
reusing one transaction would hide intervening commits.

SQLite data_version is connection-local and not a portable persisted revision.
It may supplement a live reader but cannot replace the deterministic row token.
A global max(sequence) is also insufficient: sequences are scoped to slices.

## Concrete missing authoritative fact

The existing schema can prove blueprint existence, slice membership, versions,
product lifecycle and product leases. It CANNOT prove the expected product slice
for a GP-D job/request:

- DurableJobHeader has no blueprint_id, slice_id or product-assignment reference.
- builder_blueprints/builder_slices/builder_events have no GP-D job_id/request_id.
- builder_attempts binds product attempts to slices, not GP-D jobs. Equal-looking
  IDs do not establish a cross-plane relationship (ADR-044).
- SliceJobCorrelation is created from caller-supplied product IDs and a header;
  its seal is integrity evidence, not authoritative assignment.
- No fixed production correlation implementation or authoritative mapping writer
  was found in the targeted backend/scripts searches.

Therefore a read-only projection cannot truthfully set
product_correlation_verified=True for the expected job-to-slice assignment.
Checking that caller-selected IDs happen to exist would recreate the original
callback trust bug in SQL. A human signature proves approval of receipt bytes;
it must not silently become a new product-assignment authority.

## Smallest proposed addition requiring review

Introduce one immutable, system-owned LaunchCandidateBinding at the point where
the product scheduler creates a GP-D job/request. Suggested exact contents:

- schema_version
- job_id, header_sha256, attempt_id
- request_id, request_sha256
- blueprint_id, blueprint_version, blueprint_sha256
- slice_id, slice_version
- admission_decision_id, admission_decision_sha256
- binding_sha256

The source location and writer must be fixed and protected; workers cannot mint,
replace or select an alternate binding. Bind the exact admission bytes by their
existing header digest; current policy/TCB drift blocks until explicit readmission.
New attempts/requests need new bindings. No identity collapse between queue and
GP-D attempts. Product state continues to come exclusively from product storage.

Prefer a small append-only sidecar owned by the system scheduler over a SQLite
migration, but this is a NEW authoritative writer/storage contract, not a
read-only projection of existing truth. Its creation authority and write-once
semantics need review before implementation. A digest-only public factory or
caller-provided “trusted” mapping is not an acceptable substitute. The current
runtime has no deployed fixed GP-D root/binding-source configuration to reuse.

Candidate closure after resolving that owner:

1. gpf_launch_facts.py: fixed sources, bounded parsers, tokens and revalidation;
2. gpf_product_correlation.py only if separating bounded SQL improves review;
3. gpf_launch_authority.py: reverify original signatures and exact current facts.

Use human_only for cb_launch_facts_source and cb_worker_launch_authority: the
policy governs who may change code, not who invokes it. Target imports are
stdlib, the existing protected signature verifier, and only the required
already-protected GP-C policy queries. No Context Engine, System Model, GP-E
object stack, worker/runtime/provider/network imports. If the new binding writer
or independent state validation requires extra protected surfaces, enumerate
them for approval rather than concealing them behind an adapter. No registry
membership or future digest is asserted until that exact closure is known.

Required launch checks remain all current F1-F4 blockers, strict gate/receipt
identity, approval validity, scope/capability ceilings, forbidden scope,
policy/admission compatibility and reservation replay prevention. A narrower
approval cannot authorize the wider original WorkerRequest: bind a new narrowed
request where needed. All unrelated authority flags remain False.

## F10 hard requirement: human key isolation

Ordinary workers MUST NOT have filesystem access to /Users/freeman/.mootos or
unrestricted host-home access. Mode 0600 is NOT isolation from same-user worker
processes. The sandbox/capability broker must exclude the entire directory and
all aliases/mount paths exposing it, and must not provide a signing/key-reading
capability. F10 must verify denial from inside the actual worker environment,
including same-user and symlink/mount escape cases, before any real launch.
Do not read the real private key to test denial; use an equivalent synthetic
canary under the excluded boundary. Sandbox authority is unchanged in this slice.

## Status

This contract resolves the requested token design without inventing atomicity.
Implementation stops at the absent authoritative product-to-job assignment and
its required new writer. No TrustedLaunchFacts or TrustedLaunchAuthorization
is minted; launch_authorized remains False. The enrollment key is untouched.
