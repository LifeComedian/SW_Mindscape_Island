from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import threading
from typing import Any, Iterable

from sqlalchemy.orm import Session as DBSession

from study.bfi2_instrument import (
    INSTRUMENT_ID,
    INSTRUMENT_LANGUAGE,
    INSTRUMENT_SHA256,
    INSTRUMENT_VERSION,
    REPORT_TEMPLATE_VERSION,
    SCORING_VERSION,
    participant_instrument_payload,
    render_neutral_report,
    score_bfi2,
    validate_answers,
)
from study.contracts import StudyWorkflowState
from study.protocol_v2 import enabled
from study.models import (
    StudyGameEstimate,
    StudyQuestionnaireDraft,
    StudyQuestionnaireResponse,
    StudyQuestionnaireScore,
    StudySession,
)
from study.service import StudyWorkflowError, transition_study_session, utc_now


_QUESTIONNAIRE_LOCKS: dict[int, threading.Lock] = {}
_QUESTIONNAIRE_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class QuestionnaireResult:
    study_session: StudySession
    response: StudyQuestionnaireResponse | None
    score: StudyQuestionnaireScore | None
    replayed: bool


def _lock(study_session_id: int) -> threading.Lock:
    with _QUESTIONNAIRE_LOCKS_GUARD:
        return _QUESTIONNAIRE_LOCKS.setdefault(study_session_id, threading.Lock())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _answer_map(answer_rows: Iterable[Any], *, complete: bool) -> dict[int, int]:
    rows = list(answer_rows)
    item_numbers = [int(row.item_number) for row in rows]
    if len(set(item_numbers)) != len(item_numbers):
        raise StudyWorkflowError(
            "Each questionnaire item may be answered only once.",
            422,
            "questionnaire_duplicate_item",
        )
    answers = {int(row.item_number): int(row.value) for row in rows}
    if complete:
        try:
            return validate_answers(answers)
        except ValueError as exc:
            raise StudyWorkflowError(
                str(exc), 422, "questionnaire_answers_incomplete"
            ) from exc
    if any(item not in range(1, 61) or value not in range(1, 6) for item, value in answers.items()):
        raise StudyWorkflowError(
            "Draft answers must use items 1 through 60 and values 1 through 5.",
            422,
            "questionnaire_answer_invalid",
        )
    return dict(sorted(answers.items()))


def _frozen_game_estimate_exists(db: DBSession, study_session_id: int) -> bool:
    estimate = (
        db.query(StudyGameEstimate)
        .filter_by(study_session_id=study_session_id, analysis_version=1)
        .one_or_none()
    )
    return estimate is not None


def begin_questionnaire(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> QuestionnaireResult:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        if study_session.state == StudyWorkflowState.QUESTIONNAIRE_ACTIVE.value:
            return QuestionnaireResult(study_session, None, None, True)
        if study_session.state not in {
            StudyWorkflowState.GAME_ESTIMATE_FROZEN.value,
            StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT.value,
            *([StudyWorkflowState.GAME_ESTIMATE_FAILED.value] if enabled(study_session) else []),
        }:
            raise StudyWorkflowError(
                "The questionnaire is unavailable before the island estimate is frozen.",
                409,
                "questionnaire_not_available",
            )
        if not _frozen_game_estimate_exists(db, study_session.id) and not (enabled(study_session) and study_session.state == StudyWorkflowState.GAME_ESTIMATE_FAILED.value):
            raise StudyWorkflowError(
                "The island estimate boundary is missing.",
                409,
                "game_estimate_not_frozen",
            )
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.QUESTIONNAIRE_ACTIVE,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="bfi2_questionnaire_started",
            related_record_type="instrument",
            related_record_id=INSTRUMENT_VERSION,
        )
        return QuestionnaireResult(result.study_session, None, None, result.replayed)


def questionnaire_payload(db: DBSession, study_session: StudySession) -> dict[str, Any]:
    if study_session.state != StudyWorkflowState.QUESTIONNAIRE_ACTIVE.value:
        raise StudyWorkflowError(
            "Questionnaire content is available only during the questionnaire stage.",
            409,
            "questionnaire_not_active",
        )
    draft = db.query(StudyQuestionnaireDraft).filter_by(study_session_id=study_session.id).one_or_none()
    payload = participant_instrument_payload()
    payload.update(
        {
            "draft_revision": draft.revision if draft else 0,
            "draft_answers": json.loads(draft.answers_json) if draft else {},
            "answer_count": len(json.loads(draft.answers_json)) if draft else 0,
            "required_answer_count": 0 if enabled(study_session) else 60,
            "items_optional": enabled(study_session),
            "scoring_key_exposed": False,
        }
    )
    if enabled(study_session):
        from study.models import StudyProtocolProgress
        saved=db.get(StudyProtocolProgress,study_session.id)
        payload["draft_skipped_items"]=json.loads(saved.questionnaire_skipped_json) if saved else []
        payload["instructions"] += " 每题均可跳过。只有60题全部作答才生成完整问卷报告；缺题仍可继续，补偿资格不受影响。"
    return payload


