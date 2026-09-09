# GP-F readiness and one-shot dispatch consumption

Resume: 31e73ba (trusted dependency hardening).

Two records and one boundary, none of which carry authority. No worker or
provider is invoked, no credential or private key is touched, and
`TrustedLaunchAuthorization` is still deliberately not implemented.

## Eligibility is not readiness

`TrustedLaunchEligibility` means "no trusted semantic blocker currently
prevents this candidate". That meaning is unchanged by this slice.

`TrustedLaunchDispatchIntent` means something strictly narrower: "the trusted
coordinator selected this exact candidate for the next dispatch opportunity".
Neither implies the other. Recording intent for a currently blocked candidate
is allowed and meaningless, because consumption re-decides eligibility against
fresh sources. Keeping them orthogonal is what stops readiness from quietly
becoming a second, weaker eligibility check.

## Readiness record

Bound fields: `schema_version`, `intent_id`, `job_id`, `attempt_id`,
`request_id`, `request_sha256`, `binding_sha256`, `reservation_sha256`,
`source_tokens_sha256`, `coordinator_decision_id`,
`coordinator_decision_sha256`, `issued_at`, `expires_at`, `intent_sha256`,
plus the standard false-flag vocabulary. Every authority flag is structurally
False.

`intent_id` is derived deterministically from the bound values, so an exact
replay reproduces byte-identical bytes and is idempotent, while any changed
field becomes a *conflict* rather than a silent second readiness for the same
slot.

### Writer ownership

`record_launch_dispatch_intent(facts, request_bytes, coordinator_decision_id,
coordinator_decision_sha256, issued_at, ttl_seconds)` is the only mint.

- Every bound value is rebuilt inside the writer from fresh authoritative
  sources via `project_launch_state`. The caller supplies only *which*
  coordinator decision selected the candidate and *how long* the window is.
- There is no `root`, `store`, `projection`, `clock` or `now` parameter, so a
  worker cannot point it at another candidate, another store, or a longer
  window. Tests assert `TypeError` for each.
- Storage is `<AUTHORITATIVE_ROOT>/launch_intents/<job_id>/<request_id>.json`,
  write-once via `O_EXCL` + `link()`. It is a sibling of `jobs/`, so recording
  readiness does not perturb the GP-D manifest token and cannot invalidate the
  facts it was derived from.
- A retry is a new `attempt_id`, hence a new `request_id`, hence a different
  slot. Readiness cannot be replayed onto a retry structurally.
- Readiness requires a durable dispatch reservation to already exist.
- `ttl_seconds` is bounded at 900s and `issued_at` must be within 120s of the
  process clock, so an issuer cannot backdate or postdate its way to a
  long-lived intent.
- No caller callback is accepted anywhere.

The supervisor is *not* pulled into the TCB. Only the minimal readiness fact
is projected through this narrow protected writer; the coordinator's own
decision logic stays outside and is referenced only by
`coordinator_decision_id`/`_sha256`.

## Why readiness does not pin source tokens at consumption

The intent records `source_tokens_sha256` as evidence of what it was selected
against. Consumption compares immutable *candidate identity* — job, attempt,
request, request digest, binding, reservation — and expiry, but not token
equality.

Requiring token equality was implemented first and rejected: it collapses "a
semantic blocker appeared" into "any byte moved", so an ordinary heartbeat
voided readiness while a cancellation reported the same coarse error, and the
semantic checks were never actually reached. Safety does not depend on that
equality, because consumption re-decides eligibility against the sources as
they are *now*, and the narrow expiry bounds how stale a selection may be.
Both behaviours are pinned by tests.

## One-shot consumption

`LaunchAuthorizationConsumption` binds `authorization_id`, `job_id`,
`attempt_id`, `request_id`, `request_sha256`, `authorization_sha256`,
`dispatch_intent_sha256`, `reservation_sha256`, `source_tokens_sha256`,
`consumed_at`, `consumption_sha256`, plus false flags. It is a *spent-marker*,
not a capability: holding one is not permission to invoke anything.

`consume_launch_authorization` executes in this exact order:

1. rebuild facts and lifecycle from fresh authoritative sources;
2. revalidate the exact readiness intent, including expiry;
3. re-decide eligibility — a cancellation, `execution_unknown`,
   reconciliation, stall, timeout or superseded attempt that appeared after
   authorization blocks here, with its blocker codes;
