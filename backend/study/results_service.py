from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import secrets
import threading
from typing import Any, Iterable

from sqlalchemy.orm import Session as DBSession

from study.bfi2_instrument import DOMAIN_LABELS_ZH
from study.contracts import StudyWorkflowState
from study.experience_instruments import (
    POST_RESULT_INSTRUMENT_SHA256,
    POST_RESULT_INSTRUMENT_VERSION,
    PRE_RESULT_FORMATS,
    PRE_RESULT_INSTRUMENT_ID,
    PRE_RESULT_INSTRUMENT_SHA256,
    PRE_RESULT_INSTRUMENT_VERSION,
    post_result_instrument_payload,
    pre_result_instrument_payload,
)
from study.models import (
    StudyFormatExperienceResponse,
    StudyGameEstimate,
    StudyQuestionnaireScore,
    StudyResultEvaluation,
    StudyResultPresentation,
    StudySession,
)
from study.service import StudyWorkflowError, transition_study_session, utc_now


GAME_ESTIMATE_KIND = "game_estimate"
QUESTIONNAIRE_KIND = "questionnaire"
ALLOWED_REPORT_KINDS = frozenset({GAME_ESTIMATE_KIND, QUESTIONNAIRE_KIND})

_RESULT_LOCKS: dict[int, threading.Lock] = {}
_RESULT_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class ResultFlowResponse:
    study_session: StudySession
    replayed: bool
    report: dict[str, Any] | None = None


def _lock(study_session_id: int) -> threading.Lock:
    with _RESULT_LOCKS_GUARD:
        return _RESULT_LOCKS.setdefault(study_session_id, threading.Lock())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_optional_rating(value: int | None, skipped: bool) -> None:
    if skipped == (value is not None):
        raise StudyWorkflowError(
            "Each optional item must be answered or explicitly skipped, but not both.",
            422,
            "optional_rating_invalid",
        )