def save_questionnaire_draft(
    db: DBSession,
    *,
    study_session: StudySession,
    answer_rows: Iterable[Any],
    expected_draft_revision: int,
    idempotency_key: str,
    skipped_items: list[int] | None = None,
) -> dict[str, Any]:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        if study_session.state != StudyWorkflowState.QUESTIONNAIRE_ACTIVE.value:
            raise StudyWorkflowError(
                "Questionnaire drafts cannot be changed at this stage.",
                409,
                "questionnaire_not_active",
            )
        answers = _answer_map(answer_rows, complete=False)
        skipped=skipped_items or []
        if skipped and (not enabled(study_session) or any(type(n) is not int or n not in range(1,61) for n in skipped) or len(set(skipped))!=len(skipped) or set(skipped)&set(answers)):
            raise StudyWorkflowError("Invalid skipped items.",422,"questionnaire_disposition_invalid")
        payload_hash = _sha({"instrument_sha256":INSTRUMENT_SHA256,"answers":answers,**({"skipped_items":sorted(skipped)} if enabled(study_session) else {})})
        draft = db.query(StudyQuestionnaireDraft).filter_by(study_session_id=study_session.id).one_or_none()
        if draft is not None and draft.last_idempotency_key == idempotency_key:
            if draft.last_payload_sha256 != payload_hash:
                raise StudyWorkflowError(
                    "Draft idempotency key was reused with different answers.",
                    409,
                    "idempotency_collision",
                )
            return {
                "draft_revision": draft.revision,
                "answer_count": len(answers),
                "replayed": True,
            }
        actual_revision = draft.revision if draft else 0
        if actual_revision != expected_draft_revision:
            raise StudyWorkflowError(
                "Questionnaire draft revision is stale.",
                409,
                "stale_draft_revision",
            )
        now = utc_now()
        if enabled(study_session):
            from study.protocol_v2 import progress
            progress(db,study_session).questionnaire_skipped_json=_canonical(sorted(skipped))
        if draft is None:
            draft = StudyQuestionnaireDraft(
                study_session_id=study_session.id,
                instrument_id=INSTRUMENT_ID,
                instrument_version=INSTRUMENT_VERSION,
                instrument_sha256=INSTRUMENT_SHA256,
                language=INSTRUMENT_LANGUAGE,
                answers_json=_canonical(answers),
                revision=1,
                last_idempotency_key=idempotency_key,
                last_payload_sha256=payload_hash,
                created_at=now,
                updated_at=now,
            )
            db.add(draft)
        else:
            draft.answers_json = _canonical(answers)
            draft.revision += 1
            draft.last_idempotency_key = idempotency_key
            draft.last_payload_sha256 = payload_hash
            draft.updated_at = now
        db.commit()
        db.refresh(draft)
        return {
            "draft_revision": draft.revision,
            "answer_count": len(answers),
            "replayed": False,
        }


