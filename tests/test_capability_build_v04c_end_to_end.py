"""Self-contained offline integration tests for the complete V0.4C chain."""

import hashlib
from dataclasses import replace

import pytest

from scripts.capability_build.evidence import (
    EvidenceRecord,
    build_default_verification_plan,
)
from scripts.capability_build.handoff import (
    DECISION_APPROVE_FOR_PR,
    DECISION_REJECT,
    DECISION_REQUEST_CHANGES,
)
from scripts.capability_build.intake import ReturnedFile
from scripts.capability_build.job_binding import BuildJobBinding
from scripts.capability_build.pr_package import PRPackageError
from scripts.capability_build.pr_package_renderer import PRPackageRenderError
from scripts.capability_build.pr_publication_action import (
    STATUS_ACTION_PREPARED,
    STATUS_NOT_PREPARED,
    PRPublicationActionError,
    prepare_pr_publication_action,
)
from scripts.capability_build.pr_publication_authorization import (
    STATUS_AUTHORIZED,
    STATUS_NOT_AUTHORIZED,
    authorize_pr_publication,
    expected_authorization_input,
)
from scripts.capability_build.pr_publication_result import (
    OUTCOME_CREATED,
    OUTCOME_FAILED,
    STATUS_PR_CREATED,
    STATUS_RESULT_REJECTED,
    expected_result_input,
    record_pr_publication_result,
)
from scripts.capability_build.pr_review_decision import PRReviewDecisionInput
from scripts.capability_build.request import CapabilityBuildRequest
from scripts.capability_build.request_workflow import (
    start_workflow_from_request,
)
from scripts.capability_build.workflow import (
    STATUS_COMPLETE,
    STEP_HUMAN_DECISION_PENDING,
)
from scripts.capability_build.workflow_brief import (
    render_brief_from_workflow_scope,
)
from scripts.capability_build.workflow_bundle import (
    create_bundle_from_workflow_evidence,
)
from scripts.capability_build.workflow_evidence import (
    attach_evidence_from_workflow_intake,
)
from scripts.capability_build.workflow_handoff import (
    create_handoff_from_workflow_bundle,
)
from scripts.capability_build.workflow_intake import (
    check_returned_worker_from_workflow_brief,
)
from scripts.capability_build.workflow_job import (
    create_job_from_workflow_start,
)
from scripts.capability_build.workflow_pr_decision import (
    STATUS_DECISION_RECORDED,
    STATUS_NOT_RECORDED,
    WorkflowPRDecisionError,
    record_pr_review_decision,
)
from scripts.capability_build.workflow_pr_package import (
    WorkflowPRPackageError,
    create_pr_package_from_workflow_handoff,
)
from scripts.capability_build.workflow_pr_package_renderer import (
    DISPOSITION_BLOCKED_INSPECTION_ONLY,
    WorkflowPRPackageRenderError,
    render_pr_package_from_workflow_creation,
)
from scripts.capability_build.workflow_pr_review import (
    WorkflowPRReviewError,
    enter_human_review_pending,
)
from scripts.capability_build.workflow_scope import (
    freeze_scope_from_workflow_job,
)


BASE_SHA = "f" * 40
SPEC_SHA256 = "e" * 64
TEST_PATH = "tests/test_unicode_widget.py"


def _workflow_rendering(evidence_status="passed"):
    request = CapabilityBuildRequest(
        request_id="request-v04c-closure",
        capability_name="Project insight",
        user_goal="Add deterministic offline project insight.",
        requested_behavior_summary="Return a bounded project summary.",
        constraints=("Remain offline.",),
    )
    start = start_workflow_from_request(request)
    job = create_job_from_workflow_start(
        start,
        BuildJobBinding(
            job_id="job-v04c-closure",
            capability_id="projects.insight",
            spec_sha256=SPEC_SHA256,
            base_sha=BASE_SHA,
            actor="human:reviewer",
            note="Approved closure integration fixture.",
        ),
    )
    scope = freeze_scope_from_workflow_job(
        job,
        {
            "allowed_new_files": (TEST_PATH,),
            "allowed_existing_files": ("backend/widgets.py",),
            "protected_files": ("ops/protected/**",),
            "forbidden_paths": ("private/**",),
            "justifications": {
                TEST_PATH: "Exercise the integration chain.",
                "backend/widgets.py": "Update the scoped implementation.",
            },
        },
    )
    brief = render_brief_from_workflow_scope(
        scope,
        "Implement the approved bounded behavior.",
        ("Do not add runtime authority.",),
    )
    intake = check_returned_worker_from_workflow_brief(
        brief,
        (
            ReturnedFile(
                "backend/widgets.py", "modify", "VALUE = 'café 雪'\n"
            ),
            ReturnedFile(
                TEST_PATH,
                "create",
                "def test_unicode():\n    assert '雪'\n",
            ),
        ),
    )
    plan = build_default_verification_plan(intake.intake)
    records = tuple(
        EvidenceRecord(
            command_name=command.name,
            status=evidence_status,
            summary=f"Offline verification: {command.name}",
            exit_code=0 if evidence_status == "passed" else 1,
            output_excerpt="Bounded safe evidence.",
        )
        for command in plan.commands
    )
    evidence = attach_evidence_from_workflow_intake(intake, records)
    bundle = create_bundle_from_workflow_evidence(evidence)
    handoff = create_handoff_from_workflow_bundle(bundle)
    creation = create_pr_package_from_workflow_handoff(handoff)
    return render_pr_package_from_workflow_creation(creation)


