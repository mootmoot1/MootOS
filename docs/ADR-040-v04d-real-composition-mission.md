# ADR-040 — V0.4D proves bounded composition through existing registered tools

## Status

Accepted for implementation. Recorded September 3, 2026, after completion of
the offline V0.4C trust architecture.

## Context

V0.3B can classify a goal as a candidate composition when more than one
required capability is installed. It deliberately does not prove that those
capabilities can exchange data or accomplish the goal together. V0.4D closes
that gap with one real, bounded mission through the existing Tool System.

Older V0.4B/V0.4C plans described a Local Companion and automatic Codex
dispatch. Current V0.4B/V0.4C instead implement an offline capability-build
workflow and PR trust chain. Those models are useful architectural precedent,
but they are not the V0.4D runtime path. The original local-file/cloud archive
example cannot run: no local-file or cloud-archive tools/connectors are
registered. Those capabilities require separate filesystem, credential,
connector, and external-write ADRs.

V0.4D therefore proves composition using tools resolved from the live Tool
Registry. The registry remains the only executable source of truth. V0.4D
reuses the existing validator, executor, budget, pending-operation, approval,
and Run infrastructure; it creates no parallel registry or executor.

## Decision

### Baseline mission

V0.4D will prove this user-level mission:

> Review current project activity and task status, consult relevant stored
> context, then prepare one appropriate follow-up task for human approval.

For this proof, “appropriate” has one deterministic meaning:

1. Read the project overview.
2. Select the project with the greatest number of open tasks.
3. Break ties by normalized project name.
4. Read both its status summary and its bounded set of open Tasks.
5. Search active memory using that exact project as query and project filter.
6. Prepare a bounded follow-up Task title from the selected project and the
   authoritative open-task count.
7. Stop at the existing frozen pending-operation boundary.

Both `tasks.status_summary` and `tasks.list` are required. The summary supplies
the authoritative open-task count used by later deterministic binding; the
list proves access to the actual bounded open-task set. Material disagreement
about the relevant open-task state fails closed.

Tool names shown here describe the current acceptance fixture only. Every plan
must resolve the live-registry equivalents of `projects.overview`,
`tasks.status_summary`, `tasks.list`, `memory.search`, and `tasks.create`, then
bind their current versions, schemas, risks, capabilities, and dependencies.

### What proves composition

Sequential calls alone are insufficient. Composition is proven only when:

- one user goal resolves to at least two independently useful registered read
  capabilities;
- earlier actual result data is mechanically bound into a later step;
- the terminal write arguments are deterministically derived from prior
  results and approved literals;
- exact registered tool names and versions are used;
- every call passes existing schema and risk validation;
- one mission-wide budget governs every processed request;
- actual executions have Run receipts;
- the internal write becomes an existing frozen pending operation and does not
  execute before approval; and
- mission state is derived from tool, Run, and operation receipts rather than
  model narration.

No mission-specific monolithic tool will be created.

### Data-flow bindings

An immutable composition proposal may use only:

- `LiteralBinding(value, source)`, where source is `user_goal` or
  `approved_mission_contract`; or
- `ResultBinding(source_step_id, field_path, transform)`, where the source and
  exact output field are declared before execution.

Transforms are a closed enumeration: exact copy, deterministic project
selection, integer-to-bounded-text formatting, and fixed title-template
interpolation. There is no eval, scripting, output-supplied template, or
free-form expression language.

Tool output is untrusted data. It cannot name a tool or executable capability,
change risk or schema, select an executor, add a step, expand a budget, or
grant approval. Extracted values must be bounded, type-checked, and validated
against the destination schema.

### Planning and registry binding

The proposal and feasibility-bound plan are immutable, bounded, deterministic,
and in-memory only. V0.4D adds no mission table or generalized persistent
workflow engine.

For each executable step the bound plan records tool name, version, risk,
input-schema digest, declared capabilities, and declared dependencies. These
facts form a deterministic registry snapshot identity. Immediately before
execution the runtime adapter must resolve the supplied live registry again
and fail closed if any bound authority-relevant fact changed. It must never
silently re-plan against new registry state. Capability IDs remain descriptive
and are never passed to execution; only exact registered tool names may become
`ToolRequest`s.

