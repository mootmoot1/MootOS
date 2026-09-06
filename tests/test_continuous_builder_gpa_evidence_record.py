"""GP-A4 -- Performance / Evidence Record Schema tests."""

import dataclasses

import pytest

from backend.continuous_builder.gpa_evidence_record import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceRecord,
    EvidenceRecordError,
    create_evidence_record,
    evidence_record_is_observational_only,
)
from backend.continuous_builder.gpa_eval_schema import GPAEvalSchemaError, UNKNOWN

BASE_SHA = "d799c23169332135773e377443779ee9f9544c04"


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def _fields(instance):
    return {
        item.name: getattr(instance, item.name)
        for item in dataclasses.fields(instance)
    }


def _make_record(**overrides):
    base_provenance = (
        ("outcome_state", "measured_directly"),
        ("verifier_result", "measured_directly"),
    )
    values = dict(
        run_id="run_001",
        eval_case_id="case_example_001",
        eval_case_sha256="a" * 64,
        architecture_baseline_sha256="b" * 64,
        base_sha=BASE_SHA,
        outcome_state="completed",
        verifier_result="pass",
        field_provenance=base_provenance,
    )
    extra_provenance = overrides.pop("field_provenance", ())
    values["field_provenance"] = tuple(base_provenance) + tuple(extra_provenance)
    values.update(overrides)
    return create_evidence_record(**values)


def test_all_optional_fields_default_to_unknown():
    record = _make_record()
    assert record.provider == UNKNOWN
    assert record.wall_clock_seconds == UNKNOWN
    assert record.input_tokens == UNKNOWN
    assert record.crashed == UNKNOWN
    provenance_names = {name for name, _ in record.field_provenance}
    assert provenance_names == {"outcome_state", "verifier_result"}


def test_unknown_is_never_a_fabricated_zero():
    record = _make_record()
    # UNKNOWN must be distinguishable from 0/False by identity of value,
    # not merely by a falsy check.
    assert record.input_tokens != 0
    assert record.crashed is not False
    assert record.input_tokens == UNKNOWN


def test_known_field_requires_provenance():
    with pytest.raises(EvidenceRecordError, match="no field_provenance entry"):
        _make_record(provider="codex")


def test_provenance_for_unknown_field_is_rejected():
    with pytest.raises(EvidenceRecordError, match="has a field_provenance entry"):
        _make_record(
            field_provenance=(("provider", "user_reported"),),
        )


def test_known_field_with_provenance_succeeds():
    record = _make_record(
        provider="codex",
        input_tokens=1200,
        field_provenance=(
            ("provider", "user_reported"),
            ("input_tokens", "provider_reported"),
        ),
    )
    assert record.provider == "codex"
    assert record.input_tokens == 1200


def test_deterministic_digest():
    kwargs = dict(
        provider="claude",
        field_provenance=(("provider", "measured_directly"),),
    )
    first = _make_record(**kwargs)
    second = _make_record(**kwargs)
    assert first.record_sha256 == second.record_sha256
    assert first.to_dict() == second.to_dict()


def test_unsupported_provenance_code_rejected():
    with pytest.raises(EvidenceRecordError, match="provenance code is unsupported"):
        _make_record(
            provider="codex",
            field_provenance=(("provider", "vibes_based"),),
        )


def test_duplicate_provenance_entry_rejected():
    with pytest.raises(EvidenceRecordError, match="duplicate entry"):
        _make_record(
            provider="codex",
            field_provenance=(
                ("provider", "user_reported"),
                ("provider", "measured_directly"),
            ),
        )


def test_provenance_naming_unknown_field_rejected():
    with pytest.raises(EvidenceRecordError, match="unknown field"):
        _make_record(field_provenance=(("not_a_real_field", "measured_directly"),))


def test_unexpected_optional_kwarg_rejected():
    with pytest.raises(EvidenceRecordError, match="unexpected optional field"):
        _make_record(definitely_not_a_field=1)


def test_bad_outcome_state_rejected():
    with pytest.raises(EvidenceRecordError):
        _make_record(outcome_state="vibes")


def test_negative_int_field_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_record(
            input_tokens=-5,
            field_provenance=(("input_tokens", "measured_directly"),),
        )


def test_bool_field_rejects_non_bool_non_unknown():
    with pytest.raises(GPAEvalSchemaError):
        _make_record(
            crashed=1,
            field_provenance=(("crashed", "measured_directly"),),
        )


def test_stale_base_sha_rejected():
    with pytest.raises(GPAEvalSchemaError):
        _make_record(base_sha="not-a-sha")


def test_unsupported_schema_version_rejected():
    record = _make_record()
    forged = _forge(record, schema_version="gpa-evidence-record-v99")
    with pytest.raises(EvidenceRecordError, match="schema_version"):
        EvidenceRecord(**_fields(forged))


def test_record_cannot_be_constructed_without_trusted_token():
    record = _make_record()
    forged = _forge(record, _token=object())
    with pytest.raises(EvidenceRecordError):
        EvidenceRecord(**_fields(forged))


def test_forged_field_with_stale_digest_rejected():
    record = _make_record()
    forged = _forge(record, outcome_state="failed")
    with pytest.raises(EvidenceRecordError, match="record_sha256 mismatch"):
        EvidenceRecord(**_fields(forged))


def test_zero_authority():
    record = _make_record()
    for name in (
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(record, name) is False


def test_completed_outcome_does_not_imply_trust():
    # A record claiming a fully successful run still carries zero authority
    # -- outcome_state is evidence, never a capability grant.
    record = _make_record(outcome_state="completed", verifier_result="pass")
    assert record.result_trusted is False
    assert record.worker_output_trusted is False


def test_descriptive_only_helper():
    assert evidence_record_is_observational_only() is True


def test_schema_version_constant():
    record = _make_record()
    assert record.schema_version == EVIDENCE_SCHEMA_VERSION
