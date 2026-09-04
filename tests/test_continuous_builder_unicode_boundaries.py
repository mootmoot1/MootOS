"""Unicode/surrogate boundary tests.

A Python ``str`` can carry an unpaired UTF-16 surrogate (e.g. decoded
from a JSON ``\\ud800``-style escape with no matching low surrogate).
Before Phase 2.5, several validators called ``value.encode("utf-8")``
directly for a byte-length bound check; on such a string that raises a
raw ``UnicodeEncodeError`` -- not any of this package's own domain error
types -- so it propagated as an unhandled exception instead of a clean
validation failure. ``backend.continuous_builder.text_safety.utf8_length``
fixes this uniformly; these tests prove the fix at every call site that
takes freeform caller-supplied text.
"""

import pytest

from backend.continuous_builder.blueprint import BlueprintError
from backend.continuous_builder.blueprint_parser import (
    BlueprintParseError,
    parse_blueprint,
)
from backend.continuous_builder.chief_builder import (
    BlueprintApprovalEvidence,
    ChiefBuilderError,
)
from backend.continuous_builder.conflict_analysis import (
    ConflictAnalysisError,
    EligibilityResources,
)
from backend.continuous_builder.dependency_analysis import (
    DependencyAnalysisError,
    DependencyReceipt,
)
from backend.continuous_builder.leases import LeaseError, create_attempt
from backend.continuous_builder.text_safety import utf8_length
from test_continuous_builder_blueprint import make_slice

LONE_SURROGATE = "\ud800"


def test_utf8_length_reports_infinity_for_unpaired_surrogate():
    assert utf8_length(LONE_SURROGATE) == float("inf")
    assert utf8_length("plain text") == len("plain text".encode("utf-8"))


def test_blueprint_slice_field_with_surrogate_fails_closed_not_crashes():
    with pytest.raises(BlueprintError, match="surrogate"):
        make_slice(objective=f"Do the thing {LONE_SURROGATE}")


def test_blueprint_parser_str_payload_with_surrogate_fails_closed():
    with pytest.raises(BlueprintParseError):
        parse_blueprint(LONE_SURROGATE)


def test_chief_builder_approval_identity_with_surrogate_fails_closed():
    with pytest.raises(ChiefBuilderError):
        BlueprintApprovalEvidence(
            f"approval-{LONE_SURROGATE}", "a" * 64, "human", True,
        )


def test_dependency_receipt_identity_with_surrogate_fails_closed():
    with pytest.raises(DependencyAnalysisError):
        DependencyReceipt(f"r-{LONE_SURROGATE}", "CB-001", "1", True, True)


def test_conflict_analysis_capability_with_surrogate_fails_closed():
    with pytest.raises(ConflictAnalysisError):
        EligibilityResources(
            available_capabilities=(f"cap-{LONE_SURROGATE}",),
            available_authority_classes=(),
        )


def test_lease_identity_with_surrogate_fails_closed(tmp_path):
    path = tmp_path / "mootos.db"
    from backend.migrations import run_migrations
    run_migrations(path)
    with pytest.raises(LeaseError, match="malformed"):
        create_attempt(
            path, f"attempt-{LONE_SURROGATE}", "continuous-builder",
            "phase-1", "CB-001", "1", "owner-1",
            "2026-01-01T00:00:00+00:00",
        )
