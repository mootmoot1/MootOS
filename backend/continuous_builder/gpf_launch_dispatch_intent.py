"""System-owned readiness: the coordinator selected this exact candidate.

Eligibility says "no trusted semantic blocker currently prevents this
candidate". This record says something different and strictly narrower:
"the trusted coordinator selected this exact candidate for the next
dispatch opportunity". Neither implies the other, and neither is launch
authority. Every authority flag here is structurally False.

The record binds one immutable assignment, request, attempt, reservation
and source-token identity, plus the coordinator decision that selected it
and a narrow expiry. It is write-once in a fixed system-owned location, so
a worker cannot mint it, replace it, choose another store, widen it, move
it to another request/attempt, or replay it onto a retry.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone

from . import gpf_launch_candidate_binding as source
from .gpf_launch_state_projection import (
    TrustedLaunchStateProjection, project_launch_state,
)

VERSION = "gpf-launch-dispatch-intent-v1"
# A readiness window is a dispatch opportunity, not a standing permission.
MAX_INTENT_TTL_SECONDS = 900
# An issuer cannot backdate or postdate its way to a long-lived intent.
MAX_ISSUE_SKEW_SECONDS = 120


class LaunchIntentError(ValueError):
    """Readiness could not be recorded or loaded; contains no source bytes."""


class LaunchIntentConflict(LaunchIntentError):
    """A different readiness record already owns this exact request slot."""


def _check(condition, reason):
    if not condition:
        raise LaunchIntentError(reason)


def _hash(value):
    return source._digest(source._canonical(value))


def _moment(value, label):
    _check(type(value) is str and 0 < len(value) <= 128, label)
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(stamp.utcoffset() is not None, label)
    return stamp


@dataclass(frozen=True)
class TrustedLaunchDispatchIntent:
    """Readiness evidence only. Grants no launch or dispatch capability."""

    schema_version: str
    intent_id: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    binding_sha256: str
    reservation_sha256: str
    source_tokens_sha256: str
    coordinator_decision_id: str
    coordinator_decision_sha256: str
    issued_at: str
    expires_at: str
    intent_sha256: str

    def __post_init__(self):
        _check(self.schema_version == VERSION, "unsupported intent schema")
        for name in ("intent_id", "job_id", "attempt_id", "request_id",
                     "coordinator_decision_id"):
            source._id(getattr(self, name))
        for name in ("request_sha256", "binding_sha256", "reservation_sha256",
                     "source_tokens_sha256", "coordinator_decision_sha256",
                     "intent_sha256"):
            source._sha(getattr(self, name))
        issued = _moment(self.issued_at, "invalid issue time")
        expires = _moment(self.expires_at, "invalid expiry time")
        _check(expires > issued, "expiry must follow issue")
        _check((expires - issued).total_seconds() <= MAX_INTENT_TTL_SECONDS,
               "readiness window exceeds bound")
        body = self.to_dict()
        body.pop("intent_sha256")
        _check(self.intent_sha256 == _hash(body), "intent digest mismatch")

    def __getattr__(self, name):
        if name in source._FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {item.name: getattr(self, item.name) for item in fields(self)}
        body.update({flag: False for flag in source._FLAGS})
        return body

    def is_expired(self, at):
        """Expiry is judged against an authoritative clock, never a claim."""
        return at >= _moment(self.expires_at, "invalid expiry time")


def _decode(raw):
    body = source._sealed(raw, "intent_sha256")
    expected = {item.name for item in fields(TrustedLaunchDispatchIntent)}
    _check(set(body) == expected | set(source._FLAGS),
           "intent fields mismatch")
    _check(raw == source._canonical(body), "noncanonical persisted intent")
    return TrustedLaunchDispatchIntent(**{k: body[k] for k in expected})


def _publish(directory, name, raw):
    """Atomic create-if-absent; a loser never overwrites the winner."""
    import os
    import secrets
    temporary = ".intent-" + secrets.token_hex(16)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            existing = source._read(directory, name)
            _decode(existing)
            if existing != raw:
                raise LaunchIntentConflict(
                    "a different readiness record owns this slot") from None
            return "replay"
        return "new"
    finally:
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)


def record_launch_dispatch_intent(*, facts, request_bytes,
                                  coordinator_decision_id,
                                  coordinator_decision_sha256, issued_at,
                                  ttl_seconds):
    """Coordinator-only readiness; returns (intent, "new"|"replay").

    Every bound value is rebuilt here from fresh authoritative sources --
    the caller supplies only which coordinator decision selected this
    candidate and how long the opportunity lasts. There is no projection,
    root, store or clock parameter, so a worker cannot point this at
    another candidate, another store, or a longer window.

    Readiness is deliberately orthogonal to eligibility: recording intent
    for a candidate that is currently blocked is allowed and meaningless,
    because consumption re-decides eligibility against fresh sources.
    """
    source._id(coordinator_decision_id)
    source._sha(coordinator_decision_sha256)
    _check(type(ttl_seconds) is int and
           0 < ttl_seconds <= MAX_INTENT_TTL_SECONDS,
           "readiness window out of bounds")
    now = datetime.now(timezone.utc)
    issued = _moment(issued_at, "invalid issue time")
    _check(abs((issued - now).total_seconds()) <= MAX_ISSUE_SKEW_SECONDS,
           "issue time is not current")
    try:
        fresh, projection = project_launch_state(
            facts=facts, request_bytes=request_bytes)
        _check(type(projection) is TrustedLaunchStateProjection,
               "untrusted state projection")
        _check(projection.reservation_present is True and
               type(projection.reservation_sha256) is str,
               "readiness requires a durable dispatch reservation")
        expires = issued.timestamp() + ttl_seconds
        values = dict(
            schema_version=VERSION, job_id=fresh.job_id,
            attempt_id=fresh.attempt_id, request_id=fresh.request_id,
            request_sha256=fresh.request_sha256,
            binding_sha256=fresh.binding_sha256,
            reservation_sha256=projection.reservation_sha256,
            source_tokens_sha256=projection.source_tokens_sha256,
            coordinator_decision_id=coordinator_decision_id,
            coordinator_decision_sha256=coordinator_decision_sha256,
            issued_at=issued.isoformat(),
            expires_at=datetime.fromtimestamp(
                expires, timezone.utc).isoformat(),
        )
        # Deterministic identity: an exact replay reproduces the same bytes,
        # while any changed field becomes a conflicting record, not a silent
        # second readiness for the same slot.
        values["intent_id"] = "intent_" + _hash(sorted(values.items()))[:56]
        body = dict(values, **{flag: False for flag in source._FLAGS})
        intent = TrustedLaunchDispatchIntent(
            **values, intent_sha256=_hash(body))
        with source._directory(source._AUTHORITATIVE_ROOT) as root, \
                source._child(root, "launch_intents", True) as intents, \
                source._child(intents, fresh.job_id, True) as job:
            status = _publish(job, fresh.request_id + ".json",
                              source._canonical(intent.to_dict()))
        return intent, status
    except LaunchIntentError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchIntentError("readiness could not be recorded") from None


def load_launch_dispatch_intent(*, job_id, request_id):
    """Read only from the fixed authoritative store, never a caller object."""
    source._id(job_id)
    source._id(request_id)
    try:
        with source._directory(source._AUTHORITATIVE_ROOT) as root, \
                source._child(root, "launch_intents") as intents, \
                source._child(intents, job_id) as job:
            intent = _decode(source._read(job, request_id + ".json"))
        _check((intent.job_id, intent.request_id) == (job_id, request_id),
               "persisted path/identity mismatch")
        return intent
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchIntentError("readiness unavailable or invalid") from None


def dispatch_intent_grants_no_capability():
    """TRUST REVIEW helper: True -- readiness is never launch authority."""
    return True