4. atomically record consumption, create-if-absent, fsynced before it is
   observable;
5. re-verify (1)–(3) after the write and refuse dispatch on drift.

Slot: `<AUTHORITATIVE_ROOT>/launch_consumptions/<job_id>/<request_id>.json`,
one per request. This enforces "at most one dispatch ever for this exact
request". Unlike the write-once assignment store, a byte-identical replay is
**refused**, not treated as benign: a replay is a second attempt to spend a
spent opportunity.

### Rules, all covered by tests

first valid consumption succeeds; identical replay after consumption fails; a
different authorization cannot spend the same slot; a changed request fails; a
retry/new attempt has no readiness and no marker of its own; expired intent
fails; stale caller-held facts fail; cancellation before consume fails;
`execution_unknown` before consume fails; reconciliation before consume fails;
a missing human gate fails.

### Authorization is bound but not yet verified

`TrustedLaunchAuthorization` does not exist, so `authorization_id` and
`authorization_sha256` are opaque values bound into the record and **not**
verified. This module therefore proves one-shot-ness, readiness and
currentness — not that an authorization was ever issued. That is stated
plainly rather than implied, and it is the remaining piece the authority slice
must supply.

## Post-authorization race analysis

The race is authorize → system changes → dispatch. Analysed by window:

**W0, concurrent consumers.** `link()` into a fixed name is atomic on POSIX,
so exactly one caller wins and every other caller gets `LaunchAlreadyConsumed`.
This window is closed. The directory is fsynced immediately after the link, so
a crash cannot lose the marker and let the opportunity be spent twice after
restart.

**W1, between the step-3 decision and the step-4 durable write.** Sources can
move here. Mitigated by step 5: after the write we re-derive facts, intent and
verdict, and on any drift raise `LaunchConsumptionDrift`. That exception
carries `consumption_recorded = True` — the opportunity is spent and **dead**,
nothing was dispatched, and the caller must open a new GP-D attempt rather
than retry. A burned opportunity with nothing executed is safe; dispatching
against moved sources is not. Residual safety risk: none. Residual cost: a
wasted opportunity.

**W2, between the durable spend and the actual worker invocation. NOT CLOSED.**
File-backed storage cannot make "the marker is durable" and "the worker was
invoked" a single atomic step, and this slice does not pretend otherwise.

- Crash after the marker is durable but before invocation: opportunity spent,
  nothing ran. Safe; the job needs a new attempt.
- Crash *during* invocation, or any outcome where the invocation receipt is
  uncertain: it is unknown whether a worker started. **`execution_unknown`
  must be declared in GP-D.** This is the mandated fallback and the reason
  `execution_unknown` is an unconditional blocker everywhere else in GP-F.

W2 is the documented uncertainty window. It is a property of the storage
substrate, not of this design, and it is why authorization alone is explicitly
never sufficient for dispatch.

**W3, receipt intake.** Out of scope; no executor exists. The same rule
applies: uncertain receipt means `execution_unknown`, never assumed success.

## TCB delta

Two components, two paths, both `worker_authorization` / `human_only`:

- `cb_launch_dispatch_intent` / `system_owned_dispatch_readiness` →
  `gpf_launch_dispatch_intent.py`
- `cb_launch_consumption` / `one_shot_dispatch_consumption` →
  `gpf_launch_consumption.py`

Cumulative: **28 protected paths / 20 components**.
Registry digest: `89faaa9cab36a21d33c792f8692a9f9982c4e83587ac2e9d1c1d64ff117b47eb`.

Closure of `gpf_launch_consumption` is 16 modules — the 14 of the semantic
kernel plus these two — and every member is now a protected path. No Context
Engine, System Model, GP-E object stack, `gpd_job_store`/`gpd_recovery`,
supervisor graph, worker runtime, provider SDK or network code enters it.

## Is TrustedLaunchAuthorization safe to implement next?

Both preconditions are now met: the trusted dependency closure is fully
protected, and the readiness plus one-shot consumption boundary is specified
and implemented with its uncertainty window stated. The remaining work is
narrow and additive: mint an authorization record from binding + current facts
+ eligibility + intent + authenticated approvals, and have
`consume_launch_authorization` verify it instead of accepting an opaque digest.

The executor remains a separate, later boundary. Building it requires the W2
fallback to be wired into GP-D — an executor that cannot declare
`execution_unknown` on an uncertain invocation must not be written.