def _review(evidence_status="passed"):
    return enter_human_review_pending(_workflow_rendering(evidence_status))


def _decision_input(review, choice, decision_id="decision-v04c-closure"):
    package = review.source_rendering.pr_package_creation.pr_package
    return PRReviewDecisionInput(
        decision_id=decision_id,
        reviewer_id="human:moot",
        decision=choice,
        rationale="Reviewed exact UTF-8 evidence: café 雪.",
        job_id=package.job_id,
        package_id=package.package_id,
        proposal_base_sha=package.base_sha,
    )


def _authorization(decision, authorization_id="authorization-v04c-closure"):
    supplied = expected_authorization_input(
        decision, authorization_id, "human:moot"
    )
    return authorize_pr_publication(decision, supplied)


def _created_receipt(action, result_id="result-v04c-closure"):
    supplied = expected_result_input(
        action,
        result_id,
        OUTCOME_CREATED,
        pr_number=72,
        pr_url="https://github.com/mootmoot1/MootOS/pull/72",
    )
    return record_pr_publication_result(action, supplied)


def test_happy_path_preserves_the_complete_offline_trust_chain():
    rendering = _workflow_rendering()
    creation = rendering.pr_package_creation
    package = creation.pr_package
    review = enter_human_review_pending(rendering)
    supplied_decision = _decision_input(review, DECISION_APPROVE_FOR_PR)
    decision = record_pr_review_decision(review, supplied_decision)
    authorization = _authorization(decision)
    action = prepare_pr_publication_action(authorization)
    result = _created_receipt(action)

    assert rendering.rendering.proposal is package
    assert rendering.workflow is creation.workflow
    assert review.source_rendering is rendering
    assert review.prior_workflow is rendering.workflow
    assert decision.review is review
    assert decision.supplied is supplied_decision
    assert decision.status == STATUS_DECISION_RECORDED
    assert decision.eligible_for_pr_authorization is True
    assert authorization.decision_recording is decision
    assert authorization.status == STATUS_AUTHORIZED
    assert authorization.single_purpose is True
    assert action.authorization is authorization
    assert action.status == STATUS_ACTION_PREPARED
    assert action.executed is False
    assert action.execution_performed is False
    assert result.action is action
    assert result.status == STATUS_PR_CREATED
    assert result.result_recorded is True
    assert result.external_success_reported is True
    assert result.externally_verified is False
    assert result.reporter_authenticated is False
    assert result.execution_performed_by_this_module is False
    assert all(
        value is False
        for value in (
            package.git_action_performed,
            rendering.rendering.github_action_performed,
            review.github_action_performed,
            decision.github_action_performed,
            authorization.execution_performed,
            action.github_action_performed,
            result.github_action_performed,
        )
    )


def test_blocked_chain_remains_inspection_only_and_cannot_approve():
    rendering = _workflow_rendering("failed")
    review = enter_human_review_pending(rendering)
    assert rendering.rendered is True
    assert rendering.disposition == DISPOSITION_BLOCKED_INSPECTION_ONLY
    assert review.inspection_only is True
    assert DECISION_APPROVE_FOR_PR not in review.decision_options
    assert DECISION_REQUEST_CHANGES in review.decision_options
    assert DECISION_REJECT in review.decision_options

    decision = record_pr_review_decision(
        review, _decision_input(review, DECISION_APPROVE_FOR_PR)
    )
    assert decision.status == STATUS_NOT_RECORDED
    authorization = _authorization(decision)
    assert authorization.status == STATUS_NOT_AUTHORIZED
    assert prepare_pr_publication_action(authorization).status == (
        STATUS_NOT_PREPARED
    )


@pytest.mark.parametrize(
    "choice", [DECISION_REQUEST_CHANGES, DECISION_REJECT]
)
def test_non_approval_decisions_record_without_publication_eligibility(choice):
    review = _review()
    decision = record_pr_review_decision(
        review, _decision_input(review, choice)
    )
    assert decision.status == STATUS_DECISION_RECORDED
    assert decision.decision == choice
    assert decision.eligible_for_pr_authorization is False
    authorization = _authorization(decision)
    assert authorization.status == STATUS_NOT_AUTHORIZED
    assert prepare_pr_publication_action(authorization).status == (
        STATUS_NOT_PREPARED
    )


