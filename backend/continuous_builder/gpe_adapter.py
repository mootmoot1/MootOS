"""GP-E adapter interface. No runner, provider SDK, process, or retry loop.

GP-F must separately authorize launch, validate system bindings, supervise,
quarantine, and preserve GP-D reconciliation. Implementations translate their
own SDK errors; downstream code only sees these system-owned categories.
"""

from typing import Protocol

from .gpe_protocol import (
    ERROR_CATEGORIES,
    WorkerIdentity,
    WorkerRequest,
    WorkerResult,
    WorkerProtocolError,
    create_worker_result,
    decode_message,
    validate_context_delivery,
    validate_worker_result,
)


class WorkerAdapter(Protocol):
    """Technical capability metadata never grants admitted capability.

    invoke is a future implementation boundary, not a launch authorization.
    A supervisor must validate the request against durable system inputs,
    establish authority, and supply precisely the bound CE bytes first.
    An implementation makes at most one invocation and never retries.
    """

    identity: WorkerIdentity

    def invoke(
        self, request: WorkerRequest, context_bytes: tuple
    ) -> WorkerResult: ...


def prepare_context(request, package, supplements=()):
    """Return exact existing CE serialization after delivery binding checks."""
    from .gpa_eval_schema import canonical_json

    validate_context_delivery(request, package, supplements)
    return (package.canonical_bytes(),) + tuple(
        canonical_json(s.to_dict()) for s in supplements
    )


def normalize_adapter_error(
    request,
    worker,
    *,
    category,
    execution_may_have_occurred=True,
    bounded_detail=None
):
    """Uncertainty is the conservative default; never compute retryability.

    False is only for a system-observed pre-invocation failure. A provider's
    denial/timeout/message is not proof no side effect happened. No raw SDK
    exception escapes this boundary and no raw exception is auto-logged.
    """
    if not isinstance(category, str) or category not in ERROR_CATEGORIES:
        category = "unknown_failure"
    if type(execution_may_have_occurred) is not bool:
        raise WorkerProtocolError("execution uncertainty must be boolean")
    status = (
        "execution_unknown"
        if execution_may_have_occurred
        else {
            "timed_out": "timed_out",
            "cancelled": "cancelled",
            "context_too_large": "context_insufficient",
        }.get(category, "failed")
    )
    return create_worker_result(
        request=request,
        worker=worker,
        status=status,
        error_category=category,
        stop_reason=category,
        provider_detail=bounded_detail,
    )


def receive_worker_result(raw, request, worker, *, execution_uncertain):
    """Validate wire claims; supervisor-observed uncertainty overrides claims.

    A clean claim never clears GP-D execution_unknown. This function does not
    read/write GP-D; the caller must carry durable uncertainty into this flag.
    Malformed post-invocation output conservatively requires reconciliation.
    """
    if type(execution_uncertain) is not bool:
        raise WorkerProtocolError("execution uncertainty must be boolean")
    try:
        result = decode_message(raw, WorkerResult)
        validate_worker_result(result, request, worker)
    except WorkerProtocolError:
        return normalize_adapter_error(
            request, worker, category="malformed_response"
        )
    if execution_uncertain:
        return normalize_adapter_error(
            request, worker, category="unknown_failure"
        )
    return result
