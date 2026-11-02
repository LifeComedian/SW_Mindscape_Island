from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session as DBSession

from database import SessionLocal
from study.contracts import TERMINAL_STATES, StudyWorkflowState
from study.access import invitation_required, redeem_invitation
from study.models import (
    StudyConsentRecord,
    StudyContactRecord,
    StudyEligibilityDecision,
    StudyParticipantProfile,
)
from study.participant_service import (
    CONSENT_DOCUMENT_SHA256,
    CONSENT_VERSION,
    ELIGIBILITY_CRITERIA_VERSION,
    record_contact,
    record_profile,
)
from study.schemas import (
    StudyAssessmentStatusResponse,
    StudyBootstrapRequest,
    StudyBootstrapResponse,
    StudyCommandResponse,
    StudyComparativeFeedbackSubmitCommand,
    StudyConsentCommand,
    StudyContactCommand,
    StudyCurrentStepResponse,
    StudyFormatExperienceSubmitCommand,
    StudyOnboardingCommand,
    StudyQuestionnaireDraftCommand,
    StudyQuestionnaireSubmitCommand,
    StudyResultEvaluationSubmitCommand,
    StudyScreeningCommand,
    StudyWithdrawCommand,
    StudyWorldCommand,
)
from study.assessment_service import (
    assessment_status,
    begin_game_estimate,
    run_game_estimate,
)
from study.questionnaire_service import (
    begin_questionnaire,
    questionnaire_payload,
    questionnaire_status,
    save_questionnaire_draft,
    submit_questionnaire,
)
from study.results_service import (
    begin_format_feedback,
    current_result_payload,
    format_feedback_payload,
    results_status,
    reveal_result,
    submit_format_feedback,
    submit_result_evaluation,
)
from study.completion_service import (
    acknowledge_debrief,
    begin_comparison,
    comparison_payload,
    compensation_status,
    completion_payload,
    get_debrief,
    submit_comparison,
)
from study.export_service import authorize_research_export, build_research_export
from study.service import (
    StudyWorkflowError,
    authenticate_study_session,
    bootstrap_study_session,
    transition_study_session,
    utc_now,
)
from study.world_bridge_service import (
    bind_fixture_world,
    cancel_departure,
    confirm_departure,
    request_departure,
)
from models import Session as WorldSession, WorldState
from world.registry import get_world_spec


router = APIRouter(prefix="/study", tags=["study-workflow"])


STEP_PATHS: dict[StudyWorkflowState, str] = {
    StudyWorkflowState.CONSENT_PENDING: "/study/consent",
    StudyWorkflowState.CONSENT_DECLINED: "/study/exit",
    StudyWorkflowState.CONSENTED: "/study/screening",
    StudyWorkflowState.ELIGIBILITY_PENDING: "/study/screening",
    StudyWorkflowState.ELIGIBILITY_INELIGIBLE: "/study/ineligible",
    StudyWorkflowState.ELIGIBILITY_CONFIRMED: "/study/onboarding",
    StudyWorkflowState.ONBOARDING: "/study/onboarding",
    StudyWorkflowState.ISLAND_ACTIVE: "/island",
    StudyWorkflowState.ISLAND_DEPARTURE_PENDING: "/island",
    StudyWorkflowState.ISLAND_COMPLETED: "/study/game-processing",
    StudyWorkflowState.GAME_ESTIMATE_PROCESSING: "/study/game-processing",
    StudyWorkflowState.GAME_ESTIMATE_FROZEN: "/study/questionnaire",
    StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT: "/study/questionnaire",
    StudyWorkflowState.GAME_ESTIMATE_FAILED: "/study/game-processing",
    StudyWorkflowState.QUESTIONNAIRE_ACTIVE: "/study/questionnaire",
    StudyWorkflowState.QUESTIONNAIRE_COMPLETED: "/study/format-feedback",
    StudyWorkflowState.PRE_RESULT_FEEDBACK: "/study/format-feedback",
    StudyWorkflowState.RESULTS_READY: "/study/results",
    StudyWorkflowState.RESULT_ONE_ACTIVE: "/study/results",
    StudyWorkflowState.RESULT_ONE_RATED: "/study/results",
    StudyWorkflowState.RESULT_TWO_ACTIVE: "/study/results",
    StudyWorkflowState.RESULT_TWO_RATED: "/study/comparison",
    StudyWorkflowState.COMPARATIVE_FEEDBACK: "/study/comparison",
    StudyWorkflowState.DEBRIEF: "/study/debrief",
    StudyWorkflowState.COMPLETED: "/study/complete",
    StudyWorkflowState.WITHDRAWN: "/study/withdrawn",
    StudyWorkflowState.TECHNICAL_INCOMPLETE: "/study/technical-incomplete",
}