def submit_questionnaire(
    db: DBSession,
    *,
    study_session: StudySession,
    answer_rows: Iterable[Any],
    expected_revision: int,
    idempotency_key: str,
    skipped_items: list[int] | None = None,
) -> QuestionnaireResult:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        answers = _answer_map(answer_rows, complete=not enabled(study_session))
        skipped = skipped_items or []
        if enabled(study_session) and (any(type(n) is not int for n in skipped) or len(set(skipped))!=len(skipped) or set(skipped) & set(answers) or set(skipped) | set(answers) != set(range(1,61))):
            raise StudyWorkflowError("Each item needs an answer or explicit skip.",422,"questionnaire_disposition_incomplete")
        answers_payload = {
            "instrument_sha256": INSTRUMENT_SHA256,
            "answers": answers,
        }
        answers_sha256 = _sha(answers_payload)
        existing_response = (
            db.query(StudyQuestionnaireResponse)
            .filter_by(study_session_id=study_session.id)
            .one_or_none()
        )
        if existing_response is not None:
            existing_score = (
                db.query(StudyQuestionnaireScore)
                .filter_by(study_session_id=study_session.id)
                .one_or_none()
            )
            if existing_response.answers_sha256 != answers_sha256:
                raise StudyWorkflowError(
                    "The submitted questionnaire is frozen and cannot be changed.",
                    409,
                    "questionnaire_frozen",
                )
            from study.holiday_flow import prepare_results
            study_session = prepare_results(db, study_session)
            return QuestionnaireResult(study_session, existing_response, existing_score, True)
        if study_session.state != StudyWorkflowState.QUESTIONNAIRE_ACTIVE.value:
            raise StudyWorkflowError(
                "Questionnaire submission is not available at this stage.",
                409,
                "questionnaire_not_active",
            )
        if study_session.revision != expected_revision:
            raise StudyWorkflowError(
                "Study workflow revision is stale.", 409, "stale_revision"
            )
        if not _frozen_game_estimate_exists(db, study_session.id) and not (enabled(study_session) and db.query(__import__("study.models",fromlist=["StudyWorkflowTransition"]).StudyWorkflowTransition).filter_by(study_session_id=study_session.id,from_state=StudyWorkflowState.GAME_ESTIMATE_FAILED.value,to_state=StudyWorkflowState.QUESTIONNAIRE_ACTIVE.value).first()):
            raise StudyWorkflowError(
                "The island estimate boundary is missing.",
                409,
                "game_estimate_not_frozen",
            )
        scored = score_bfi2(answers) if len(answers)==60 else None
        report_text = render_neutral_report(scored) if scored else None
        now = utc_now()
        response = StudyQuestionnaireResponse(
            study_session_id=study_session.id,
            instrument_id=INSTRUMENT_ID,
            instrument_version=INSTRUMENT_VERSION,
            instrument_sha256=INSTRUMENT_SHA256,
            language=INSTRUMENT_LANGUAGE,
            answers_json=_canonical(answers),
            answers_sha256=answers_sha256,
            submit_idempotency_key=idempotency_key,
            submitted_at=now,
            frozen_at=now,
        )
        db.add(response)
        db.flush()
        score = None
        if scored is not None:
            score_material = {
                "instrument_sha256": INSTRUMENT_SHA256,
                "scoring_version": SCORING_VERSION,
                "transformed_item_scores": scored.transformed_item_scores,
                "domain_scores": scored.domain_scores,
                "facet_scores": scored.facet_scores,
                "report_template_version": REPORT_TEMPLATE_VERSION,
                "report_text": report_text,
            }
            score = StudyQuestionnaireScore(
                study_session_id=study_session.id,
                questionnaire_response_id=response.id,
                scoring_version=SCORING_VERSION,
                transformed_item_scores_json=_canonical(scored.transformed_item_scores),
                domain_scores_json=_canonical(scored.domain_scores),
                facet_scores_json=_canonical(scored.facet_scores),
                report_template_version=REPORT_TEMPLATE_VERSION,
                report_text=report_text,
                result_sha256=_sha(score_material),
                frozen_at=now,
            )
            db.add(score)
        draft = db.query(StudyQuestionnaireDraft).filter_by(study_session_id=study_session.id).one_or_none()
        if draft is not None:
            db.delete(draft)
        study_session.compensation_stage = "questionnaire_completed"
        db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.QUESTIONNAIRE_COMPLETED,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="bfi2_questionnaire_frozen",
            related_record_type="questionnaire_response",
            related_record_id=str(response.id),
        )
        db.refresh(response)
        if score is not None: db.refresh(score)
        from study.holiday_flow import prepare_results
        next_session = prepare_results(db, result.study_session)
        return QuestionnaireResult(next_session, response, score, result.replayed)


def questionnaire_status(db: DBSession, study_session: StudySession) -> dict[str, Any]:
    response = db.query(StudyQuestionnaireResponse).filter_by(study_session_id=study_session.id).one_or_none()
    score = db.query(StudyQuestionnaireScore).filter_by(study_session_id=study_session.id).one_or_none()
    draft = db.query(StudyQuestionnaireDraft).filter_by(study_session_id=study_session.id).one_or_none()
    return {
        "state": study_session.state,
        "revision": study_session.revision,
        "instrument_id": INSTRUMENT_ID,
        "instrument_version": INSTRUMENT_VERSION,
        "instrument_sha256": INSTRUMENT_SHA256,
        "draft_answer_count": len(json.loads(draft.answers_json)) if draft else 0,
        "submitted": response is not None,
        "answered_count": len(json.loads(response.answers_json)) if response else None,
        "skipped_items": [n for n in range(1,61) if str(n) not in json.loads(response.answers_json)] if response and enabled(study_session) else [],
        "response_status": ("complete" if score else "partial") if response else "not_submitted",
        "scored": score is not None,
        "scoring_version": score.scoring_version if score else None,
        "result_sha256": score.result_sha256 if score else None,
        "frozen_at": score.frozen_at.isoformat() if score else None,
    }

