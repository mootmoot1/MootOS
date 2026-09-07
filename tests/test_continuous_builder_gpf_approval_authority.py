"""GP-F signature boundary; keys are ephemeral and never serialized."""

import ast
import dataclasses
import hashlib
import inspect
import json
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from backend.continuous_builder import gpf_approval_authority as authority
from backend.continuous_builder.gpe_protocol import create_worker_request
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    evaluate_changed_paths_against_tcb,
    OUTCOME_FORBIDDEN,
)
from test_continuous_builder_gpf_launch_preparation import (
    _build_inputs, _receipt,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def seal(value):
    body = dict(value)
    body.pop("receipt_sha256", None)
    body["receipt_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    return canonical(body)


@pytest.fixture
def receipt(tmp_path):
    request = create_worker_request(**_build_inputs(tmp_path))
    return _receipt(request)


@pytest.fixture
def signer(monkeypatch):
    # Test-process memory only; never write/export private key bytes.
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "sha256:" + hashlib.sha256(public).hexdigest()
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({key_id: public}))
    return private, key_id


def proof(receipt, signer):
    raw = canonical(receipt.to_dict())
    private, key_id = signer
    return dict(receipt_bytes=raw, detached_signature=private.sign(
        authority.DOMAIN + raw), signer_key_id=key_id)


def test_valid_signature_and_exact_evidence(receipt, signer):
    args = proof(receipt, signer)
    evidence = authority.verify_human_approval(**args)
    assert evidence.authenticated is True
    assert evidence.receipt_sha256 == receipt.receipt_sha256
    assert evidence.signature_algorithm == "Ed25519"
    assert evidence.signer_key_id == signer[1]
    assert receipt.approver_authenticated is False
    assert receipt.launch_authorized is False
    assert authority.validate_trusted_human_approval_evidence(
        evidence, **args) == evidence
    body = evidence.to_dict()
    digest = body.pop("evidence_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    assert not hasattr(evidence, "launch_authorized")


@pytest.mark.parametrize("field,value", [
    ("approval_id", "different_approval"), ("attempt_id", "old_attempt"),
    ("request_id", "other_request"), ("job_id", "other_job"),
    ("gate", "another_gate"), ("request_sha256", "c" * 64),
    ("header_sha256", "d" * 64),
])
def test_old_signature_cannot_authenticate_different_receipt(
    receipt, signer, field, value,
):
    args = proof(receipt, signer)
    body = receipt.to_dict()
    body[field] = value
    args["receipt_bytes"] = seal(body)
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(**args)


@pytest.mark.parametrize("mutation", [
    "tamper_bytes", "tamper_digest", "malformed_json", "duplicate",
    "noncanonical", "unknown", "missing", "array", "nan", "utf8",
    "oversize", "empty", "nested", "subject_digest", "bad_id",
    "bad_interval", "naive_timestamp", "wrong_schema",
])
def test_invalid_receipts_rejected_even_if_signed(receipt, signer, mutation):
    args = proof(receipt, signer)
    body = receipt.to_dict()
    raw = args["receipt_bytes"]
    if mutation == "tamper_bytes":
        raw = raw.replace(b"human_review", b"other_review")
    elif mutation == "tamper_digest":
        body["receipt_sha256"] = "0" * 64
        raw = canonical(body)
    elif mutation == "malformed_json":
        raw = b"{"
    elif mutation == "duplicate":
        raw = b'{"gate":"human_review",' + raw[1:]
    elif mutation == "noncanonical":
        raw += b"\n"
    elif mutation == "unknown":
        body["unexpected"] = False
        raw = seal(body)
    elif mutation == "missing":
        del body["gate"]
        raw = seal(body)
    elif mutation == "array":
        raw = b"[]"
    elif mutation == "nan":
        raw = b'{"gate":NaN}'
    elif mutation == "utf8":
        raw = b"\xff"
    elif mutation == "oversize":
        raw = b" " * (authority.MAX_RECEIPT_BYTES + 1)
    elif mutation == "empty":
        raw = b""
    elif mutation == "nested":
        raw = b"[" * 2000 + b"]" * 2000
    else:
        field, value = {
            "subject_digest": ("subject_sha256", "0" * 64),
            "bad_id": ("job_id", 1),
            "bad_interval": ("valid_until", "2020-01-01T00:00:00+00:00"),
            "naive_timestamp": ("created_at", "2026-09-06T22:00:00"),
            "wrong_schema": ("schema_version", "v2"),
        }[mutation]
        body[field] = value
        raw = seal(body)
    args.update(receipt_bytes=raw,
                detached_signature=signer[0].sign(authority.DOMAIN + raw))
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(**args)


@pytest.mark.parametrize("flag", sorted(authority._FALSE_FLAGS))
@pytest.mark.parametrize("value", [True, 0])
def test_promoted_or_nonboolean_false_flag_rejected(
    receipt, signer, flag, value,
):
    body = receipt.to_dict()
    body[flag] = value
    raw = seal(body)
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(
            receipt_bytes=raw, signer_key_id=signer[1],
            detached_signature=signer[0].sign(authority.DOMAIN + raw))


@pytest.mark.parametrize("case", [
    "wrong_key", "unknown_id", "replaced_key", "wrong_domain",
    "short", "long", "string", "corrupt", "bad_key_id", "bytearray",
])
def test_bad_signature_or_trust_root(receipt, signer, monkeypatch, case):
    args = proof(receipt, signer)
    if case == "wrong_key":
        args["detached_signature"] = Ed25519PrivateKey.generate().sign(
            authority.DOMAIN + args["receipt_bytes"])
    elif case == "unknown_id":
        args["signer_key_id"] = "sha256:" + "0" * 64
    elif case == "replaced_key":
        other = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)
        monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                            MappingProxyType({signer[1]: other}))
    elif case == "wrong_domain":
        args["detached_signature"] = signer[0].sign(
            b"other-domain\x00" + args["receipt_bytes"])
    elif case == "bad_key_id":
        args["signer_key_id"] = []
    elif case == "bytearray":
        args["receipt_bytes"] = bytearray(args["receipt_bytes"])
    else:
        args["detached_signature"] = {
            "short": b"a" * 63, "long": b"a" * 65,
            "string": "a" * 64, "corrupt": b"a" * 64,
        }[case]
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(**args)