STATE_ACTIONS: dict[StudyWorkflowState, tuple[str, ...]] = {
    StudyWorkflowState.CONSENT_PENDING: ("read_consent", "accept_consent", "decline_consent"),
    StudyWorkflowState.CONSENTED: ("begin_screening",),
    StudyWorkflowState.ELIGIBILITY_PENDING: ("submit_screening",),
    StudyWorkflowState.ELIGIBILITY_CONFIRMED: ("submit_contact", "submit_onboarding"),
    StudyWorkflowState.ONBOARDING: ("await_island_bridge",),
    StudyWorkflowState.ISLAND_ACTIVE: ("continue_island", "request_departure"),
    StudyWorkflowState.ISLAND_DEPARTURE_PENDING: ("return_to_island", "confirm_departure"),
    StudyWorkflowState.ISLAND_COMPLETED: ("begin_game_processing",),
    StudyWorkflowState.GAME_ESTIMATE_PROCESSING: ("run_game_processing",),
    StudyWorkflowState.GAME_ESTIMATE_FAILED: ("retry_game_processing",),
    StudyWorkflowState.GAME_ESTIMATE_FROZEN: ("begin_questionnaire",),
    StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT: ("begin_questionnaire",),
    StudyWorkflowState.QUESTIONNAIRE_ACTIVE: (
        "save_questionnaire_draft",
        "submit_questionnaire",
    ),
    StudyWorkflowState.QUESTIONNAIRE_COMPLETED: ("begin_format_feedback",),
    StudyWorkflowState.PRE_RESULT_FEEDBACK: ("submit_or_skip_format_feedback",),
    StudyWorkflowState.RESULTS_READY: ("view_result_one",),
    StudyWorkflowState.RESULT_ONE_ACTIVE: ("rate_or_skip_result_one",),
    StudyWorkflowState.RESULT_ONE_RATED: ("view_result_two",),
    StudyWorkflowState.RESULT_TWO_ACTIVE: ("rate_or_skip_result_two",),
    StudyWorkflowState.RESULT_TWO_RATED: ("begin_comparison",),
    StudyWorkflowState.COMPARATIVE_FEEDBACK: ("submit_or_skip_comparison",),
    StudyWorkflowState.DEBRIEF: ("acknowledge_debrief",),
}


def get_study_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _raise_http(exc: StudyWorkflowError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _current_step_payload(study_session) -> StudyCurrentStepResponse:
    try:
        state = StudyWorkflowState(study_session.state)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "invalid_persisted_state", "message": "Stored study state is invalid."},
        ) from exc
    terminal = state in TERMINAL_STATES
    actions = list(STATE_ACTIONS.get(state, ()))
    return StudyCurrentStepResponse(
        study_session_id=study_session.public_id,
        state=state.value,
        revision=study_session.revision,
        language=study_session.language,
        current_step_path=STEP_PATHS[state],
        terminal=terminal,
        can_withdraw=not terminal and state not in {StudyWorkflowState.CONSENT_PENDING},
        allowed_actions=actions,
        study_contract_version=study_session.study_contract_version,
        workflow_version=study_session.workflow_version,
        world_session_id=study_session.world_session_id,
    )


@router.post("/sessions/bootstrap", response_model=StudyBootstrapResponse)
def create_study_workflow(
    request: StudyBootstrapRequest,
    db: DBSession = Depends(get_study_db),
):
    try:
        if invitation_required() or request.invitation_code:
            result = redeem_invitation(db, code=request.invitation_code or "", language=request.language)
        else:
            result = bootstrap_study_session(
                db, language=request.language, idempotency_key=request.idempotency_key,
            )
    except StudyWorkflowError as exc:
        _raise_http(exc)
    study_session = result.study_session
    return StudyBootstrapResponse(
        study_session_id=study_session.public_id,
        state=study_session.state,
        revision=study_session.revision,
        recovery_token=result.recovery_token,
        recovery_token_issued=result.recovery_token is not None,
        replayed=result.replayed,
        current_step_path=STEP_PATHS[StudyWorkflowState(study_session.state)],
    )