def _format_ratings(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    allowed_formats = {format_id for format_id, _label in PRE_RESULT_FORMATS}
    for row in rows:
        format_id = str(row.format_id)
        item_number = int(row.item_number)
        value = int(row.value) if row.value is not None else None
        skipped = bool(row.skipped)
        key = (format_id, item_number)
        if key in seen:
            raise StudyWorkflowError(
                "Each format-experience item may appear only once.",
                422,
                "format_feedback_duplicate_item",
            )
        seen.add(key)
        _validate_optional_rating(value, skipped)
        normalized.append(
            {
                "format_id": format_id,
                "item_number": item_number,
                "value": value,
                "skipped": skipped,
            }
        )
    expected = {
        (format_id, item_number)
        for format_id in allowed_formats
        for item_number in range(1, 7)
    }
    if seen != expected:
        raise StudyWorkflowError(
            "All twelve format-experience items must be answered or explicitly skipped.",
            422,
            "format_feedback_incomplete",
        )
    return sorted(normalized, key=lambda item: (item["format_id"], item["item_number"]))


def _result_ratings(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        item_number = int(row.item_number)
        value = int(row.value) if row.value is not None else None
        skipped = bool(row.skipped)
        if item_number in seen:
            raise StudyWorkflowError(
                "Each result-evaluation item may appear only once.",
                422,
                "result_evaluation_duplicate_item",
            )
        seen.add(item_number)
        _validate_optional_rating(value, skipped)
        normalized.append(
            {"item_number": item_number, "value": value, "skipped": skipped}
        )
    if seen != set(range(1, 5)):
        raise StudyWorkflowError(
            "All four result-evaluation items must be answered or explicitly skipped.",
            422,
            "result_evaluation_incomplete",
        )
    return sorted(normalized, key=lambda item: item["item_number"])


def _frozen_results(
    db: DBSession, study_session_id: int
) -> tuple[StudyGameEstimate, StudyQuestionnaireScore]:
    game = (
        db.query(StudyGameEstimate)
        .filter_by(study_session_id=study_session_id, analysis_version=1)
        .one_or_none()
    )
    questionnaire = (
        db.query(StudyQuestionnaireScore)
        .filter_by(study_session_id=study_session_id)
        .one_or_none()
    )
    if game is None or questionnaire is None:
        raise StudyWorkflowError(
            "Both frozen results are required before experience feedback.",
            409,
            "results_not_frozen",
        )
    return game, questionnaire


def begin_format_feedback(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> ResultFlowResponse:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        if study_session.state == StudyWorkflowState.PRE_RESULT_FEEDBACK.value:
            return ResultFlowResponse(study_session, True)
        if study_session.state != StudyWorkflowState.QUESTIONNAIRE_COMPLETED.value:
            raise StudyWorkflowError(
                "Pre-result experience feedback is unavailable at this stage.",
                409,
                "format_feedback_not_available",
            )
        from study.protocol_v2 import enabled
        if enabled(study_session): raise StudyWorkflowError("Removed questionnaire.",410,"instrument_removed")
        _frozen_results(db, study_session.id)
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.PRE_RESULT_FEEDBACK,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="pre_result_feedback_started",
            related_record_type="instrument",
            related_record_id=PRE_RESULT_INSTRUMENT_VERSION,
        )
        return ResultFlowResponse(result.study_session, result.replayed)


def format_feedback_payload(study_session: StudySession) -> dict[str, Any]:
    if study_session.state != StudyWorkflowState.PRE_RESULT_FEEDBACK.value:
        raise StudyWorkflowError(
            "Pre-result feedback content is available only during its active stage.",
            409,
            "format_feedback_not_active",
        )
    from study.protocol_v2 import enabled
    if enabled(study_session): raise StudyWorkflowError("Removed questionnaire.",410,"instrument_removed")
    return pre_result_instrument_payload()


def submit_format_feedback(
    db: DBSession,
    *,
    study_session: StudySession,
    rating_rows: Iterable[Any],
    expected_revision: int,
    idempotency_key: str,
) -> ResultFlowResponse:
    ratings = _format_ratings(rating_rows)
    ratings_sha256 = _sha(
        {"instrument_sha256": PRE_RESULT_INSTRUMENT_SHA256, "ratings": ratings}
    )
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        existing = (
            db.query(StudyFormatExperienceResponse)
            .filter_by(study_session_id=study_session.id)
            .one_or_none()
        )
        if existing is not None:
            if existing.ratings_sha256 != ratings_sha256:
                raise StudyWorkflowError(
                    "The pre-result feedback is frozen and cannot be changed.",
                    409,
                    "format_feedback_frozen",
                )
            return ResultFlowResponse(study_session, True)
        if study_session.state != StudyWorkflowState.PRE_RESULT_FEEDBACK.value:
            raise StudyWorkflowError(
                "Pre-result experience feedback is not active.",
                409,
                "format_feedback_not_active",
            )
        if study_session.revision != expected_revision:
            raise StudyWorkflowError("Study workflow revision is stale.", 409, "stale_revision")
        game, questionnaire = _frozen_results(db, study_session.id)
        now = utc_now()
        response = StudyFormatExperienceResponse(
            study_session_id=study_session.id,
            instrument_id=PRE_RESULT_INSTRUMENT_ID,
            instrument_version=PRE_RESULT_INSTRUMENT_VERSION,
            instrument_sha256=PRE_RESULT_INSTRUMENT_SHA256,
            language="zh-CN",
            ratings_json=_canonical(ratings),
            ratings_sha256=ratings_sha256,
            submit_idempotency_key=idempotency_key,
            submitted_at=now,
            frozen_at=now,
        )
        db.add(response)
        first, second = (
            (GAME_ESTIMATE_KIND, QUESTIONNAIRE_KIND)
            if secrets.randbits(1) == 0
            else (QUESTIONNAIRE_KIND, GAME_ESTIMATE_KIND)
        )
        order_material = {
            "result_one_kind": first,
            "result_two_kind": second,
            "game_output_sha256": game.output_sha256,
            "questionnaire_result_sha256": questionnaire.result_sha256,
        }
        presentation = StudyResultPresentation(
            study_session_id=study_session.id,
            game_estimate_id=game.id,
            questionnaire_score_id=questionnaire.id,
            result_one_kind=first,
            result_two_kind=second,
            game_output_sha256=game.output_sha256,
            questionnaire_result_sha256=questionnaire.result_sha256,
            order_sha256=_sha(order_material),
            generated_at=now,
        )
        db.add(presentation)
        db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.RESULTS_READY,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="pre_result_feedback_frozen_and_order_generated",
            related_record_type="result_presentation",
            related_record_id=str(presentation.id),
        )
        return ResultFlowResponse(result.study_session, result.replayed)


def _presentation(db: DBSession, study_session_id: int) -> StudyResultPresentation:
    presentation = (
        db.query(StudyResultPresentation)
        .filter_by(study_session_id=study_session_id)
        .one_or_none()
    )
    if presentation is None:
        raise StudyWorkflowError(
            "The frozen result order is missing.", 409, "result_order_missing"
        )
    if {presentation.result_one_kind, presentation.result_two_kind} != ALLOWED_REPORT_KINDS:
        raise StudyWorkflowError(
            "The stored result order is invalid.", 500, "invalid_result_order"
        )
    return presentation


def results_status(db: DBSession, study_session: StudySession) -> dict[str, Any]:
    presentation = (
        db.query(StudyResultPresentation)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    evaluations = (
        db.query(StudyResultEvaluation)
        .filter_by(study_session_id=study_session.id)
        .all()
    )
    active_position = None
    active_kind = None
    if study_session.state == StudyWorkflowState.RESULT_ONE_ACTIVE.value:
        active_position = 1
    elif study_session.state == StudyWorkflowState.RESULT_TWO_ACTIVE.value:
        active_position = 2
    if active_position is not None and presentation is not None:
        active_kind = (
            presentation.result_one_kind
            if active_position == 1
            else presentation.result_two_kind
        )
    return {
        "state": study_session.state,
        "revision": study_session.revision,
        "order_generated": presentation is not None,
        "order_sha256": presentation.order_sha256 if presentation else None,
        "active_position": active_position,
        "active_report_kind": active_kind,
        "submitted_evaluation_count": sum(
            evaluation.submitted_at is not None for evaluation in evaluations
        ),
        "report_body_exposed": False,
    }


def _game_report_payload(game: StudyGameEstimate) -> dict[str, Any]:
    stored = json.loads(game.result_json)
    if stored.get('method_version') == 'production-island-letter-v2':
        letter=stored['island_letter']
        return {'report_kind':GAME_ESTIMATE_KIND, 'title':letter['report']['title'],
            'source':'岛屿回信 · 根据你这次游玩留下的记录整理', 'summary':game.report_text,
            'letter_paragraphs':letter['paragraphs'], **({'recap':letter['recap']} if 'recap' in letter else {}), 'dimensions':[], 'evidence':[], 'facets':[],
            'scale_note':'不提供人格分数。', 'uncertainty_note':stored['uncertainty_note'],
            'limitations':stored['limitations'], 'fixture_only':False, 'watermark':None,
            'integrity_sha256':game.output_sha256}
    dimensions = []
    for domain in stored.get("domains", []):
        dimensions.append(
            {
                "domain_id": domain["domain_id"],
                "label": DOMAIN_LABELS_ZH.get(domain["domain_id"], domain["domain_id"]),
                "status": domain["status"],
                "value": domain.get("value"),
                "maximum": 5 if domain.get("value") is not None else None,
                "description": domain["description"],
            }
        )
    observation = stored.get("method_version", "").startswith(("holiday-observation", "production-observation"))
    return {
        "evidence": stored.get("evidence", []),
        "facets": stored.get("facets", []) if observation else [],
        "report_kind": GAME_ESTIMATE_KIND,
        "title": "岛屿旅程观察报告" if observation else "岛屿互动研究估计",
        "source": "来源：本次旅程的实际记录及按有限规则整理的明确表达；不推断稳定人格。" if observation else "来源：七个游戏日中经预定义规则编码的互动、选择与语言特征。",
        "summary": game.report_text,
        "dimensions": dimensions,
        "scale_note": (
            "正式获批版本将以连续维度呈现；当前测试夹具未进行人格估计。"
            if game.fixture_only
            else "五维与十五分面均不打分，证据不足处保留说明。" if observation else "维度采用连续方式呈现，不表示好坏。"
        ),
        "uncertainty_note": stored.get("uncertainty_note", ""),
        "limitations": list(stored.get("limitations", [])),
        "fixture_only": game.fixture_only,
        "watermark": stored.get("watermark"),
        "integrity_sha256": game.output_sha256,
    }


def _questionnaire_report_payload(score: StudyQuestionnaireScore) -> dict[str, Any]:
    domain_scores = json.loads(score.domain_scores_json)
    return {
        "report_kind": QUESTIONNAIRE_KIND,
        "title": "标准化问卷结果",
        "source": "来源：中文版 BFI-2 的60项自我报告回答，使用冻结的固定计分规则。",
        "summary": score.report_text,
        "dimensions": [
            {
                "domain_id": domain_id,
                "label": label,
                "status": "continuous_score",
                "value": domain_scores[domain_id],
                "maximum": 5,
                "description": "本次问卷在该连续维度上的固定规则得分。",
            }
            for domain_id, label in DOMAIN_LABELS_ZH.items()
        ],
        "scale_note": "分数范围为1.00–5.00；不使用人群常模、百分位或临床阈值。",
        "uncertainty_note": "自我报告结果会受到当时理解、作答方式和情境影响。",
        "limitations": [
            "这些连续分数不代表好坏，也不是诊断结论。",
            "结果不应用于医疗、学业、就业、纪律、资格或其他重要决定。",
        ],
        "fixture_only": False,
        "watermark": None,
        "integrity_sha256": score.result_sha256,
    }


def report_payload_for_kind(
    db: DBSession, presentation: StudyResultPresentation, report_kind: str
) -> dict[str, Any]:
    if report_kind == GAME_ESTIMATE_KIND:
        game = db.query(StudyGameEstimate).filter_by(id=presentation.game_estimate_id).one()
        if game.output_sha256 != presentation.game_output_sha256:
            raise StudyWorkflowError(
                "The frozen game result hash no longer matches its presentation.",
                409,
                "result_hash_mismatch",
            )
        return _game_report_payload(game)
    if report_kind == QUESTIONNAIRE_KIND:
        score = (
            db.query(StudyQuestionnaireScore)
            .filter_by(id=presentation.questionnaire_score_id)
            .one()
        )
        if score.result_sha256 != presentation.questionnaire_result_sha256:
            raise StudyWorkflowError(
                "The frozen questionnaire result hash no longer matches its presentation.",
                409,
                "result_hash_mismatch",
            )
        return _questionnaire_report_payload(score)
    raise StudyWorkflowError("Unknown report kind.", 500, "invalid_result_kind")


def reveal_result(
    db: DBSession,
    *,
    study_session: StudySession,
    position: int,
    expected_revision: int,
    idempotency_key: str,
) -> ResultFlowResponse:
    if position not in {1, 2}:
        raise StudyWorkflowError("Result position must be one or two.", 422, "invalid_result_position")
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        presentation = _presentation(db, study_session.id)
        active_state = (
            StudyWorkflowState.RESULT_ONE_ACTIVE
            if position == 1
            else StudyWorkflowState.RESULT_TWO_ACTIVE
        )
        required_state = (
            StudyWorkflowState.RESULTS_READY
            if position == 1
            else StudyWorkflowState.RESULT_ONE_RATED
        )
        report_kind = (
            presentation.result_one_kind
            if position == 1
            else presentation.result_two_kind
        )
        if study_session.state == active_state.value:
            return ResultFlowResponse(
                study_session, True, report_payload_for_kind(db, presentation, report_kind)
            )
        if study_session.state != required_state.value:
            raise StudyWorkflowError(
                "This result cannot be viewed at the current stage.",
                409,
                "result_not_available",
            )
        evaluation = (
            db.query(StudyResultEvaluation)
            .filter_by(study_session_id=study_session.id, presentation_position=position)
            .one_or_none()
        )
        if evaluation is None:
            evaluation = StudyResultEvaluation(
                study_session_id=study_session.id,
                presentation_id=presentation.id,
                report_kind=report_kind,
                presentation_position=position,
                instrument_version=POST_RESULT_INSTRUMENT_VERSION,
                instrument_sha256=POST_RESULT_INSTRUMENT_SHA256,
                first_viewed_at=utc_now(),
            )
            db.add(evaluation)
            db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=active_state,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code=f"result_{position}_first_viewed",
            related_record_type="result_evaluation",
            related_record_id=str(evaluation.id),
        )
        return ResultFlowResponse(
            result.study_session,
            result.replayed,
            report_payload_for_kind(db, presentation, report_kind),
        )


def current_result_payload(db: DBSession, study_session: StudySession) -> dict[str, Any]:
    if study_session.state == StudyWorkflowState.RESULT_ONE_ACTIVE.value:
        position = 1
    elif study_session.state == StudyWorkflowState.RESULT_TWO_ACTIVE.value:
        position = 2
    else:
        raise StudyWorkflowError(
            "No report is currently authorized for display.",
            409,
            "result_not_active",
        )
    presentation = _presentation(db, study_session.id)
    report_kind = (
        presentation.result_one_kind if position == 1 else presentation.result_two_kind
    )
    return {
        "position": position,
        "total": 2,
        "evaluation_instrument": post_result_instrument_payload(),
        "report": report_payload_for_kind(db, presentation, report_kind),
    }


def submit_result_evaluation(
    db: DBSession,
    *,
    study_session: StudySession,
    rating_rows: Iterable[Any],
    expected_revision: int,
    idempotency_key: str,
) -> ResultFlowResponse:
    ratings = _result_ratings(rating_rows)
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        if study_session.state in {
            StudyWorkflowState.RESULT_ONE_ACTIVE.value,
            StudyWorkflowState.RESULT_ONE_RATED.value,
        }:
            position = 1
        elif study_session.state in {
            StudyWorkflowState.RESULT_TWO_ACTIVE.value,
            StudyWorkflowState.RESULT_TWO_RATED.value,
        }:
            position = 2
        else:
            raise StudyWorkflowError(
                "A result evaluation is not active.", 409, "result_evaluation_not_active"
            )
        presentation = _presentation(db, study_session.id)
        report_kind = (
            presentation.result_one_kind if position == 1 else presentation.result_two_kind
        )
        ratings_sha256 = _sha(
            {
                "instrument_sha256": POST_RESULT_INSTRUMENT_SHA256,
                "report_kind": report_kind,
                "presentation_position": position,
                "ratings": ratings,
            }
        )
        evaluation = (
            db.query(StudyResultEvaluation)
            .filter_by(study_session_id=study_session.id, presentation_position=position)
            .one_or_none()
        )
        if evaluation is None:
            raise StudyWorkflowError(
                "The result has not been displayed.", 409, "result_not_viewed"
            )
        if evaluation.submitted_at is not None:
            if evaluation.ratings_sha256 != ratings_sha256:
                raise StudyWorkflowError(
                    "This result evaluation is frozen and cannot be changed.",
                    409,
                    "result_evaluation_frozen",
                )
            return ResultFlowResponse(study_session, True)
        expected_active = (
            StudyWorkflowState.RESULT_ONE_ACTIVE.value
            if position == 1
            else StudyWorkflowState.RESULT_TWO_ACTIVE.value
        )
        if study_session.state != expected_active:
            raise StudyWorkflowError(
                "This result evaluation is no longer active.",
                409,
                "result_evaluation_not_active",
            )
        if evaluation.report_kind != report_kind:
            raise StudyWorkflowError(
                "The evaluation is bound to the wrong report.",
                500,
                "result_evaluation_binding_error",
            )
        evaluation.ratings_json = _canonical(ratings)
        evaluation.ratings_sha256 = ratings_sha256
        evaluation.submit_idempotency_key = idempotency_key
        evaluation.submitted_at = utc_now()
        target = (
            StudyWorkflowState.RESULT_ONE_RATED
            if position == 1
            else StudyWorkflowState.RESULT_TWO_RATED
        )
        if position == 2:
            study_session.compensation_stage = "results_evaluated"
        db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=target,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code=f"result_{position}_evaluation_frozen",
            related_record_type="result_evaluation",
            related_record_id=str(evaluation.id),
        )
        return ResultFlowResponse(result.study_session, result.replayed)


