from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import os
from typing import Any

from sqlalchemy.orm import Session as DBSession

from models import Session as WorldSession
from study.models import (
    StudyAssessmentAttempt,
    StudyAssessmentJob,
    StudyComparativeFeedback,
    StudyCompletionReceipt,
    StudyConsentRecord,
    StudyDebriefAcknowledgement,
    StudyEligibilityDecision,
    StudyFeatureSnapshot,
    StudyFormatExperienceResponse,
    StudyGameEstimate,
    StudyObservationRecord,
    StudyParticipantProfile,
    StudyQuestionnaireResponse,
    StudyQuestionnaireScore,
    StudyResultEvaluation,
    StudyResultPresentation,
    StudySession,
    StudyWorldBoundary,
    StudyWorkflowTransition,
)
from study.service import StudyWorkflowError, utc_now


RESEARCH_EXPORT_SCHEMA_VERSION = "study-research-export-v1"
RESEARCH_EXPORT_POLICY_VERSION = "minimum-necessary-no-direct-identifiers-v1"


def authorize_research_export(supplied_key: str | None) -> None:
    """Fail closed unless a dedicated, high-entropy local/admin key is configured."""

    configured = os.getenv("STUDY_RESEARCH_EXPORT_KEY", "")
    if len(configured) < 32:
        raise StudyWorkflowError(
            "Research export is not configured.", 503, "research_export_disabled"
        )
    if supplied_key is None or not hmac.compare_digest(configured, supplied_key):
        # Do not reveal whether a study identifier exists to an unauthenticated caller.
        raise StudyWorkflowError("Research export not found.", 404, "research_export_not_found")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text_dispositions(value: str | None) -> list[dict[str, Any]]:
    rows = _json(value, [])
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row.get("value")
        has_text = isinstance(text, str) and bool(text)
        result.append(
            {
                "item_number": row.get("item_number"),
                "skipped": bool(row.get("skipped")),
                "response_present": has_text,
                "response_character_count": len(text) if has_text else 0,
                "response_sha256": (
                    hashlib.sha256(text.encode("utf-8")).hexdigest() if has_text else None
                ),
            }
        )
    return result


def _export_features(value):
    features = _json(value, {})
    facts = features.pop('controlled_letter_facts', None)
    if facts is not None:
        features['controlled_letter_summary'] = {'version':facts['version'],
            'source_sha256':facts['source_sha256'], 'fact_count':len(facts['cards']),
            'player_actions':facts['coverage']['player_actions']}
    return features


def _estimate_summary(value: str | None) -> dict[str, Any]:
    stored = _json(value, {})
    if not isinstance(stored, dict):
        return {}
    domains = stored.get("domains", [])
    safe_domains: list[dict[str, Any]] = []
    if isinstance(domains, list):
        for domain in domains:
            if not isinstance(domain, dict):
                continue
            safe_domains.append(
                {
                    "domain_id": domain.get("domain_id"),
                    "status": domain.get("status"),
                    "value": domain.get("value"),
                    "basis": domain.get("basis") if isinstance(domain.get("basis"), list) else [],
                }
            )
    return {
        "schema_version": stored.get("schema_version"),
        "result_kind": stored.get("result_kind"),
        "fixture_only": stored.get("fixture_only"),
        "watermark": stored.get("watermark"),
        "data_sufficiency": stored.get("data_sufficiency"),
        "domains": safe_domains,
    }


def _one(db: DBSession, model: type[Any], study_session_id: int) -> Any | None:
    return db.query(model).filter_by(study_session_id=study_session_id).one_or_none()