@router.get(
    "/sessions/{study_session_id}/current-step",
    response_model=StudyCurrentStepResponse,
    response_model_exclude_none=True,
)
def get_current_study_step(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    try:
        study_session = authenticate_study_session(
            db,
            public_id=study_session_id,
            recovery_token=x_study_recovery_token,
        )
        # Resume report preparation after a committed submission.
        from study.protocol_v2 import enabled
        if enabled(study_session) and study_session.state == 'questionnaire_completed':
            from study.available_results import prepare
            study_session=prepare(db,study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)
    return _current_step_payload(study_session)


def _authenticated_session(
    db: DBSession, study_session_id: str, recovery_token: str
):
    try:
        return authenticate_study_session(
            db,
            public_id=study_session_id,
            recovery_token=recovery_token,
        )
    except StudyWorkflowError as exc:
        _raise_http(exc)


def _command_payload(study_session, *, replayed: bool = False, research_id: str | None = None):
    state = StudyWorkflowState(study_session.state)
    return StudyCommandResponse(
        state=state.value,
        revision=study_session.revision,
        current_step_path=STEP_PATHS[state],
        replayed=replayed,
        research_id=research_id,
        world_session_id=study_session.world_session_id,
    )


@router.get('/sessions/{study_session_id}/consent-content')
def get_bound_consent(study_session_id: str, x_study_recovery_token: str = Header(min_length=20,max_length=200), db: DBSession = Depends(get_study_db)):
    session=_authenticated_session(db,study_session_id,x_study_recovery_token)
    from study.protocol_v2 import enabled,consent_payload
    if not enabled(session): raise HTTPException(404,detail={'code':'legacy_consent'})
    record = db.query(StudyConsentRecord).filter_by(study_session_id=session.id).one_or_none()
    return consent_payload(record.consent_version) if record else consent_payload()


@router.post('/sessions/{study_session_id}/begin-baseline')
def begin_baseline(study_session_id: str, x_study_recovery_token: str = Header(min_length=20,max_length=200), db: DBSession = Depends(get_study_db)):
    session=_authenticated_session(db,study_session_id,x_study_recovery_token)
    from study.protocol_v2 import enabled,progress
    if not enabled(session) or session.state not in ('eligibility_confirmed','onboarding') or not db.query(StudyContactRecord).filter_by(study_session_id=session.id).first():
        raise HTTPException(409,detail={'code':'baseline_not_available'})
    row=progress(db,session)
    if row.baseline_started_at is None: row.baseline_started_at=utc_now()
    db.commit()
    return {'started_at':row.baseline_started_at.isoformat()}


@router.get('/sessions/{study_session_id}/exit-information')
def exit_information(study_session_id: str, x_study_recovery_token: str = Header(min_length=20,max_length=200), db: DBSession = Depends(get_study_db)):
    session=_authenticated_session(db,study_session_id,x_study_recovery_token)
    from study.protocol_v2 import enabled,debrief_instrument
    if not enabled(session) or session.state not in ('withdrawn','technical_incomplete'):
        raise HTTPException(409,detail={'code':'exit_information_unavailable'})
    contact=db.query(StudyContactRecord).filter_by(study_session_id=session.id).one_or_none()
    return {**debrief_instrument(),'research_id':contact.research_id if contact else None,
      'exit_receipt':'EXIT-'+session.public_id[-16:].upper(),'ended_at':session.updated_at.isoformat(),
      'compensation':compensation_status(db,session)}


@router.get("/research-export/sessions/{study_session_id}")
def export_research_session(
    study_session_id: str,
    x_study_research_export_key: str | None = Header(
        default=None, min_length=1, max_length=512
    ),
    db: DBSession = Depends(get_study_db),
):
    try:
        authorize_research_export(x_study_research_export_key)
        return build_research_export(db, study_session_public_id=study_session_id)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post(
    "/sessions/{study_session_id}/start-island",
    response_model=StudyCommandResponse,
)
def start_island(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = bind_fixture_world(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/request-departure",
    response_model=StudyCommandResponse,
)
def request_island_departure(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = request_departure(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/cancel-departure",
    response_model=StudyCommandResponse,
)
def cancel_island_departure(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = cancel_departure(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/confirm-departure",
    response_model=StudyCommandResponse,
)
def confirm_island_departure(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = confirm_departure(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/begin-game-estimate",
    response_model=StudyCommandResponse,
)
def begin_island_estimate(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = begin_game_estimate(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/run-game-estimate",
    response_model=StudyCommandResponse,
)
def run_island_estimate(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = run_game_estimate(
            db,
            study_session=study_session,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get(
    "/sessions/{study_session_id}/game-estimate",
    response_model=StudyAssessmentStatusResponse,
    response_model_exclude_none=True,
)
def get_island_estimate_status(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    return assessment_status(db, study_session)


@router.post(
    "/sessions/{study_session_id}/begin-questionnaire",
    response_model=StudyCommandResponse,
)
def begin_bfi2_questionnaire(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = begin_questionnaire(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/questionnaire")
def get_bfi2_questionnaire(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return questionnaire_payload(db, study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post("/sessions/{study_session_id}/questionnaire-draft")
def save_bfi2_questionnaire_draft(
    study_session_id: str,
    request: StudyQuestionnaireDraftCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return save_questionnaire_draft(
            db,
            study_session=study_session,
            answer_rows=request.answers,
            skipped_items=request.skipped_items,
            expected_draft_revision=request.expected_draft_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)


@router.post(
    "/sessions/{study_session_id}/questionnaire-submit",
    response_model=StudyCommandResponse,
)
def submit_bfi2_questionnaire(
    study_session_id: str,
    request: StudyQuestionnaireSubmitCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = submit_questionnaire(
            db,
            study_session=study_session,
            answer_rows=request.answers,
            skipped_items=request.skipped_items,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/questionnaire-status")
def get_bfi2_questionnaire_status(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    return questionnaire_status(db, study_session)


@router.post(
    "/sessions/{study_session_id}/begin-format-feedback",
    response_model=StudyCommandResponse,
)
def begin_pre_result_format_feedback(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = begin_format_feedback(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/format-feedback")
def get_pre_result_format_feedback(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return format_feedback_payload(study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post("/sessions/{study_session_id}/format-feedback-submit")
def submit_pre_result_format_feedback(
    study_session_id: str,
    request: StudyFormatExperienceSubmitCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = submit_format_feedback(
            db,
            study_session=study_session,
            rating_rows=request.ratings,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/results-status")
def get_results_status(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    return results_status(db, study_session)


def _view_result(
    *,
    study_session_id: str,
    request: StudyWorldCommand,
    recovery_token: str,
    position: int,
    db: DBSession,
):
    study_session = _authenticated_session(db, study_session_id, recovery_token)
    try:
        result = reveal_result(
            db,
            study_session=study_session,
            position=position,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    payload = _command_payload(result.study_session, replayed=result.replayed).model_dump(
        mode="json"
    )
    payload["position"] = position
    payload["total"] = current_result_payload(db, result.study_session)["total"]
    payload["evaluation_instrument"] = current_result_payload(
        db, result.study_session
    )["evaluation_instrument"]
    payload["report"] = result.report
    return payload


@router.post("/sessions/{study_session_id}/view-result-one")
def view_result_one(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    return _view_result(
        study_session_id=study_session_id,
        request=request,
        recovery_token=x_study_recovery_token,
        position=1,
        db=db,
    )


@router.post("/sessions/{study_session_id}/view-result-two")
def view_result_two(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    return _view_result(
        study_session_id=study_session_id,
        request=request,
        recovery_token=x_study_recovery_token,
        position=2,
        db=db,
    )


@router.get("/sessions/{study_session_id}/current-result")
def get_current_result(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return current_result_payload(db, study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post(
    "/sessions/{study_session_id}/result-rating",
    response_model=StudyCommandResponse,
)
def submit_current_result_rating(
    study_session_id: str,
    request: StudyResultEvaluationSubmitCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = submit_result_evaluation(
            db,
            study_session=study_session,
            rating_rows=request.ratings,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/begin-comparison",
    response_model=StudyCommandResponse,
)
def begin_comparative_feedback(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = begin_comparison(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/comparison")
def get_comparative_feedback(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return comparison_payload(study_session, db=db)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post(
    "/sessions/{study_session_id}/comparison-submit",
    response_model=StudyCommandResponse,
)
def submit_comparative_feedback(
    study_session_id: str,
    request: StudyComparativeFeedbackSubmitCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = submit_comparison(
            db,
            study_session=study_session,
            comparison_rows=request.comparisons,
            open_feedback_rows=request.open_feedback,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/debrief")
def get_study_debrief(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return get_debrief(db, study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.post(
    "/sessions/{study_session_id}/acknowledge-debrief",
    response_model=StudyCommandResponse,
)
def acknowledge_study_debrief(
    study_session_id: str,
    request: StudyWorldCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = acknowledge_debrief(
            db,
            study_session=study_session,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.get("/sessions/{study_session_id}/completion")
def get_completion_receipt(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        return completion_payload(db, study_session)
    except StudyWorkflowError as exc:
        _raise_http(exc)


@router.get("/sessions/{study_session_id}/compensation-status")
def get_compensation_status(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    return compensation_status(db, study_session)


@router.post(
    "/sessions/{study_session_id}/consent",
    response_model=StudyCommandResponse,
)
def submit_consent(
    study_session_id: str,
    request: StudyConsentCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    from study.protocol_v2 import enabled, consent_payload
    existing_consent = db.query(StudyConsentRecord).filter_by(study_session_id=study_session.id).one_or_none()
    consent = (consent_payload(existing_consent.consent_version) if existing_consent else consent_payload()) if enabled(study_session) else {"version":CONSENT_VERSION,"document_sha256":CONSENT_DOCUMENT_SHA256}
    if request.consent_version != consent["version"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "consent_version_mismatch", "message": "Consent version is not current."},
        )
    if request.document_sha256 != consent["document_sha256"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "consent_document_mismatch", "message": "Consent document is not current."},
        )
    target = (
        StudyWorkflowState.CONSENTED
        if request.action == "accept"
        else StudyWorkflowState.CONSENT_DECLINED
    )
    if request.action == "accept":
        record = db.query(StudyConsentRecord).filter_by(study_session_id=study_session.id).one_or_none()
        if record is None:
            db.add(
                StudyConsentRecord(
                    study_session_id=study_session.id,
                    consent_version=consent["version"],
                    document_sha256=consent["document_sha256"],
                    language=study_session.language,
                    accepted_at=utc_now(),
                )
            )
        elif (
            record.consent_version != consent["version"]
            or record.document_sha256 != consent["document_sha256"]
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "consent_record_collision", "message": "Consent record differs."},
            )
    try:
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=target,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
            source="participant",
            reason_code=f"consent_{request.action}",
            related_record_type="consent_record" if request.action == "accept" else None,
            related_record_id=consent["version"] if request.action == "accept" else None,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post(
    "/sessions/{study_session_id}/screening",
    response_model=StudyCommandResponse,
)
def submit_screening(
    study_session_id: str,
    request: StudyScreeningCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        pending = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ELIGIBILITY_PENDING,
            expected_revision=request.expected_revision,
            idempotency_key=f"{request.idempotency_key}:pending",
            source="participant",
            reason_code="screening_submitted",
        )
        eligible = all(
            (
                request.age_18_or_older,
                request.located_in_mainland_china,
                request.reads_chinese_and_has_computer,
                request.accepts_ai_interaction_and_recording,
            )
        )
        decision = db.query(StudyEligibilityDecision).filter_by(
            study_session_id=study_session.id
        ).one_or_none()
        if decision is None:
            decision = StudyEligibilityDecision(
                study_session_id=study_session.id,
                criteria_version=ELIGIBILITY_CRITERIA_VERSION,
                eligible=eligible,
                item_response_count=4,
                item_responses_deleted_at=utc_now(),
                evaluated_at=utc_now(),
            )
            db.add(decision)
            db.flush()
        elif decision.eligible != eligible:
            raise StudyWorkflowError(
                "Screening retry differs from the recorded decision.",
                409,
                "idempotency_collision",
            )
        target = (
            StudyWorkflowState.ELIGIBILITY_CONFIRMED
            if eligible
            else StudyWorkflowState.ELIGIBILITY_INELIGIBLE
        )
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=target,
            expected_revision=pending.study_session.revision,
            idempotency_key=f"{request.idempotency_key}:decision",
            source="system",
            reason_code="screening_eligible" if eligible else "screening_ineligible",
            related_record_type="eligibility_decision",
            related_record_id=ELIGIBILITY_CRITERIA_VERSION,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(
        result.study_session,
        replayed=pending.replayed and result.replayed,
    )


@router.post(
    "/sessions/{study_session_id}/contact",
    response_model=StudyCommandResponse,
)
def submit_contact(
    study_session_id: str,
    request: StudyContactCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    _idempotency_key = request.idempotency_key
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        contact, replayed = record_contact(db, study_session=study_session, email=request.email)
    except StudyWorkflowError as exc:
        _raise_http(exc)
    return _command_payload(study_session, replayed=replayed, research_id=contact.research_id)


@router.get("/sessions/{study_session_id}/onboarding-status")
def get_onboarding_status(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    if study_session.state not in {
        StudyWorkflowState.ELIGIBILITY_CONFIRMED.value,
        StudyWorkflowState.ONBOARDING.value,
    }:
        raise HTTPException(status_code=409, detail={"code": "invalid_transition"})
    contact = db.query(StudyContactRecord).filter_by(study_session_id=study_session.id).one_or_none()
    profile = db.query(StudyParticipantProfile).filter_by(study_session_id=study_session.id).one_or_none()
    from study.protocol_v2 import enabled
    from study.world_bridge_service import configured_world_available
    return {
        "items_optional":enabled(study_session),
        "study_world_available":configured_world_available(study_session),
        "world_version":"chaoxi-holiday-v6" if enabled(study_session) else None,
        "contact_received": contact is not None,
        "profile_completed": profile is not None,
        "research_id": contact.research_id if contact else None,
    }


@router.post(
    "/sessions/{study_session_id}/onboarding",
    response_model=StudyCommandResponse,
)
def submit_onboarding(
    study_session_id: str,
    request: StudyOnboardingCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        from study.protocol_v2 import enabled, progress
        if enabled(study_session) and progress(db,study_session).baseline_started_at is None:
            raise StudyWorkflowError("Open the baseline before submitting.",409,"baseline_not_started")
        profile = record_profile(
            db,
            study_session=study_session,
            nickname=request.nickname,
            gaming_frequency_code=request.gaming_frequency_code,
            social_game_experience_code=request.social_game_experience_code,
            ai_text_frequency_code=request.ai_text_frequency_code,
        )
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ONBOARDING,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
            source="participant",
            reason_code="onboarding_completed",
            related_record_type="participant_profile",
            related_record_id=profile.research_id,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return _command_payload(
        result.study_session,
        replayed=result.replayed,
        research_id=profile.research_id,
    )


@router.post(
    "/sessions/{study_session_id}/withdraw",
    response_model=StudyCommandResponse,
)
def withdraw_from_study(
    study_session_id: str,
    request: StudyWithdrawCommand,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    try:
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.WITHDRAWN,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
            source="participant",
            reason_code="participant_withdrew",
        )
    except StudyWorkflowError as exc:
        _raise_http(exc)
    return _command_payload(result.study_session, replayed=result.replayed)


@router.post("/test-fixtures/eligible-onboarding", response_model=StudyBootstrapResponse)
def create_eligible_onboarding_fixture(
    request: StudyBootstrapRequest,
    db: DBSession = Depends(get_study_db),
):
    fixture_enabled = os.getenv("STUDY_TEST_FIXTURES_ENABLED", "").lower() == "true"
    runtime = os.getenv("STUDY_RUNTIME_ENV", "").lower()
    if not fixture_enabled or runtime not in {"test", "development"}:
        raise HTTPException(status_code=404, detail={"code": "fixture_not_available"})
    try:
        bootstrap = bootstrap_study_session(
            db,
            language=request.language,
            idempotency_key=f"fixture:{request.idempotency_key}",
        )
        study_session = bootstrap.study_session
        if bootstrap.replayed:
            return StudyBootstrapResponse(
                study_session_id=study_session.public_id,
                state=study_session.state,
                revision=study_session.revision,
                recovery_token=None,
                recovery_token_issued=False,
                replayed=True,
                current_step_path=STEP_PATHS[StudyWorkflowState(study_session.state)],
            )
        db.add(
            StudyConsentRecord(
                study_session_id=study_session.id,
                consent_version=CONSENT_VERSION,
                document_sha256=CONSENT_DOCUMENT_SHA256,
                language=study_session.language,
                accepted_at=utc_now(),
            )
        )
        consented = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.CONSENTED,
            expected_revision=0,
            idempotency_key=f"{request.idempotency_key}:consent",
            source="test_fixture",
            reason_code="fixture_consent",
            related_record_type="consent_record",
            related_record_id=CONSENT_VERSION,
        )
        pending = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ELIGIBILITY_PENDING,
            expected_revision=consented.study_session.revision,
            idempotency_key=f"{request.idempotency_key}:pending",
            source="test_fixture",
            reason_code="fixture_screening",
        )
        db.add(
            StudyEligibilityDecision(
                study_session_id=study_session.id,
                criteria_version=ELIGIBILITY_CRITERIA_VERSION,
                eligible=True,
                item_response_count=4,
                item_responses_deleted_at=utc_now(),
                evaluated_at=utc_now(),
            )
        )
        confirmed = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ELIGIBILITY_CONFIRMED,
            expected_revision=pending.study_session.revision,
            idempotency_key=f"{request.idempotency_key}:eligible",
            source="test_fixture",
            reason_code="fixture_eligible",
            related_record_type="eligibility_decision",
            related_record_id=ELIGIBILITY_CRITERIA_VERSION,
        )
        record_contact(
            db,
            study_session=confirmed.study_session,
            email=f"fixture-{study_session.public_id[-12:]}@example.invalid",
        )
        profile = record_profile(
            db,
            study_session=confirmed.study_session,
            nickname="测试旅人",
            gaming_frequency_code="monthly_1_3",
            social_game_experience_code="5_20h",
            ai_text_frequency_code="monthly",
        )
        ready = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ONBOARDING,
            expected_revision=confirmed.study_session.revision,
            idempotency_key=f"{request.idempotency_key}:onboarding",
            source="test_fixture",
            reason_code="fixture_onboarding",
            related_record_type="participant_profile",
            related_record_id=profile.research_id,
        )
    except StudyWorkflowError as exc:
        db.rollback()
        _raise_http(exc)
    return StudyBootstrapResponse(
        study_session_id=ready.study_session.public_id,
        state=ready.study_session.state,
        revision=ready.study_session.revision,
        recovery_token=bootstrap.recovery_token,
        recovery_token_issued=True,
        replayed=False,
        current_step_path=STEP_PATHS[StudyWorkflowState(ready.study_session.state)],
    )


@router.post("/test-fixtures/sessions/{study_session_id}/complete-island-calendar")
def complete_fixture_island_calendar(
    study_session_id: str,
    x_study_recovery_token: str = Header(min_length=20, max_length=200),
    db: DBSession = Depends(get_study_db),
):
    fixture_enabled = os.getenv("STUDY_TEST_FIXTURES_ENABLED", "").lower() == "true"
    runtime = os.getenv("STUDY_RUNTIME_ENV", "").lower()
    if not fixture_enabled or runtime not in {"test", "development"}:
        raise HTTPException(status_code=404, detail={"code": "fixture_not_available"})
    study_session = _authenticated_session(db, study_session_id, x_study_recovery_token)
    if study_session.state != StudyWorkflowState.ISLAND_ACTIVE.value:
        raise HTTPException(status_code=409, detail={"code": "invalid_transition"})
    if study_session.world_session_id is None:
        raise HTTPException(status_code=409, detail={"code": "world_not_bound"})
    world_session = db.query(WorldSession).filter_by(id=study_session.world_session_id).one()
    world = db.query(WorldState).filter_by(session_id=world_session.id).one()
    spec = get_world_spec(world.world_version)
    world.current_day = spec.calendar.total_days
    world.current_time_minutes = spec.calendar.day_end_minute
    world_session.current_day = spec.calendar.total_days
    world.updated_at = utc_now()
    db.commit()
    return {
        "world_session_id": world_session.id,
        "day": world.current_day,
        "time_minutes": world.current_time_minutes,
    }