### Mission-wide budget and repeat protection

The proof has one five-request in-memory budget and intentionally no retry
capacity:

1. `projects.overview`
2. `tasks.status_summary`
3. `tasks.list`
4. `memory.search`
5. terminal `tasks.create` pending-operation request

Policy is maximum five processed requests, maximum two identical
tool/validated-argument signatures, and maximum two consecutive failures.
Denied and invalid processed requests consume budget. The terminal pending
write request also consumes budget even though it is not executed before
approval. Slice 3 models this requirement; Slice 4 must enforce it without
silently inheriting the current conversation loop's internal-write accounting
gap. No cross-process budget continuity is claimed.

Repeated-call identity is the deterministic digest of exact tool name and
validated arguments. It prevents an in-memory loop only; it is not durable
replay protection or external idempotency.

### Failure propagation

The baseline graph is linear. Any failed execution, malformed or missing
result, unresolved binding, registry mismatch, budget violation, or material
task-summary/task-list disagreement terminates or blocks the mission. All
dependent steps become not attempted. No fallback tool, re-plan, retry, or
model assertion can override failure.

### Write and approval boundary

The terminal `tasks.create` remains `internal_write`. V0.4D materializes and
validates its exact arguments, revalidates registry version/risk/schema, calls
the existing `create_pending_operation`, records `approval_pending`, and
returns. It does not create a Task or a tool Run at this point. Only the
existing `approve_operation` flow may execute the frozen request. Any argument
mutation requires a new operation and approval. There is no automatic write
approval and high-risk tools remain prohibited.

### Continuation and status

Initial V0.4D has no generalized continuation or resume after approval. The
write is terminal. A later receipt may read the independently durable operation
and Run outcome without resuming model reasoning or executing another step.

Mission statuses are mechanically derived: `not_started`, `planned`,
`feasible`, `running`, `approval_pending`, `completed`, `rejected`, `failed`,
`blocked`, or `expired`. Model narration cannot set or override status.

### Mission receipt

The bounded immutable receipt must include mission and goal identities, plan
and registry-snapshot identities, exact ordered tool names/versions, schema and
risk bindings, argument provenance, data-flow bindings, processed/executed
counts, repeat signatures, sanitized result fields actually used, read Run
IDs, pending-operation identity/status, terminal write Run/reference when one
exists, derived mission status, and safe failure classifications. It explicitly
states that mission persistence and generalized resume are unsupported.

It excludes raw prompts, provider continuation state, credentials, environment
data, unrestricted tool output, and database internals.

## Authority

V0.4D may coordinate already-registered tools, automatically use tools already
classified `read_only`, freeze one existing `internal_write` request, and allow
that exact request to execute only through existing human approval. It creates
no new underlying resource authority.

V0.4D does not introduce a second registry or executor, dynamic registration,
shell/root/arbitrary filesystem access, automatic approval, high-risk
execution, approval inheritance after mutation, background missions, unbounded
loops, credentials, GitHub execution, merge/deployment, capability
installation, Continuous Builder authority, retries, persistent mission state,
or generalized resume.

## Implementation sequence and approvals

1. This ADR and exact mission selection — no production behavior.
2. Pure immutable composition proposal — no resolution or execution.
3. Deterministic registry/policy/data-flow feasibility binding — no execution.
4. Separately approved runtime adapter — read-only execution, then stop at the
   frozen pending write.
5. Mission receipt, end-to-end proof, and documentation.
6. Optional post-approval continuation only after a separate future decision.

Slices 2–3 may share one controlled session but remain separate contracts and
commits. Human review is required before Slice 4. Existing approval remains
required for the exact frozen write. Final mission evidence requires human
review before V0.4D completion.

## Future decisions

New ADRs are required for persistent mission workflows, cross-process budgets,
durable replay/idempotency, retries and uncertain outcomes, filesystem tools,
Local Companion device authority, cloud connectors and credential ownership,
external-write rollback, background missions, or Continuous Builder
integration.