def test_adjacent_boundaries_reject_forged_objects_and_identifiers():
    rendering = _workflow_rendering()
    creation = rendering.pr_package_creation
    package = creation.pr_package
    review = enter_human_review_pending(rendering)

    with pytest.raises(PRPackageError):
        replace(package, job_id="")
    with pytest.raises(WorkflowPRPackageError):
        replace(creation, pr_package=replace(package, package_id="forged"))
    with pytest.raises(WorkflowPRPackageError):
        replace(
            creation, pr_package=replace(package, job_id="forged-job")
        )
    with pytest.raises(PRPackageRenderError):
        replace(rendering.rendering, pr_body="forged body")
    with pytest.raises(WorkflowPRPackageRenderError):
        replace(rendering, disposition=DISPOSITION_BLOCKED_INSPECTION_ONLY)
    with pytest.raises(WorkflowPRReviewError):
        replace(review, decision_options=(DECISION_REJECT,))

    wrong_source = replace(
        _decision_input(review, DECISION_APPROVE_FOR_PR),
        proposal_base_sha="a" * 40,
    )
    assert record_pr_review_decision(review, wrong_source).status == (
        STATUS_NOT_RECORDED
    )
    decision = record_pr_review_decision(
        review, _decision_input(review, DECISION_APPROVE_FOR_PR)
    )
    with pytest.raises(WorkflowPRDecisionError):
        replace(decision, decision=DECISION_REJECT)

    supplied_auth = expected_authorization_input(
        decision, "authorization-v04c-closure", "human:moot"
    )
    for changes in (
        {"repository": "other/repo"},
        {"target_branch": "develop"},
        {"title_sha256": "b" * 64},
        {"body_sha256": "c" * 64},
        {"decision_id": "forged-decision"},
    ):
        rejected = authorize_pr_publication(
            decision, replace(supplied_auth, **changes)
        )
        assert rejected.status == STATUS_NOT_AUTHORIZED

    authorization = authorize_pr_publication(decision, supplied_auth)
    action = prepare_pr_publication_action(authorization)
    with pytest.raises(PRPublicationActionError):
        replace(action, idempotency_key="b" * 64)

    supplied_result = expected_result_input(
        action,
        "result-v04c-closure",
        OUTCOME_CREATED,
        pr_number=72,
        pr_url="https://github.com/mootmoot1/MootOS/pull/72",
    )
    for changes in (
        {"idempotency_key": "b" * 64},
        {"authorization_id": "forged-authorization"},
        {"pr_url": "https://github.com/mootmoot1/MootOS/pull/73"},
    ):
        rejected = record_pr_publication_result(
            action, replace(supplied_result, **changes)
        )
        assert rejected.status == STATUS_RESULT_REJECTED


def test_unicode_content_propagates_through_allowed_human_text():
    rendering = _workflow_rendering()
    review = enter_human_review_pending(rendering)
    supplied = _decision_input(review, DECISION_APPROVE_FOR_PR)
    decision = record_pr_review_decision(review, supplied)
    authorization = _authorization(decision)
    action = prepare_pr_publication_action(authorization)
    assert "café 雪" in decision.summary()
    assert decision.supplied.rationale.encode("utf-8").decode("utf-8") == (
        decision.supplied.rationale
    )
    rendered_body = rendering.rendering.pr_body
    assert authorization.supplied.body_sha256 == hashlib.sha256(
        rendered_body.encode("utf-8")
    ).hexdigest()
    assert action == prepare_pr_publication_action(authorization)

    decomposed = "External failure: Cafe\u0301 雪"
    failed_input = expected_result_input(
        action,
        "result-v04c-unicode",
        OUTCOME_FAILED,
        failure_classification="external_failure",
        explanation=decomposed,
    )
    failed_result = record_pr_publication_result(action, failed_input)
    assert failed_result.supplied.explanation == decomposed
    assert decomposed in failed_result.summary()
    assert failed_result.summary().encode("utf-8").decode("utf-8") == (
        failed_result.summary()
    )


def test_workflow_complete_does_not_mean_publication_complete():
    review = _review()
    assert review.workflow.status == STATUS_COMPLETE
    assert review.workflow.current_step == STEP_HUMAN_DECISION_PENDING
    assert review.human_decision_recorded is False
    assert review.approved is False
    assert review.github_action_performed is False
    assert review.runtime_authority is False


def test_deterministic_identity_repeats_without_claiming_replay_protection():
    review = _review()
    first_decision = record_pr_review_decision(
        review, _decision_input(review, DECISION_APPROVE_FOR_PR)
    )
    second_decision = record_pr_review_decision(
        review, _decision_input(review, DECISION_APPROVE_FOR_PR)
    )
    first_action = prepare_pr_publication_action(
        _authorization(first_decision)
    )
    second_action = prepare_pr_publication_action(
        _authorization(second_decision)
    )
    assert first_decision == second_decision
    assert first_action.idempotency_key == second_action.idempotency_key
    assert _created_receipt(first_action) == _created_receipt(second_action)
    assert first_action.executed is False
    assert _created_receipt(first_action).externally_verified is False
