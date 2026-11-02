"""Comparative questionnaire flow for the holiday study."""
from study.models import StudyWorldBoundary, StudyResultPresentation
from study.contracts import StudyWorkflowState as State


def applies(db, session):
    return db.query(StudyWorldBoundary.id).filter(StudyWorldBoundary.study_session_id==session.id, StudyWorldBoundary.world_version.in_(('chaoxi-holiday-v3','chaoxi-holiday-v4','chaoxi-holiday-v5','chaoxi-holiday-v6'))).first() is not None


def prepare_results(db, session):
    from study.protocol_v2 import enabled
    if enabled(session):
        from study.available_results import prepare
        return prepare(db, session)
    if session.state != State.QUESTIONNAIRE_COMPLETED.value or not applies(db, session):
        return session
    from study.results_service import _frozen_results, _sha, GAME_ESTIMATE_KIND, QUESTIONNAIRE_KIND
    from study.service import transition_study_session, utc_now
    import secrets
    game, score = _frozen_results(db,session.id)
    presentation = db.query(StudyResultPresentation).filter_by(study_session_id=session.id).first()
    if not presentation:
        first,second = (GAME_ESTIMATE_KIND,QUESTIONNAIRE_KIND) if secrets.randbits(1)==0 else (QUESTIONNAIRE_KIND,GAME_ESTIMATE_KIND)
        material = {'result_one_kind':first,'result_two_kind':second,'game_output_sha256':game.output_sha256,'questionnaire_result_sha256':score.result_sha256}
        presentation = StudyResultPresentation(study_session_id=session.id,game_estimate_id=game.id,questionnaire_score_id=score.id,
            result_one_kind=first,result_two_kind=second,game_output_sha256=game.output_sha256,questionnaire_result_sha256=score.result_sha256,
            order_sha256=_sha(material),generated_at=utc_now())
        db.add(presentation); db.flush()
    session.workflow_version='holiday-v3-final-feedback-only'
    return transition_study_session(db,study_session_id=session.id,requested_state=State.RESULTS_READY,
        expected_revision=session.revision,idempotency_key=f'v3-results:{session.id}',source='system',
        reason_code='holiday_v3_no_pre_result_feedback',related_record_type='result_presentation',related_record_id=str(presentation.id)).study_session
