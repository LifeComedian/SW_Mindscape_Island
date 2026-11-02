"""Available-report flow; guarded by the session's frozen V2 workflow version."""
import json
import secrets
from study.models import StudyAvailableResults, StudyGameEstimate, StudyQuestionnaireScore, StudyQuestionnaireResponse, StudySession, StudyAssessmentJob
from study.contracts import StudyWorkflowState as State
from study.service import StudyWorkflowError, transition_study_session, utc_now
from study.protocol_v2 import canonical, digest, evaluation_instrument

def record(db, session):
    row=db.query(StudyAvailableResults).filter_by(study_session_id=session.id).one_or_none()
    if row is None: raise StudyWorkflowError('Report order is not frozen.',409,'result_order_missing')
    if digest({'availability':json.loads(row.availability_json),'order':json.loads(row.order_json)}) != row.order_sha256:
        raise StudyWorkflowError('Report order integrity mismatch.',409,'result_hash_mismatch')
    return row

def _prepare(db, session):
    if session.state != State.QUESTIONNAIRE_COMPLETED.value: return session
    game=db.query(StudyGameEstimate).filter_by(study_session_id=session.id,analysis_version=1).one_or_none()
    score=db.query(StudyQuestionnaireScore).filter_by(study_session_id=session.id).one_or_none()
    response=db.query(StudyQuestionnaireResponse).filter_by(study_session_id=session.id).one()
    availability={
      'game_estimate':{'available':game is not None,'reason':None if game else 'technical_failure','sha256':game.output_sha256 if game else None},
      'questionnaire':{'available':score is not None,'reason':None if score else 'incomplete_answers','sha256':score.result_sha256 if score else None,
                       'answered_count':len(json.loads(response.answers_json))}}
    order=[kind for kind,value in availability.items() if value['available']]
    if len(order)==2 and secrets.randbits(1): order.reverse()
    row=db.query(StudyAvailableResults).filter_by(study_session_id=session.id).one_or_none()
    if row is None:
        row=StudyAvailableResults(study_session_id=session.id,availability_json=canonical(availability),order_json=canonical(order),
             order_sha256=digest({'availability':availability,'order':order}),evaluations_json='[]')
        db.add(row);db.flush()
    else: order=json.loads(record(db,session).order_json)
    return transition_study_session(db,study_session_id=session.id,requested_state=State.RESULTS_READY if order else State.COMPARATIVE_FEEDBACK,
        expected_revision=session.revision,idempotency_key=f'available-results:{session.id}',source='system',reason_code='available_reports_frozen',
        related_record_type='available_results',related_record_id=str(row.id)).study_session

def prepare(db,session):
    from study.results_service import _lock
    session_id=session.id
    with _lock(session_id):
        db.rollback()
        return _prepare(db,db.get(StudySession,session_id))

def status(db,session):
    row=db.query(StudyAvailableResults).filter_by(study_session_id=session.id).one_or_none()
    if row is not None: row=record(db,session)
    order=json.loads(row.order_json) if row else []
    position={State.RESULT_ONE_ACTIVE.value:1,State.RESULT_TWO_ACTIVE.value:2}.get(session.state)
    return {'state':session.state,'revision':session.revision,'order_generated':row is not None,'order_sha256':row.order_sha256 if row else None,
      'active_position':position,'active_report_kind':order[position-1] if position else None,'total':len(order),
      'submitted_evaluation_count':sum(bool(e.get('submitted_at')) for e in json.loads(row.evaluations_json)) if row else 0,
      'availability':json.loads(row.availability_json) if row else {},'report_body_exposed':False}

def report(db,session,kind):
    from study.results_service import _game_report_payload, _questionnaire_report_payload
    availability=json.loads(record(db,session).availability_json)[kind]
    if not availability['available']: raise StudyWorkflowError('Report unavailable.',409,'result_not_available')
    if kind=='game_estimate':
        item=db.query(StudyGameEstimate).filter_by(study_session_id=session.id,analysis_version=1).one()
        hashed=item.output_sha256; payload=_game_report_payload(item)
        job=db.get(StudyAssessmentJob,item.assessment_job_id)
        actual=digest({'result':json.loads(item.result_json),'report_text':item.report_text,'package':job.package_sha256})
    else:
        item=db.query(StudyQuestionnaireScore).filter_by(study_session_id=session.id).one()
        hashed=item.result_sha256; payload=_questionnaire_report_payload(item)
        response=db.get(StudyQuestionnaireResponse,item.questionnaire_response_id)
        actual=digest({'instrument_sha256':response.instrument_sha256,'scoring_version':item.scoring_version,
            'transformed_item_scores':{int(k):v for k,v in json.loads(item.transformed_item_scores_json).items()},'domain_scores':json.loads(item.domain_scores_json),
            'facet_scores':json.loads(item.facet_scores_json),'report_template_version':item.report_template_version,'report_text':item.report_text})
    if availability['sha256']!=hashed or actual!=hashed: raise StudyWorkflowError('Report hash mismatch.',409,'result_hash_mismatch')
    return payload

