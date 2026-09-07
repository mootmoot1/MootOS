"""Authenticate exact GP-F receipt bytes, never authorize execution.

Trust assumes an isolated, human-controlled interpreter/package installation.
Python object privacy and evidence digests are not security boundaries. Always
reverify transported evidence with its original receipt and detached signature.
Public-key enrollment/rotation/removal is a human-only TCB edit.
"""

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"MootOS/GPF/HumanApprovalReceipt/v1\x00"
MAX_RECEIPT_BYTES = 8 * 1024
EVIDENCE_VERSION = "gpf-trusted-human-approval-evidence-v1"
# Raw public verification keys only. No caller-supplied trust roots or loaders.
_AUTHORIZED_PUBLIC_KEYS = MappingProxyType({
    "sha256:712fdc1c22d40f838af779c26c89e68122e9afa2770fa6091913287f40a1483a":
        bytes.fromhex(
            "a3d6f3ca5d13e054149ec868c03137b286c3714cac42a619ebb44900615cdef8"
        ),
})
_FALSE_FLAGS = frozenset({
    "approver_authenticated", "launch_authorized", "dispatch_authorized",
    "publication_authorized", "queue_transition_authorized",
    "github_authorized", "merge_authorized", "main_advancement_authorized",
    "result_trusted", "worker_output_trusted",
})
_IDS = ("approval_id", "job_id", "attempt_id", "request_id")
_DIGESTS = ("receipt_sha256", "request_sha256", "header_sha256",
            "subject_sha256")
_RECEIPT_FIELDS = _FALSE_FLAGS | frozenset(_IDS + _DIGESTS) | {
    "schema_version", "gate", "supplied_approver_identity",
    "approved_capability_ids", "approved_scope", "created_at", "valid_until",
}


class ApprovalAuthorityError(ValueError):
    """Approval could not be authenticated; never contains input contents."""


def _check(condition, reason):
    if not condition:
        raise ApprovalAuthorityError(reason)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value):
    raise ApprovalAuthorityError("non-JSON constant")


def _text(value, maximum):
    _check(type(value) is str and 0 < len(value.encode("utf-8")) <= maximum,
           "invalid receipt text")


def _timestamp(value):
    _text(value, 128)
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(stamp.utcoffset() is not None, "timestamp requires timezone")
    return stamp


def _parse_receipt(raw):
    _check(type(raw) is bytes and 0 < len(raw) <= MAX_RECEIPT_BYTES,
           "receipt byte bound/type")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                          parse_constant=_no_constant)
        _check(type(body) is dict and set(body) == _RECEIPT_FIELDS,
               "receipt fields mismatch")
        _check(_canonical(body) == raw, "non-canonical receipt")
        _check(body["schema_version"] == "gpf-human-approval-receipt-v1",
               "unsupported receipt schema")
        for name in _FALSE_FLAGS:
            _check(body[name] is False, "receipt authority promotion")
        for name in _IDS:
            _text(body[name], 64)
            _check(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", body[name]),
                   "invalid receipt id")
        for name in _DIGESTS:
            _text(body[name], 64)
            _check(re.fullmatch(r"[0-9a-f]{64}", body[name]),
                   "invalid receipt digest")
        _text(body["gate"], 64)
        _text(body["supplied_approver_identity"], 256)
        for name, maximum in (("approved_scope", 64),
                              ("approved_capability_ids", 32)):
            values = body[name]
            _check(type(values) is list and len(values) <= maximum,
                   "invalid receipt subject")
            for value in values:
                _text(value, 4096)
            _check(values == sorted(set(values)), "non-canonical subject")
        # Subject strings are authenticated, not interpreted as capabilities
        # or scope permission. Admission/currentness belongs to the consumer.
        subject = {name: body[name] for name in (
            "approved_capability_ids", "approved_scope")}
        _check(body["subject_sha256"] == _digest(_canonical(subject)),
               "subject digest mismatch")
        created = _timestamp(body["created_at"])
        if body["valid_until"] is not None:
            _check(_timestamp(body["valid_until"]) > created,
                   "invalid receipt interval")
        payload = {k: v for k, v in body.items() if k != "receipt_sha256"}
        _check(body["receipt_sha256"] == _digest(_canonical(payload)),
               "receipt digest mismatch")
        return body
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ApprovalAuthorityError("invalid canonical receipt") from None


@dataclass(frozen=True, init=False)
class TrustedHumanApprovalEvidence:
    """Verifier output, not a bearer token. No public mint/reseal constructor.

    A digest proves integrity only. A future trusted consumer must call
    validate_trusted_human_approval_evidence with original proof bytes.
    This record grants no launch, publication, merge, or other capability.
    """

    schema_version: str
    receipt_sha256: str
    approval_id: str
    job_id: str
    attempt_id: str
    request_id: str
    gate: str
    signer_key_id: str
    signature_algorithm: str
    authenticated: bool
    evidence_sha256: str

    def __init__(self, *args, **kwargs):
        raise ApprovalAuthorityError(
            "evidence requires signature verification")

    def to_dict(self):
        return {item.name: getattr(self, item.name) for item in fields(self)}


def verify_human_approval(*, receipt_bytes: bytes, detached_signature: bytes,
                          signer_key_id: str) -> TrustedHumanApprovalEvidence:
    """Verify signature over DOMAIN + exact canonical receipt bytes.

    Does not decide expiry, currentness, gate satisfaction, or launch.
    The claimed approver name is signed text, not an authenticated identity.
    """
    body = _parse_receipt(receipt_bytes)
    _check(type(detached_signature) is bytes and len(detached_signature) == 64,
           "invalid signature size/type")
    _check(type(signer_key_id) is str and
           re.fullmatch(r"sha256:[0-9a-f]{64}", signer_key_id),
           "invalid key id")
    raw_key = _AUTHORIZED_PUBLIC_KEYS.get(signer_key_id)
    _check(type(raw_key) is bytes and len(raw_key) == 32,
           "unauthorized signer")
    _check(signer_key_id == "sha256:" + _digest(raw_key),
           "pinned key fingerprint mismatch")
    try:
        Ed25519PublicKey.from_public_bytes(raw_key).verify(
            detached_signature, DOMAIN + receipt_bytes)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError):
        raise ApprovalAuthorityError("signature verification failed") from None
    values = {name: body[name] for name in _IDS + ("gate", "receipt_sha256")}
    values.update(schema_version=EVIDENCE_VERSION, signer_key_id=signer_key_id,
                  signature_algorithm="Ed25519", authenticated=True)
    values["evidence_sha256"] = _digest(_canonical(values))
    evidence = object.__new__(TrustedHumanApprovalEvidence)
    for name, value in values.items():
        object.__setattr__(evidence, name, value)
    return evidence


def validate_trusted_human_approval_evidence(
    evidence, *, receipt_bytes: bytes, detached_signature: bytes,
    signer_key_id: str,
) -> TrustedHumanApprovalEvidence:
    """Reverify proof and compare every field; never trust an evidence seal."""
    verified = verify_human_approval(
        receipt_bytes=receipt_bytes, detached_signature=detached_signature,
        signer_key_id=signer_key_id)
    _check(type(evidence) is TrustedHumanApprovalEvidence,
           "invalid evidence type")
    for item in fields(verified):
        actual = getattr(evidence, item.name, None)
        expected = getattr(verified, item.name)
        _check(type(actual) is type(expected) and actual == expected,
               "evidence does not match verified proof")
    return verified