def test_empty_production_allowlist_fails_closed(receipt, monkeypatch):
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({}))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "sha256:" + hashlib.sha256(public).hexdigest()
    args = proof(receipt, (private, key_id))
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(**args)


@pytest.mark.parametrize("field,value", [
    ("receipt_sha256", "0" * 64), ("gate", "other_gate"),
    ("authenticated", 1), ("attempt_id", "retry"),
])
def test_forged_evidence_with_recomputed_digest_rejected(
    receipt, signer, field, value,
):
    args = proof(receipt, signer)
    original = authority.verify_human_approval(**args)
    body = original.to_dict()
    body[field] = value
    body.pop("evidence_sha256")
    body["evidence_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    forged = object.__new__(authority.TrustedHumanApprovalEvidence)
    for name, item in body.items():
        object.__setattr__(forged, name, item)
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.validate_trusted_human_approval_evidence(forged, **args)


def test_evidence_has_no_public_constructor(receipt, signer):
    original = authority.verify_human_approval(**proof(receipt, signer))
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.TrustedHumanApprovalEvidence(**original.to_dict())
    with pytest.raises(dataclasses.FrozenInstanceError):
        original.authenticated = False


def test_evidence_reverification_honors_key_removal(
    receipt, signer, monkeypatch,
):
    args = proof(receipt, signer)
    original = authority.verify_human_approval(**args)
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({}))
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.validate_trusted_human_approval_evidence(original, **args)


@pytest.mark.parametrize("path", [
    "backend/continuous_builder/gpf_approval_authority.py", "requirements.txt",
])
def test_new_tcb_paths_are_human_only(path):
    registry = create_mootos_tcb_registry_v1()
    component = registry.component_for_path(path)
    assert component.component_id == "cb_launch_approval_authority"
    assert component.category == "approval_authority"
    assert component.change_policy == "human_only"
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_FORBIDDEN
    assert decision.blocks_advancement is True


def test_dependency_closure_and_receipt_stays_outside_tcb():
    tree = ast.parse(inspect.getsource(authority))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imports.add(node.module)
    assert imports == {
        "hashlib", "json", "re", "dataclasses", "datetime", "types",
        "cryptography.exceptions",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
    }
    registry = create_mootos_tcb_registry_v1()
    assert registry.component_for_path(
        "backend/continuous_builder/gpf_human_approval_receipt.py") is None


def test_old_evidence_cannot_match_new_validly_signed_receipt(receipt, signer):
    args = proof(receipt, signer)
    old = authority.verify_human_approval(**args)
    body = receipt.to_dict()
    body["attempt_id"] = "retry_attempt"
    raw = seal(body)
    args.update(receipt_bytes=raw, detached_signature=signer[0].sign(
        b"MootOS/GPF/HumanApprovalReceipt/v1\x00" + raw))
    updated = authority.verify_human_approval(**args)
    assert updated.attempt_id == "retry_attempt"
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.validate_trusted_human_approval_evidence(old, **args)


def test_signing_domain_is_versioned_protocol_constant():
    assert authority.DOMAIN == b"MootOS/GPF/HumanApprovalReceipt/v1\x00"


def test_enrolled_public_key_structure_and_fingerprint():
    keys = authority._AUTHORIZED_PUBLIC_KEYS
    expected = (
        "sha256:"
        "712fdc1c22d40f838af779c26c89e68122e9afa2770fa6091913287f40a1483a"
    )
    assert tuple(keys) == (expected,)
    public = keys[expected]
    assert type(public) is bytes and len(public) == 32
    assert expected == "sha256:" + hashlib.sha256(public).hexdigest()
    authority.Ed25519PublicKey.from_public_bytes(public)
    with pytest.raises(TypeError):
        keys[expected] = b"x" * 32


def test_enrolled_public_key_cannot_verify_synthetic_signer(receipt):
    raw = canonical(receipt.to_dict())
    synthetic = Ed25519PrivateKey.generate()
    with pytest.raises(authority.ApprovalAuthorityError):
        authority.verify_human_approval(
            receipt_bytes=raw,
            detached_signature=synthetic.sign(authority.DOMAIN + raw),
            signer_key_id=next(iter(authority._AUTHORIZED_PUBLIC_KEYS)),
        )


def test_altered_enrolled_public_key_fingerprint_rejected(
    receipt, monkeypatch,
):
    key_id, public = next(iter(authority._AUTHORIZED_PUBLIC_KEYS.items()))
    altered = bytes([public[0] ^ 1]) + public[1:]
    monkeypatch.setattr(authority, "_AUTHORIZED_PUBLIC_KEYS",
                        MappingProxyType({key_id: altered}))
    with pytest.raises(authority.ApprovalAuthorityError,
                       match="pinned key fingerprint mismatch"):
        authority.verify_human_approval(
            receipt_bytes=canonical(receipt.to_dict()),
            detached_signature=b"x" * 64,
            signer_key_id=key_id,
        )