def current(db,session):
    position={State.RESULT_ONE_ACTIVE.value:1,State.RESULT_TWO_ACTIVE.value:2}.get(session.state)
    if position is None: raise StudyWorkflowError('No active report.',409,'result_not_active')
    row=record(db,session);order=json.loads(row.order_json)
    return {'position':position,'total':len(order),'availability':json.loads(row.availability_json),
            'evaluation_instrument':evaluation_instrument(),'report':report(db,session,order[position-1])}

def reveal(db,session,position,revision,key):
    from study.results_service import ResultFlowResponse, _lock
    with _lock(session.id):
        db.rollback();session=db.get(StudySession,session.id);row=record(db,session);order=json.loads(row.order_json)
        if position not in range(1,len(order)+1): raise StudyWorkflowError('Report unavailable.',409,'result_not_available')
        active=State.RESULT_ONE_ACTIVE if position==1 else State.RESULT_TWO_ACTIVE
        required=State.RESULTS_READY if position==1 else State.RESULT_ONE_RATED
        if session.state==active.value: return ResultFlowResponse(session,True,report(db,session,order[position-1]))
        if session.state!=required.value: raise StudyWorkflowError('Report unavailable.',409,'result_not_available')
        evaluations=json.loads(row.evaluations_json)
        evaluations.append({'report_kind':order[position-1],'presentation_position':position,'first_viewed_at':utc_now().isoformat(),
                            'instrument_version':evaluation_instrument()['instrument_version'],'instrument_sha256':evaluation_instrument()['instrument_sha256']})
        row.evaluations_json=canonical(evaluations)
        result=transition_study_session(db,study_session_id=session.id,requested_state=active,expected_revision=revision,idempotency_key=key,
             source='participant',reason_code=f'result_{position}_first_viewed',related_record_type='available_results',related_record_id=str(row.id))
        return ResultFlowResponse(result.study_session,result.replayed,report(db,result.study_session,order[position-1]))

def submit(db,session,ratings,revision,key):
    from study.results_service import ResultFlowResponse, _lock, _result_ratings
    values=_result_ratings(ratings)
    with _lock(session.id):
        db.rollback();session=db.get(StudySession,session.id);row=record(db,session)
        evaluations=json.loads(row.evaluations_json);order=json.loads(row.order_json)
        for e in evaluations:
            if e.get('submit_idempotency_key')==key:
                if e['ratings']!=values: raise StudyWorkflowError('Request changed.',409,'idempotency_collision')
                return ResultFlowResponse(session,True)
        position={State.RESULT_ONE_ACTIVE.value:1,State.RESULT_TWO_ACTIVE.value:2}.get(session.state)
        if position is None: raise StudyWorkflowError('Evaluation inactive.',409,'result_evaluation_not_active')
        e=evaluations[position-1]
        e.update(ratings=values,ratings_sha256=digest({'instrument_sha256':e['instrument_sha256'],'report_kind':e['report_kind'],'ratings':values}),
                 submitted_at=utc_now().isoformat(),submit_idempotency_key=key)
        row.evaluations_json=canonical(evaluations)
        target=State.COMPARATIVE_FEEDBACK if position==len(order) else State.RESULT_ONE_RATED
        result=transition_study_session(db,study_session_id=session.id,requested_state=target,expected_revision=revision,idempotency_key=key,
            source='participant',reason_code='available_report_evaluation_frozen',related_record_type='available_results',related_record_id=str(row.id))
        return ResultFlowResponse(result.study_session,result.replayed)

def not_applicable_items(db,session):
    availability=json.loads(record(db,session).availability_json)
    return [] if all(v['available'] for v in availability.values()) else [6,7,8]
