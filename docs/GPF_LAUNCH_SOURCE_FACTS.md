# GP-F fixed-source currentness contract

This second slice implements source identity/currentness facts only. It does
not assert launch readiness, valid admission semantics, lifecycle eligibility,
human approval, lease safety, or execution success. Every authority flag is
False. No TrustedLaunchAuthorization is implemented.

## Fixed sources and tokens

The protected assignment module owns the fixed, initially unconfigured GP-D
root and product database constants. No caller can provide a root, connection,
or correlation callback. Human-reviewed deployment provisioning and coordinator
integration remain required; no production source is guessed or accessed.

TrustedLaunchFacts binds the exact immutable assignment, job, latest started
attempt, request and header. Its source_tokens tuple has this fixed order:

1. Assignment binding_sha256, reloaded and validated from the write-once source.
2. GP-D canonical manifest digest: raw byte digest, size and presence for header,
   events, attempts, leases, heartbeats, checkpoints, side effects and
   reconciliations, plus every recorded attempt's dispatch reservation. Absent
   and empty sources differ. Row integrity/job identity and event hash-chain
   continuity are checked; lifecycle transitions are not evaluated here.
3. Product canonical projection digest: columns and deterministically ordered
   rows of builder_blueprints, builder_slices, builder_events, builder_attempts
   and builder_leases for the whole assigned blueprint/version. Leases join
   through attempts. Whole-blueprint coverage conservatively includes other
   slices/dependencies. Fixed read-only SQLite transactions see committed WAL
   state; unreadable WAL or missing schema fails closed. No migration is added.
4. Current trusted-policy registry and GP-C policy-matrix identity digest.
   Header policy version, registry digest and policy snapshot must match live
   identities. This is not attestation of installed source-file bytes and does
   not independently re-evaluate the full admission decision.

Sources are bounded by bytes/rows. Product membership/version/digest is checked
against the immutable assignment. Allowed/forbidden scope, capability and budget
projections are bound by digests. Creation time is informational, never a source
revision proof.

Capture reads all source tokens, reads candidate identities, then reads tokens
again. Any mismatch fails closed. Revalidation rebuilds from original request
bytes and fixed sources, compares every substantive fact, checks the old seal,
and returns the fresh record. A caller-resealed modified object is not accepted
as bearer evidence. A snapshot may represent a blocked job: it grants nothing.

These are representation digests, not a global transaction or monotonic
revision counters. Same-content ABA changes cannot be distinguished by a digest;
append-only ownership is required for the GP-D/binding sources. A change after
revalidation returns is still possible. A future authority must revalidate at
its decision boundary; eventual one-shot invocation needs its own consumption
and race contract. Never persist this snapshot as permission to execute later.

## Protected closure

New component cb_launch_facts_source / worker_authorization / human_only /
system_owned_launch_facts_currentness protects gpf_launch_facts.py. Humans review
code changes; system invocation does not require manual record construction.

Cumulative delta from f51b399: two paths, two components; 17 paths / 13 components.
Registry digest: b23b086b640bbde70cb73f23ee4a3b1ff6973888e8dbe69359fed928dcbfa9bf.

Binding imports only standard library. Facts additionally imports binding and
the already-protected GP-C admission core and trusted policy. Their complete
local import closure is gpf_launch_facts, gpf_launch_candidate_binding,
gpc_trusted_admission_core, trusted_policy, paths and text_safety. An AST test
checks that exact closure. No cryptography/private key, network, provider,
worker, Context Engine or System Model enters this new closure.

## Next authority stop

Do not directly import the existing F4 preparation/supervisor/GP-E validators
into this boundary: their transitive local closure is 28 modules and includes
Context Engine and System Model. The user explicitly forbids that expansion.
A correct consumer also cannot replace those validators with a digest comparison
or trust caller-derived lifecycle/admission objects.

The next reviewable design is extraction of a minimal semantic validation kernel
for the already-bound raw GP-D, product and admission projections, followed by
a trusted launch consumer that rechecks the original signed receipts and fresh
source tokens. Specify exact event/lifecycle rules, admission decision inputs,
lease/reconciliation rules, and one-shot authorization consumption before
registering it. Keep original GP-B/C/D/E validation behavior in parity tests;
do not duplicate a partial state machine and call it authoritative.

This slice therefore stops before commit 3. Full TrustedLaunchFacts eligibility
and authenticated-gate projection remain unfinished. launch_authorized=True
cannot be produced by these modules. Existing F4 remains false as well.

F10 must enforce coordinator-only binding-store access and deny ordinary workers
/Users/freeman/.mootos and unrestricted host-home access. Unix 0600 alone is not
same-user isolation. No worker or provider was run; no private key was accessed.