# Versioned adapters: old sessions never acquire V2 report availability implicitly.
_legacy_status=results_status
_legacy_current=current_result_payload
_legacy_reveal=reveal_result
_legacy_submit=submit_result_evaluation
def results_status(db,study_session):
    from study.protocol_v2 import enabled
    from study.available_results import status
    return status(db,study_session) if enabled(study_session) else _legacy_status(db,study_session)
def current_result_payload(db,study_session):
    from study.protocol_v2 import enabled
    from study.available_results import current
    return current(db,study_session) if enabled(study_session) else _legacy_current(db,study_session)
def reveal_result(db,*,study_session,position,expected_revision,idempotency_key):
    from study.protocol_v2 import enabled
    from study.available_results import reveal
    if enabled(study_session): return reveal(db,study_session,position,expected_revision,idempotency_key)
    return _legacy_reveal(db,study_session=study_session,position=position,expected_revision=expected_revision,idempotency_key=idempotency_key)
def submit_result_evaluation(db,*,study_session,rating_rows,expected_revision,idempotency_key):
    from study.protocol_v2 import enabled
    from study.available_results import submit
    if enabled(study_session): return submit(db,study_session,rating_rows,expected_revision,idempotency_key)
    return _legacy_submit(db,study_session=study_session,rating_rows=rating_rows,expected_revision=expected_revision,idempotency_key=idempotency_key)
