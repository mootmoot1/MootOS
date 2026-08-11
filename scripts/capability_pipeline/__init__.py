"""V0.3E manual capability-build pipeline tooling.

This package is offline, developer-facing tooling for turning a V0.3B Gap
Report into a validated, human-reviewable capability specification and
walking it through an explicit, human-controlled lifecycle -- it is not
part of the running MootOS application and is never imported from
``backend/``. See ``docs/CAPABILITY_BUILD_PIPELINE.md`` for the full
manual workflow this package supports.

**Core invariant, enforced structurally, not by convention:** nothing in
this package can register a tool, execute a tool, approve an operation,
or otherwise install anything. A ``CapabilitySpec`` and a
``CapabilityRecord`` are inert data -- validated, serializable, and
reviewable, but never executable. The only way a capability becomes real
is the same path every MootOS tool has always used: an explicit
``registry.register(...)`` call inside ``backend/tool_registry.py``,
written and reviewed by a human, merged through the normal PR process.
See ``docs/CAPABILITY_ARCHITECTURE.md`` Sec2 and Sec6 (V0.3E).

Modules:

- ``spec`` -- ``CapabilitySpec``: the machine-readable, schema-validated
  proposal for one capability, fail-closed on anything malformed,
  inconsistent, or missing.
- ``lifecycle`` -- ``CapabilityRecord`` and the explicit, human-invoked
  state transitions (``proposed`` -> ... -> ``ready_for_pr`` ->
  ``merged``). No automatic transitions exist anywhere in this module.
- ``review`` -- ``AdvisoryReview``: a structured record for one of the
  three advisory review roles (correctness, security, architecture).
  Attaching a review never changes lifecycle state.
"""