def build_research_export(
    db: DBSession,
    *,
    study_session_public_id: str,
) -> dict[str, Any]:
    """Build a pseudonymous, minimum-necessary research record.

    This deliberately never queries the restricted contact table, questionnaire
    answer JSON, completion-code ciphertext, game nickname, or raw world text.
    """

    study = (
        db.query(StudySession)
        .filter(StudySession.public_id == study_session_public_id)
        .one_or_none()
    )
    if study is None:
        raise StudyWorkflowError("Research export not found.", 404, "research_export_not_found")

    consent = _one(db, StudyConsentRecord, study.id)
    eligibility = _one(db, StudyEligibilityDecision, study.id)
    profile = _one(db, StudyParticipantProfile, study.id)
    boundary = _one(db, StudyWorldBoundary, study.id)
    feature = _one(db, StudyFeatureSnapshot, study.id)
    job = (
        db.query(StudyAssessmentJob)
        .filter_by(study_session_id=study.id, analysis_version=1)
        .one_or_none()
    )
    estimate = (
        db.query(StudyGameEstimate)
        .filter_by(study_session_id=study.id, analysis_version=1)
        .one_or_none()
    )
    questionnaire_response = _one(db, StudyQuestionnaireResponse, study.id)
    questionnaire_score = _one(db, StudyQuestionnaireScore, study.id)
    format_feedback = _one(db, StudyFormatExperienceResponse, study.id)
    presentation = _one(db, StudyResultPresentation, study.id)
    comparative = _one(db, StudyComparativeFeedback, study.id)
    debrief = _one(db, StudyDebriefAcknowledgement, study.id)
    receipt = _one(db, StudyCompletionReceipt, study.id)
    world_session = (
        db.query(WorldSession).filter_by(id=study.world_session_id).one_or_none()
        if study.world_session_id is not None
        else None
    )

    transitions = (
        db.query(StudyWorkflowTransition)
        .filter_by(study_session_id=study.id)
        .order_by(StudyWorkflowTransition.result_revision.asc())
        .all()
    )
    observations = (
        db.query(StudyObservationRecord)
        .filter_by(study_session_id=study.id)
        .order_by(StudyObservationRecord.occurred_at.asc(), StudyObservationRecord.id.asc())
        .all()
    )
    attempts = (
        db.query(StudyAssessmentAttempt)
        .filter_by(assessment_job_id=job.id)
        .order_by(StudyAssessmentAttempt.attempt_number.asc())
        .all()
        if job is not None
        else []
    )
    result_evaluations = (
        db.query(StudyResultEvaluation)
        .filter_by(study_session_id=study.id)
        .order_by(StudyResultEvaluation.presentation_position.asc())
        .all()
    )

    record: dict[str, Any] = {
        "participant": {
            "research_id": profile.research_id if profile else None,
            "language": study.language,
            "baseline": (
                {
                    "version": profile.baseline_version,
                    "gaming_frequency_code": profile.gaming_frequency_code,
                    "social_game_experience_code": profile.social_game_experience_code,
                    "ai_text_frequency_code": profile.ai_text_frequency_code,
                }
                if profile
                else None
            ),
        },
        "workflow": {
            "state": study.state,
            "revision": study.revision,
            "compensation_stage": study.compensation_stage,
            "terminal_reason_code": study.terminal_reason_code,
            "created_at": _iso(study.created_at),
            "updated_at": _iso(study.updated_at),
            "completed_at": _iso(study.completed_at),
            "transitions": [
                {
                    "from_state": row.from_state,
                    "to_state": row.to_state,
                    "expected_revision": row.expected_revision,
                    "result_revision": row.result_revision,
                    "source": row.source,
                    "reason_code": row.reason_code,
                    "related_record_type": row.related_record_type,
                    "occurred_at": _iso(row.created_at),
                }
                for row in transitions
            ],
        },
        "versions": {
            "study_contract_version": study.study_contract_version,
            "workflow_version": study.workflow_version,
            "consent_version": consent.consent_version if consent else None,
            "consent_document_sha256": consent.document_sha256 if consent else None,
            "eligibility_criteria_version": (
                eligibility.criteria_version if eligibility else None
            ),
        },
        "eligibility": (
            {
                "eligible": eligibility.eligible,
                "item_response_count": eligibility.item_response_count,
                "item_responses_deleted_at": _iso(eligibility.item_responses_deleted_at),
                "evaluated_at": _iso(eligibility.evaluated_at),
            }
            if eligibility
            else None
        ),
        "game_boundary": (
            {
                "binding_mode": boundary.binding_mode,
                "world_version": boundary.world_version,
                "scenario_pack_version": boundary.scenario_pack_version,
                "simulation_seed": world_session.simulation_seed if world_session else None,
                "observation_schema_version": boundary.observation_schema_version,
                "feature_schema_version": boundary.feature_schema_version,
                "bound_at": _iso(boundary.bound_at),
                "frozen_at": _iso(boundary.frozen_at),
                "final_action_count": boundary.final_action_count,
                "final_world_day": boundary.final_world_day,
                "final_world_time_minutes": boundary.final_world_time_minutes,
                "final_state_sha256": boundary.final_state_sha256,
                "integrity_status": boundary.integrity_status,
            }
            if boundary
            else None
        ),
        "observations": [
            {
                "observation_id": row.observation_id,
                "schema_version": row.schema_version,
                "source_type": row.source_type,
                "source_record_id": row.source_record_id,
                "occurred_at": _iso(row.occurred_at),
                "world_day": row.world_day,
                "world_time_minutes": row.world_time_minutes,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "observation_type": row.observation_type,
                "location_id": row.location_id,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "opportunity_id": row.opportunity_id,
                "offered_option_ids": _json(row.offered_option_ids_json, []),
                "available_option_ids": _json(row.available_option_ids_json, []),
                "selected_option_id": row.selected_option_id,
                "outcome_code": row.outcome_code,
                "technical_status": row.technical_status,
                "versions": _json(row.versions_json, {}),
            }
            for row in observations
        ],
        "feature_snapshot": (
            {
                "extractor_version": feature.extractor_version,
                "feature_schema_version": feature.feature_schema_version,
                "features": _export_features(feature.features_json),
                "opportunity_denominators": _json(
                    feature.opportunity_denominators_json, {}
                ),
                "missing_reasons": _json(feature.missing_reasons_json, {}),
                "sufficient": feature.sufficient,
                "observation_count": feature.observation_count,
                "frozen_at": _iso(feature.frozen_at),
            }
            if feature
            else None
        ),
        "assessment": {
            "job": (
                {
                    "analysis_version": job.analysis_version,
                    "mode": job.mode,
                    "status": job.status,
                    "package_id": job.package_id,
                    "package_version": job.package_version,
                    "package_sha256": job.package_sha256,
                    "input_sha256": job.input_sha256,
                    "attempt_count": job.attempt_count,
                    "last_error_code": job.last_error_code,
                    "created_at": _iso(job.created_at),
                    "completed_at": _iso(job.completed_at),
                }
                if job
                else None
            ),
            "attempts": [
                {
                    "attempt_number": row.attempt_number,
                    "request_schema_version": row.request_schema_version,
                    "request_sha256": row.request_sha256,
                    "status": row.status,
                    "error_code": row.error_code,
                    "response_sha256": row.response_sha256,
                    "started_at": _iso(row.started_at),
                    "completed_at": _iso(row.completed_at),
                }
                for row in attempts
            ],
            "result": (
                {
                    "analysis_version": estimate.analysis_version,
                    "result_schema_version": estimate.result_schema_version,
                    "result_kind": estimate.result_kind,
                    "fixture_only": estimate.fixture_only,
                    "structured_result": _estimate_summary(estimate.result_json),
                    "output_sha256": estimate.output_sha256,
                    "frozen_at": _iso(estimate.frozen_at),
                }
                if estimate
                else None
            ),
        },
        "questionnaire_scoring": (
            {
                "instrument_id": questionnaire_response.instrument_id,
                "instrument_version": questionnaire_response.instrument_version,
                "instrument_sha256": questionnaire_response.instrument_sha256,
                "language": questionnaire_response.language,
                "submitted_at": _iso(questionnaire_response.submitted_at),
                "scoring_version": questionnaire_score.scoring_version,
                "domain_scores": _json(questionnaire_score.domain_scores_json, {}),
                "facet_scores": _json(questionnaire_score.facet_scores_json, {}),
                "report_template_version": questionnaire_score.report_template_version,
                "result_sha256": questionnaire_score.result_sha256,
                "frozen_at": _iso(questionnaire_score.frozen_at),
            }
            if questionnaire_response and questionnaire_score
            else None
        ),
        "result_presentation": (
            {
                "result_one_kind": presentation.result_one_kind,
                "result_two_kind": presentation.result_two_kind,
                "game_output_sha256": presentation.game_output_sha256,
                "questionnaire_result_sha256": presentation.questionnaire_result_sha256,
                "order_sha256": presentation.order_sha256,
                "generated_at": _iso(presentation.generated_at),
            }
            if presentation
            else None
        ),
        "feedback": {
            "format_experience": (
                {
                    "instrument_version": format_feedback.instrument_version,
                    "instrument_sha256": format_feedback.instrument_sha256,
                    "ratings": _json(format_feedback.ratings_json, []),
                    "ratings_sha256": format_feedback.ratings_sha256,
                    "submitted_at": _iso(format_feedback.submitted_at),
                }
                if format_feedback
                else None
            ),
            "result_evaluations": [
                {
                    "report_kind": row.report_kind,
                    "presentation_position": row.presentation_position,
                    "instrument_version": row.instrument_version,
                    "instrument_sha256": row.instrument_sha256,
                    "first_viewed_at": _iso(row.first_viewed_at),
                    "ratings": _json(row.ratings_json, []) if row.ratings_json else None,
                    "ratings_sha256": row.ratings_sha256,
                    "submitted_at": _iso(row.submitted_at),
                }
                for row in result_evaluations
            ],
            "comparative": (
                {
                    "instrument_version": comparative.instrument_version,
                    "instrument_sha256": comparative.instrument_sha256,
                    "comparisons": _json(comparative.comparisons_json, []),
                    "open_response_dispositions": _text_dispositions(
                        comparative.open_feedback_json
                    ),
                    "payload_sha256": comparative.payload_sha256,
                    "submitted_at": _iso(comparative.submitted_at),
                }
                if comparative
                else None
            ),
        },
        "debrief": (
            {
                "debrief_version": debrief.debrief_version,
                "debrief_sha256": debrief.debrief_sha256,
                "presented_at": _iso(debrief.presented_at),
                "acknowledged_at": _iso(debrief.acknowledged_at),
            }
            if debrief
            else None
        ),
        "completion": (
            {
                "receipt_issued": True,
                "receipt_version": receipt.receipt_version,
                "generated_at": _iso(receipt.generated_at),
            }
            if receipt
            else {"receipt_issued": False}
        ),
    }
    from study.protocol_v2 import enabled
    if enabled(study):
        from study.models import StudyAvailableResults, StudyProtocolProgress
        progress=db.get(StudyProtocolProgress,study.id)
        record["workflow"]["formal_activity_started_at"]=_iso(progress.baseline_started_at) if progress else None
        available=db.query(StudyAvailableResults).filter_by(study_session_id=study.id).one_or_none()
        record["questionnaire_response_status"]={"submitted":questionnaire_response is not None, "answered_count":len(_json(questionnaire_response.answers_json,{})) if questionnaire_response else None, "scored":questionnaire_score is not None, "missing_policy":"no_imputation"}
        if available:
            order=_json(available.order_json,[])
            record["result_presentation"]={"result_one_kind":order[0] if order else None,"result_two_kind":order[1] if len(order)>1 else None,"order_sha256":available.order_sha256,"availability":_json(available.availability_json,{}),"generated_at":_iso(available.generated_at)}
            record["feedback"]["result_evaluations"]=[{k:v for k,v in e.items() if k!="submit_idempotency_key"} for e in _json(available.evaluations_json,[])]
    return {
        "export_schema_version": RESEARCH_EXPORT_SCHEMA_VERSION,
        "data_minimization_policy_version": RESEARCH_EXPORT_POLICY_VERSION,
        "generated_at": _iso(utc_now()),
        "record_sha256": _sha(record),
        "record": record,
    }
