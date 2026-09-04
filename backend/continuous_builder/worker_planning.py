"""Read-only bridge from durable Chief Builder evidence to inert actions."""

import hashlib
import json
from dataclasses import dataclass

from backend.db import connect

from .chief_builder import ChiefBuilderPlanningReceipt
from .leases import inspect_lease
from .queue_projection import replay_slice
from .readiness_bridge import derive_dependency_receipts
from .worker_action import (
    InertWorkerLaunchAction, prepare_worker_launch_action,
)
from .worker_authorization import (
    WorkerDispatchAuthorization, authorize_worker_dispatch,
)
from .worker_provider import (
    WorkerMatch, WorkerRequirement, match_worker,
)
from .worker_request import FrozenWorkerRequest, create_frozen_worker_request


class WorkerPlanningError(RuntimeError):
    """Raised when durable planning evidence cannot prove inert dispatch."""


MAX_RESULT_BYTES = 512 * 1024


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class WorkerPlanningResult:
    planning_receipt: ChiefBuilderPlanningReceipt
    selected_slice_id: str
    durable_projection_digest: str
    durable_dependency_receipt_ids: tuple
    lease_id: str
    lease_owner_id: str
    worker_match: WorkerMatch
    worker_request: FrozenWorkerRequest
    dispatch_authorization: WorkerDispatchAuthorization
    launch_action: InertWorkerLaunchAction
    result_digest: str
    durable_state_changed: bool = False
    queue_transition_performed: bool = False
    worker_launched: bool = False
    execution_performed: bool = False

    def __post_init__(self):
        if not isinstance(self.planning_receipt, ChiefBuilderPlanningReceipt):
            raise WorkerPlanningError("Chief Builder receipt is invalid")
        if self.selected_slice_id not in (
            self.planning_receipt.recommended_slice_ids
        ):
            raise WorkerPlanningError("selected slice is not recommended")
        if not isinstance(self.worker_match, WorkerMatch) or (
            self.worker_match.status != "matched"
        ):
            raise WorkerPlanningError("worker match is invalid")
        if not isinstance(self.worker_request, FrozenWorkerRequest) or (
            self.worker_request.slice_blueprint.slice_id
            != self.selected_slice_id
        ):
            raise WorkerPlanningError("worker request binding is invalid")
        if not isinstance(
            self.dispatch_authorization, WorkerDispatchAuthorization
        ) or not self.dispatch_authorization.authorized:
            raise WorkerPlanningError("dispatch authorization is invalid")
        if not isinstance(self.launch_action, InertWorkerLaunchAction):
            raise WorkerPlanningError("inert launch action is invalid")
        if (
            self.dispatch_authorization.request != self.worker_request
            or self.dispatch_authorization.worker != self.worker_match.worker
            or self.launch_action.authorization != self.dispatch_authorization
        ):
            raise WorkerPlanningError("worker chain binding mismatch")
        if self.worker_request.attempt_id != self.launch_action.attempt_id:
            raise WorkerPlanningError("attempt binding mismatch")
        if self.lease_owner_id != self.worker_match.worker.worker_id:
            raise WorkerPlanningError("lease owner does not bind worker")
        if any(
            value is not False for value in (
                self.durable_state_changed, self.queue_transition_performed,
                self.worker_launched, self.execution_performed,
            )
        ):
            raise WorkerPlanningError(
                "planning adapter cannot claim execution"
            )
        if self.result_digest != hashlib.sha256(self._payload()).hexdigest():
            raise WorkerPlanningError("planning result digest mismatch")
        if len(self.canonical_bytes()) > MAX_RESULT_BYTES:
            raise WorkerPlanningError("planning result exceeds byte bound")
        object.__setattr__(
            self, "durable_dependency_receipt_ids",
            tuple(self.durable_dependency_receipt_ids),
        )

    def _body(self):
        return {
            "dispatch_authorization_digest": (
                self.dispatch_authorization.authorization_digest
            ),
            "durable_dependency_receipt_ids": list(
                self.durable_dependency_receipt_ids
            ),
            "durable_projection_digest": self.durable_projection_digest,
            "durable_state_changed": False,
            "execution_performed": False,
            "launch_action_digest": self.launch_action.action_digest,
            "lease_id": self.lease_id,
            "lease_owner_id": self.lease_owner_id,
            "planning_receipt_digest": self.planning_receipt.receipt_sha256,
            "queue_transition_performed": False,
            "selected_slice_id": self.selected_slice_id,
            "worker_descriptor_digest": (
                self.worker_match.worker.descriptor_sha256
            ),
            "worker_launched": False,
            "worker_request_digest": self.worker_request.request_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["result_digest"] = self.result_digest
        return _canonical(value)


def _durable_sources(database_path, planning, selected_slice_id, lease_id,
                     observed_at):
    parsed = (
        planning.priority_analysis.conflict_analysis.dependency_analysis
        .parsed_blueprint
    )
    blueprint = parsed.blueprint
    connection = connect(database_path)
    try:
        stored_blueprint = connection.execute(
            "SELECT content_digest, canonical_json FROM builder_blueprints "
            "WHERE blueprint_id=? AND blueprint_version=?",
            (blueprint.blueprint_id, blueprint.blueprint_version),
        ).fetchone()
        stored_slice = connection.execute(
            "SELECT slice_version, canonical_json FROM builder_slices "
            "WHERE blueprint_id=? AND blueprint_version=? AND slice_id=?",
            (blueprint.blueprint_id, blueprint.blueprint_version,
             selected_slice_id),
        ).fetchone()
        lease = connection.execute(
            "SELECT l.*, a.blueprint_id AS attempt_blueprint_id, "
            "a.blueprint_version AS attempt_blueprint_version, "
            "a.slice_version AS attempt_slice_version "
            "FROM builder_leases l JOIN builder_attempts a "
            "ON a.attempt_id=l.attempt_id WHERE l.lease_id=?",
            (lease_id,),
        ).fetchone()
    finally:
        connection.close()
    if stored_blueprint is None or (
        stored_blueprint["content_digest"] != parsed.content_sha256
        or stored_blueprint["canonical_json"] != parsed.canonical_json
    ):
        raise WorkerPlanningError("durable blueprint binding mismatch")
    by_id = {item.slice_id: item for item in blueprint.slices}
    selected = by_id.get(selected_slice_id)
    if stored_slice is None or selected is None or (
        stored_slice["slice_version"] != selected.version
        or json.loads(stored_slice["canonical_json"]) != selected.to_dict()
    ):
        raise WorkerPlanningError("durable slice binding mismatch")
    projection = replay_slice(
        database_path, blueprint.blueprint_id, blueprint.blueprint_version,
        selected_slice_id,
    )
    if projection.current_state != "scheduled":
        raise WorkerPlanningError("durable slice is not scheduled")
    lease_status = inspect_lease(database_path, lease_id, observed_at)
    if lease is None or lease_status.status != "active" or (
        lease["attempt_blueprint_id"] != blueprint.blueprint_id
        or lease["attempt_blueprint_version"] != blueprint.blueprint_version
        or lease["slice_id"] != selected_slice_id
        or lease["attempt_slice_version"] != selected.version
        or lease["released_at"] is not None
    ):
        raise WorkerPlanningError("active lease binding mismatch")
    receipts = derive_dependency_receipts(
        database_path, blueprint.blueprint_id, blueprint.blueprint_version,
        selected_slice_id,
    )
    if any(not item.authoritative or not item.passed for item in receipts):
        raise WorkerPlanningError("durable dependency readiness failed")
    return selected, projection, lease, tuple(
        item.receipt_id for item in receipts
    )


def plan_inert_worker_action(
    database_path, planning_receipt, selected_slice_id, lease_id, observed_at,
    descriptors, job, frozen_scope, handoff, worker_brief,
    authorization_input,
):
    """Revalidate durable evidence and prepare one inert action."""
    if not isinstance(planning_receipt, ChiefBuilderPlanningReceipt):
        raise WorkerPlanningError("Chief Builder receipt is invalid")
    planned = {
        item.slice_id: item for item in planning_receipt.planned_slices
    }.get(selected_slice_id)
    if planned is None or not planned.eligible or planned.blocked_reasons or (
        planning_receipt.recommended_slice_ids != (selected_slice_id,)
    ):
        raise WorkerPlanningError("Chief Builder plan is not eligible")
    selected, before, lease, receipt_ids = _durable_sources(
        database_path, planning_receipt, selected_slice_id, lease_id,
        observed_at,
    )
    if tuple(planned.dependency_receipt_ids) != receipt_ids:
        raise WorkerPlanningError(
            "planning dependency evidence is not durable"
        )
    requirement = WorkerRequirement(
        "bounded_code_change", selected.requested_capabilities, 1024,
        selected.budget.max_output_bytes,
    )
    worker_match = match_worker(requirement, descriptors)
    if worker_match.status != "matched" or (
        lease["owner_id"] != worker_match.worker.worker_id
    ):
        raise WorkerPlanningError("selected worker does not own the lease")
    parsed = (
        planning_receipt.priority_analysis.conflict_analysis
        .dependency_analysis.parsed_blueprint
    )
    request = create_frozen_worker_request(
        parsed, selected, job, frozen_scope, handoff, worker_brief,
        lease["attempt_id"], selected.requested_capabilities[0],
    )
    authorization = authorize_worker_dispatch(
        request, worker_match.worker, authorization_input,
    )
    if not authorization.authorized:
        raise WorkerPlanningError("dispatch authorization failed closed")
    action = prepare_worker_launch_action(authorization)
    after = replay_slice(
        database_path, parsed.blueprint.blueprint_id,
        parsed.blueprint.blueprint_version, selected_slice_id,
    )
    if after != before:
        raise WorkerPlanningError("durable state changed during planning")
    provisional = object.__new__(WorkerPlanningResult)
    values = {
        "planning_receipt": planning_receipt,
        "selected_slice_id": selected_slice_id,
        "durable_projection_digest": before.event_digest,
        "durable_dependency_receipt_ids": receipt_ids,
        "lease_id": lease_id,
        "lease_owner_id": lease["owner_id"],
        "worker_match": worker_match,
        "worker_request": request,
        "dispatch_authorization": authorization,
        "launch_action": action,
        "durable_state_changed": False,
        "queue_transition_performed": False,
        "worker_launched": False,
        "execution_performed": False,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return WorkerPlanningResult(**values, result_digest=digest)
