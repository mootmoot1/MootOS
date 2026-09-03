"""Tests for V0.4C Slice 6 human decision input."""

import json
from dataclasses import FrozenInstanceError

import pytest

from scripts.capability_build.pr_review_decision import (
    MAX_DECISION_INPUT_SUMMARY_BYTES,
    MAX_RATIONALE_BYTES,
    PRReviewDecisionError,
    PRReviewDecisionInput,
)


def _input(**changes):
    values = dict(
        decision_id="decision-1", reviewer_id="human:moot",
        decision="approve_for_pr", rationale="Reviewed evidence.",
        job_id="job-1", package_id="job-1-pr-package",
        proposal_base_sha="a" * 40,
    )
    values.update(changes)
    return PRReviewDecisionInput(**values)


@pytest.mark.parametrize(
    "decision", ["approve_for_pr", "request_changes", "reject"]
)
def test_all_fixed_decisions_are_representable_without_validation(decision):
    value = _input(decision=decision)
    assert value.decision == decision
    assert value.decision_allowed is False
    assert value.publication_authorized is False


@pytest.mark.parametrize("decision", ["", "approved", None])
def test_invalid_decision_is_rejected(decision):
    with pytest.raises(PRReviewDecisionError):
        _input(decision=decision)


@pytest.mark.parametrize(
    "field,value",
    [("decision_id", "bad/id"), ("reviewer_id", ""),
     ("job_id", "../job"), ("package_id", "package id"),
     ("proposal_base_sha", "xyz")],
)
def test_invalid_identity_is_rejected(field, value):
    with pytest.raises(PRReviewDecisionError):
        _input(**{field: value})


def test_rationale_byte_and_unicode_boundaries():
    assert len(_input(rationale="x" * MAX_RATIONALE_BYTES).rationale) == 4096
    assert len(_input(rationale="é" * 2048).rationale.encode("utf-8")) == 4096
    with pytest.raises(PRReviewDecisionError, match="exceeds"):
        _input(rationale="x" * (MAX_RATIONALE_BYTES + 1))
    with pytest.raises(PRReviewDecisionError, match="exceeds"):
        _input(rationale="é" * 2049)


def test_deterministic_immutable_sanitized_bounded_summary():
    first = _input()
    second = _input()
    assert first.summary() == second.summary()
    payload = json.loads(first.summary())
    assert len(first.summary().encode("utf-8")) <= (
        MAX_DECISION_INPUT_SUMMARY_BYTES
    )
    assert payload["authority"]["source_authoritative"] is False
    assert "secret" not in payload
    with pytest.raises(FrozenInstanceError):
        first.decision = "reject"


def test_secret_like_and_control_text_is_rejected():
    with pytest.raises(PRReviewDecisionError):
        _input(rationale="password=abcdefghijklmnop")
    with pytest.raises(PRReviewDecisionError):
        _input(rationale="bad\x00text")
