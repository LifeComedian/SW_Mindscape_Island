from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import os
import re
import threading
import secrets
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import update, or_

from models import WorldAction
from study.assessment_interfaces import FixtureGameAssessmentProvider, FixtureReportRenderer
from study.assessment_packages import (
    FIXTURE_PACKAGE,
    SYSTEM_CONTRACT_VERSION,
    AssessmentPackageDefinition,
    canonical_json,
    fixture_integrity_verified,
    fixture_package_for,
    versions_match_fixture,
)
from study.contracts import AssessmentMode, RuntimeEnvironment, StudyWorkflowState
from study.models import (
    StudyAssessmentAttempt,
    StudyAssessmentJob,
    StudyAssessmentLease,
    StudyFeatureSnapshot,
    StudyGameEstimate,
    StudySession,
    StudyWorldBoundary,
)
from study.service import StudyWorkflowError, transition_study_session, utc_now
from world.registry import get_world_spec


FIXTURE_WATERMARK = "TEST FIXTURE — NOT A PARTICIPANT RESULT"
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
_JOB_LOCKS: dict[int, threading.Lock] = {}
_JOB_LOCKS_GUARD = threading.Lock()


class ProviderTimeoutError(TimeoutError):
    pass


class ProviderUnavailableError(RuntimeError):
    pass


class StudyAssessmentValidationError(ValueError):
    pass


class DomainObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str = Field(min_length=2, max_length=40)
    status: str = Field(pattern=r"^(not_estimated|observed_range)$")
    description: str = Field(min_length=1, max_length=240)
    basis: list[str] = Field(default_factory=list, max_length=12)
    value: float | None = Field(default=None, ge=1, le=5)


class GameEstimateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^game-estimate-result-v1$")
    result_kind: str = Field(
        pattern=r"^(fixture_pipeline_check|data_insufficient|observational_estimate)$"
    )
    fixture_only: bool
    watermark: str = Field(min_length=8, max_length=120)
    domains: list[DomainObservation] = Field(max_length=5)
    data_sufficiency: str = Field(pattern=r"^(sufficient|insufficient)$")
    uncertainty_note: str = Field(min_length=1, max_length=400)
    limitations: list[str] = Field(min_length=1, max_length=8)
    gentle_summary: str = Field(min_length=1, max_length=500)
    method_version: str | None = None
    facets: list[dict[str, Any]] | None = None
    provider_metrics: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    observation_sections: list[dict[str, Any]] | None = None
    coverage: dict[str, Any] | None = None
    island_letter: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AssessmentLifecycleResult:
    study_session: StudySession
    job: StudyAssessmentJob
    estimate: StudyGameEstimate | None
    replayed: bool


def _job_lock(study_session_id: int) -> threading.Lock:
    with _JOB_LOCKS_GUARD:
        return _JOB_LOCKS.setdefault(study_session_id, threading.Lock())


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _runtime_environment() -> RuntimeEnvironment:
    raw = os.getenv("STUDY_RUNTIME_ENV", "").strip().lower()
    try:
        return RuntimeEnvironment(raw)
    except ValueError as exc:
        raise StudyWorkflowError(
            "Study runtime environment must be explicitly configured.",
            409,
            "assessment_environment_invalid",
        ) from exc


def _assessment_mode() -> AssessmentMode:
    raw = os.getenv("STUDY_ASSESSMENT_MODE", "disabled").strip().lower()
    try:
        return AssessmentMode(raw)
    except ValueError as exc:
        raise StudyWorkflowError(
            "Assessment mode is invalid.", 409, "assessment_mode_invalid"
        ) from exc


def _actual_versions(boundary: StudyWorldBoundary) -> dict[str, str]:
    spec = get_world_spec(boundary.world_version)
    return {
        "world_version": boundary.world_version,
        "scenario_pack_version": boundary.scenario_pack_version,
        "content_pack_version": spec.content_pack_version or "not_versioned",
        "event_pack_version": spec.event_pack_version or "not_versioned",
        "system_contract_version": SYSTEM_CONTRACT_VERSION,
    }


def _resolve_package(boundary: StudyWorldBoundary, snapshot=None) -> tuple[AssessmentMode, AssessmentPackageDefinition]:
    mode = _assessment_mode()
    environment = _runtime_environment()
    if mode is AssessmentMode.OBSERVATION:
        from study.production_observation import package
        from study.production_letter import FACT_KEY
        if snapshot is not None and FACT_KEY in json.loads(snapshot.features_json):
            from study.production_letter import package
        return mode, package(boundary)
    if mode is AssessmentMode.EXPERIMENTAL:
        if environment is RuntimeEnvironment.PRODUCTION or boundary.world_version not in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            raise StudyWorkflowError('Experimental assessment requires a local v5 world.',409,'experimental_assessment_forbidden')
        from study.holiday_assessment_v5 import package, SCHEMA, OBSERVATION_SCHEMA
        if boundary.feature_schema_version not in (SCHEMA, OBSERVATION_SCHEMA):
            raise StudyWorkflowError('Actual coded snapshot is missing.',409,'coded_snapshot_missing')
        return mode, package(boundary)
    if mode is AssessmentMode.DISABLED:
        raise StudyWorkflowError(
            "Island assessment is disabled.", 409, "assessment_disabled"
        )
    if mode is AssessmentMode.FIXTURE:
        fixtures_enabled = os.getenv("STUDY_TEST_FIXTURES_ENABLED", "").lower() == "true"
        if environment is RuntimeEnvironment.PRODUCTION or not fixtures_enabled:
            raise StudyWorkflowError(
                "Fixture assessment is unavailable in this environment.",
                409,
                "fixture_assessment_forbidden",
            )
        package = fixture_package_for(boundary.world_version)
        if not fixture_integrity_verified(package):
            raise StudyWorkflowError(
                "Assessment package integrity verification failed.",
                409,
                "assessment_package_hash_mismatch",
            )
        if not versions_match_fixture(_actual_versions(boundary), package):
            raise StudyWorkflowError(
                "Assessment package is incompatible with the frozen world.",
                409,
                "assessment_package_incompatible",
            )
        if (
            boundary.observation_schema_version
            != package.manifest.observation_schema_version
            or boundary.feature_schema_version
            != package.manifest.feature_schema_version
        ):
            raise StudyWorkflowError(
                "Assessment schemas are incompatible with the frozen snapshot.",
                409,
                "assessment_package_incompatible",
            )
        return mode, package
    # No approved package ships with M6. Never fall back to fixture or defaults.
    raise StudyWorkflowError(
        "No approved assessment package is installed.",
        409,
        "approved_assessment_package_unavailable",
    )


def _job_for(db: DBSession, study_session_id: int) -> StudyAssessmentJob | None:
    return (
        db.query(StudyAssessmentJob)
        .filter_by(study_session_id=study_session_id, analysis_version=1)
        .one_or_none()
    )


def begin_game_estimate(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> AssessmentLifecycleResult:
    with _job_lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        boundary = db.query(StudyWorldBoundary).filter_by(study_session_id=study_session.id).one_or_none()
        if boundary is None or boundary.integrity_status != "frozen" or boundary.frozen_at is None:
            raise StudyWorkflowError(
                "The island observation boundary is not frozen.", 409, "island_not_frozen"
            )
        existing = _job_for(db, study_session.id)
        if existing is not None and study_session.state not in {
            StudyWorkflowState.GAME_ESTIMATE_FAILED.value,
            StudyWorkflowState.ISLAND_COMPLETED.value,
        }:
            estimate = db.query(StudyGameEstimate).filter_by(assessment_job_id=existing.id).one_or_none()
            return AssessmentLifecycleResult(study_session, existing, estimate, True)
        snapshot = db.query(StudyFeatureSnapshot).filter_by(study_session_id=study_session.id).one()
        mode, package = _resolve_package(boundary, snapshot)
        if existing is None:
            if study_session.state != StudyWorkflowState.ISLAND_COMPLETED.value:
                raise StudyWorkflowError(
                    "The island estimate cannot begin from this stage.", 409, "invalid_transition"
                )
            job = StudyAssessmentJob(
                study_session_id=study_session.id,
                analysis_version=1,
                mode=mode.value,
                status="processing",
                package_id=package.manifest.package_id,
                package_version=package.manifest.package_version,
                package_sha256=package.manifest.integrity_sha256,
                attempt_count=0,
                begin_idempotency_key=idempotency_key,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(job)
            db.flush()
            db.add(StudyAssessmentLease(assessment_job_id=job.id))
            reason = "fixture_game_estimate_started" if package.fixture_only else "observation_report_started"
        else:
            if study_session.state == StudyWorkflowState.ISLAND_COMPLETED.value:
                if existing.begin_idempotency_key != idempotency_key:
                    raise StudyWorkflowError(
                        "An assessment job already exists for this Session.",
                        409,
                        "assessment_job_exists",
                    )
                return AssessmentLifecycleResult(study_session, existing, None, True)
            job = existing
            if (
                job.package_id != package.manifest.package_id
                or job.package_version != package.manifest.package_version
                or job.package_sha256 != package.manifest.integrity_sha256
            ):
                raise StudyWorkflowError(
                    "The assessment package changed between attempts.",
                    409,
                    "assessment_package_drift",
                )
            job.status = "processing"
            job.last_error_code = None
            job.updated_at = utc_now()
            reason = "fixture_game_estimate_retry_started" if package.fixture_only else "observation_report_retry_started"
        transition = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.GAME_ESTIMATE_PROCESSING,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="system",
            reason_code=reason,
            related_record_type="assessment_job",
            related_record_id=str(job.id),
        )
        db.refresh(job)
        return AssessmentLifecycleResult(transition.study_session, job, None, transition.replayed)


def _safe_count_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, int] = {}
    for key, count in value.items():
        if (
            isinstance(key, str)
            and _IDENTIFIER.fullmatch(key)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
        ):
            safe[key] = count
    return dict(sorted(safe.items()))


def _build_request(
    snapshot: StudyFeatureSnapshot,
    boundary: StudyWorldBoundary,
    package: AssessmentPackageDefinition,
) -> dict[str, Any]:
    try:
        stored_features = json.loads(snapshot.features_json)
        stored_opportunities = json.loads(snapshot.opportunity_denominators_json)
        stored_missing = json.loads(snapshot.missing_reasons_json)
    except (TypeError, ValueError) as exc:
        raise StudyWorkflowError(
            "Frozen feature snapshot is unreadable.", 409, "feature_snapshot_invalid"
        ) from exc
    selected_count = stored_features.get("selected_option_count", 0)
    if not isinstance(selected_count, int) or isinstance(selected_count, bool) or selected_count < 0:
        selected_count = 0
    missing = {
        key: value
        for key, value in stored_missing.items()
        if key in {"observations", "choice_opportunities"}
        and value in {"no_observations_recorded", "no_option_sets_observed"}
    } if isinstance(stored_missing, dict) else {}
    request = {
        "schema_version": package.request_schema_version,
        "assessment_package": {
            "package_id": package.manifest.package_id,
            "package_version": package.manifest.package_version,
            "package_sha256": package.manifest.integrity_sha256,
        },
        "versions": {
            **_actual_versions(boundary),
            "observation_schema_version": boundary.observation_schema_version,
            "feature_schema_version": snapshot.feature_schema_version,
            "extractor_version": snapshot.extractor_version,
        },
        "encoded_features": {
            "language_features": {},
            "behavior_choice_summary": {
                "action_counts": _safe_count_map(stored_features.get("action_counts", {})),
                "selected_option_count": selected_count,
            },
            "opportunity_exposure": _safe_count_map(stored_opportunities),
            "temporal_context": {
                "observation_count": snapshot.observation_count,
                "final_world_day": boundary.final_world_day,
                "final_world_time_minutes": boundary.final_world_time_minutes,
            },
            "data_sufficiency": {"sufficient": snapshot.sufficient},
            "missing_reasons": missing,
        },
    }
    if boundary.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and not package.fixture_only:
        from study.holiday_assessment_v5 import packet
        coded = packet(stored_features.get('coded_events', []))
        request['encoded_features']['language_features'] = {'coded_events': coded['coded_events']}
        request['encoded_features']['behavior_choice_summary'] = {'sources': stored_features.get('sources', {})}
        if package.manifest.package_id in ('holiday-observation-only-v1','production-observation-v1'):
            request['encoded_features']['behavior_choice_summary']['observation_only'] = True
        if package.manifest.package_id == 'production-island-letter-v2':
            from study.production_letter import FACT_KEY
            request['encoded_features']['behavior_choice_summary'] = {FACT_KEY: stored_features[FACT_KEY]}
            request['encoded_features']['language_features'] = {}
    if tuple(request["encoded_features"].keys()) != package.feature_allowlist:
        raise StudyWorkflowError(
            "Feature allowlist does not match the package.", 409, "feature_allowlist_mismatch"
        )
    return request


def _all_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


_PROHIBITED_OUTPUT_LANGUAGE = (
    "diagnos",
    "medical advice",
    "treatment",
    "you are definitely",
    "you certainly are",
    "诊断",
    "患有",
    "治疗建议",
    "你一定是",
    "你就是一个",
)


def validate_provider_output(
    raw: Any,
    *,
    package: AssessmentPackageDefinition,
    raw_participant_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise StudyAssessmentValidationError("Provider output must be a JSON object.")
    try:
        parsed = GameEstimateOutput.model_validate(dict(raw))
    except ValidationError as exc:
        raise StudyAssessmentValidationError("Provider output schema is invalid.") from exc
    payload = parsed.model_dump(mode="json", exclude_none=True)
    domain_ids = [item["domain_id"] for item in payload["domains"]]
    if len(set(domain_ids)) != len(domain_ids):
        raise StudyAssessmentValidationError("Provider output repeats a domain.")
    if not set(domain_ids).issubset(package.manifest.enabled_domain_ids):
        raise StudyAssessmentValidationError("Provider output contains an unknown domain.")
    if package.fixture_only:
        if not payload["fixture_only"] or payload["watermark"] != FIXTURE_WATERMARK:
            raise StudyAssessmentValidationError("Fixture output is missing its test watermark.")
        if payload["result_kind"] not in {"fixture_pipeline_check", "data_insufficient"}:
            raise StudyAssessmentValidationError("Fixture output cannot impersonate a real estimate.")
        if any(item["status"] != "not_estimated" for item in payload["domains"]):
            raise StudyAssessmentValidationError("Fixture output cannot contain trait estimates.")
    elif payload["fixture_only"]:
        raise StudyAssessmentValidationError("Approved output cannot be marked as fixture data.")
    if package.manifest.package_id == 'production-island-letter-v2':
        if payload['domains'] or payload.get('facets') or not payload.get('island_letter'):
            raise StudyAssessmentValidationError('Island letters require a controlled body and no scores.')
    elif payload.get('island_letter') is not None:
        raise StudyAssessmentValidationError('Unexpected island letter for this package.')
    if package.manifest.package_id in ('holiday-observation-only-v1','production-observation-v1'):
        from study.draft_assessment import FACETS
        facets = payload.get('facets') or []
        if (set(domain_ids) != set(package.manifest.enabled_domain_ids)
            or any(d['status'] != 'not_estimated' or d.get('value') is not None for d in payload['domains'])
            or len(facets) != len(FACETS) or {f.get('facet_id') for f in facets} != set(FACETS)
            or any(f.get('score') is not None or f.get('status') != 'insufficient' for f in facets)
            or (payload['result_kind'],payload['data_sufficiency']) not in {('data_insufficient','insufficient'),('observational_estimate','sufficient')}):
            raise StudyAssessmentValidationError("Observation-only reports cannot contain trait scores.")
    normalized_strings = [item.casefold() for item in _all_strings(payload)]
    if any(term in text for text in normalized_strings for term in _PROHIBITED_OUTPUT_LANGUAGE):
        raise StudyAssessmentValidationError("Provider output contains prohibited clinical language.")
    for fragment in raw_participant_fragments:
        normalized = fragment.strip().casefold()
        if len(normalized) >= 5 and any(normalized in text for text in normalized_strings):
            raise StudyAssessmentValidationError("Provider output repeats participant text.")
    return payload


def _insufficient_output() -> dict[str, Any]:
    raw = FixtureGameAssessmentProvider().assess(
        {"data_sufficiency": {"sufficient": False}}
    )
    return {**raw, "result_kind": "data_insufficient"}


def _response_hash(raw: Any) -> str | None:
    try:
        return _sha(raw)
    except (TypeError, ValueError):
        return None


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, (ProviderTimeoutError, TimeoutError)):
        return "provider_timeout"
    if isinstance(exc, StudyAssessmentValidationError):
        return "provider_invalid_output"
    if isinstance(exc, ProviderUnavailableError):
        return "provider_unavailable"
    return "provider_error"


def run_game_estimate(
    db: DBSession,
    *,
    study_session: StudySession,
    idempotency_key: str,
    provider: Any | None = None,
) -> AssessmentLifecycleResult:
    with _job_lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        job = _job_for(db, study_session.id)
        if job is None:
            raise StudyWorkflowError(
                "Assessment job has not been started.", 409, "assessment_job_missing"
            )
        estimate = db.query(StudyGameEstimate).filter_by(assessment_job_id=job.id).one_or_none()
        if estimate is not None:
            return AssessmentLifecycleResult(study_session, job, estimate, True)
        lease = db.get(StudyAssessmentLease, job.id)
        now = utc_now()
        if lease and lease.token and lease.expires_at and lease.expires_at > now:
            return AssessmentLifecycleResult(study_session, job, None, True)
        # Preserve uncertain delivery after a worker crash; do not reset attempts.
        for orphan in db.query(StudyAssessmentAttempt).filter_by(assessment_job_id=job.id, status="processing").all():
            orphan.status = "outcome_unknown"
            orphan.error_code = "lease_expired_result_unknown"
            orphan.completed_at = now
        if job.attempt_count >= 3 and study_session.state == StudyWorkflowState.GAME_ESTIMATE_PROCESSING.value:
            job.status = "technical_incomplete"
            job.last_error_code = "retry_limit_after_interruption"
            job.completed_at = now
            result = transition_study_session(db, study_session_id=study_session.id,
                requested_state=StudyWorkflowState.TECHNICAL_INCOMPLETE, expected_revision=study_session.revision,
                idempotency_key=f"{idempotency_key}:exhausted", source="assessment_system",
                reason_code=job.last_error_code, related_record_type="assessment_job", related_record_id=str(job.id))
            db.refresh(job)
            return AssessmentLifecycleResult(result.study_session, job, None, False)
        replay_attempt = db.query(StudyAssessmentAttempt).filter_by(
            assessment_job_id=job.id, idempotency_key=idempotency_key
        ).one_or_none()
        if replay_attempt is not None:
            db.commit()
            db.refresh(study_session)
            db.refresh(job)
            return AssessmentLifecycleResult(study_session, job, None, True)
        if study_session.state != StudyWorkflowState.GAME_ESTIMATE_PROCESSING.value:
            raise StudyWorkflowError(
                "Assessment job is not ready to run.", 409, "invalid_transition"
            )
        boundary = db.query(StudyWorldBoundary).filter_by(study_session_id=study_session.id).one()
        snapshot = db.query(StudyFeatureSnapshot).filter_by(study_session_id=study_session.id).one()
        mode, package = _resolve_package(boundary, snapshot)
        if (
            job.mode != mode.value
            or job.package_id != package.manifest.package_id
            or job.package_version != package.manifest.package_version
            or job.package_sha256 != package.manifest.integrity_sha256
        ):
            raise StudyWorkflowError(
                "Assessment package changed after the job began.", 409, "assessment_package_drift"
            )
        snapshot = db.query(StudyFeatureSnapshot).filter_by(study_session_id=study_session.id).one()
        request_payload = _build_request(snapshot, boundary, package)
        input_sha256 = _sha(request_payload)
        if job.input_sha256 is not None and job.input_sha256 != input_sha256:
            raise StudyWorkflowError(
                "Frozen assessment input changed between attempts.",
                409,
                "assessment_input_drift",
            )
        job.input_sha256 = input_sha256
        if lease is None:
            lease = StudyAssessmentLease(assessment_job_id=job.id)
            db.add(lease)
            db.flush()
        lease_token = secrets.token_hex(24)
        claimed = db.execute(update(StudyAssessmentLease).where(
            StudyAssessmentLease.assessment_job_id == job.id,
            or_(StudyAssessmentLease.token.is_(None), StudyAssessmentLease.expires_at <= now),
        ).values(token=lease_token, expires_at=now + timedelta(minutes=3)))
        if claimed.rowcount != 1:
            db.rollback()
            return AssessmentLifecycleResult(study_session, job, None, True)
        job.attempt_count += 1
        job.updated_at = utc_now()
        attempt = StudyAssessmentAttempt(
            assessment_job_id=job.id,
            attempt_number=job.attempt_count,
            idempotency_key=idempotency_key,
            request_schema_version=package.request_schema_version,
            request_payload_json=canonical_json(request_payload),
            request_sha256=input_sha256,
            status="processing",
            started_at=utc_now(),
        )
        db.add(attempt)
        db.flush()
        sufficient = snapshot.sufficient
        raw_fragments = tuple(row.response_text for row in db.query(WorldAction)
            .filter_by(session_id=boundary.world_session_id).all() if row.response_text)
        # Commit the lease and request before waiting for the provider.
        study_pk, job_pk, attempt_pk = study_session.id, job.id, attempt.id
        db.commit()

        target_state: StudyWorkflowState
        result_payload: dict[str, Any] | None = None
        error: Exception | None = None
        if not sufficient and package.fixture_only:
            result_payload = validate_provider_output(
                _insufficient_output(), package=package
            )
            target_state = StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT
            attempt.status = "not_called_insufficient"
        else:
            if not package.fixture_only:
                from study.holiday_assessment_v5 import Provider
                if package.manifest.package_id == "production-observation-v1":
                    from study.production_observation import Provider
                elif package.manifest.package_id == 'production-island-letter-v2':
                    from study.production_letter import Provider
                assessment_provider = provider or Provider()
            else:
                assessment_provider = provider or FixtureGameAssessmentProvider()
            try:
                raw_output = assessment_provider.assess(request_payload["encoded_features"])
                if package.manifest.package_id == "production-observation-v1":
                    from study.production_observation import Provider as EvidenceProvider
                    if raw_output != EvidenceProvider().assess(request_payload["encoded_features"]):
                        raise StudyAssessmentValidationError("Observation output does not match frozen evidence.")
                if package.manifest.package_id == 'production-island-letter-v2':
                    from study.production_letter import verify
                    verify(raw_output, request_payload['encoded_features'])
                result_payload = validate_provider_output(
                    raw_output,
                    package=package,
                    # Reconstruct quotes from frozen session facts before use.
                    raw_participant_fragments=() if package.manifest.package_id == 'production-island-letter-v2' else raw_fragments,
                )
                attempt.response_sha256 = _sha(result_payload)
                attempt.status = "succeeded"
                target_state = StudyWorkflowState.GAME_ESTIMATE_FROZEN
            except Exception as exc:  # provider boundary: audit error, never persist raw output
                error = exc
                attempt.response_sha256 = _response_hash(locals().get("raw_output"))
                attempt.status = "failed"
                attempt.error_code = _failure_code(exc)
                target_state = (
                    StudyWorkflowState.TECHNICAL_INCOMPLETE
                    if job.attempt_count >= 3 and not __import__("study.protocol_v2",fromlist=["enabled"]).enabled(study_session)
                    else StudyWorkflowState.GAME_ESTIMATE_FAILED
                )

        # Recheck withdrawal and lease ownership after the provider returns.
        attempt_status, attempt_error, response_sha = attempt.status, attempt.error_code, attempt.response_sha256
        db.rollback()
        study_session = db.get(StudySession, study_pk)
        job = db.get(StudyAssessmentJob, job_pk)
        attempt = db.get(StudyAssessmentAttempt, attempt_pk)
        released = db.execute(update(StudyAssessmentLease).where(
            StudyAssessmentLease.assessment_job_id == job_pk,
            StudyAssessmentLease.token == lease_token,
            StudyAssessmentLease.expires_at > utc_now(),
        ).values(token=None, expires_at=None))
        if released.rowcount != 1:
            db.rollback()
            estimate = db.query(StudyGameEstimate).filter_by(assessment_job_id=job_pk).one_or_none()
            return AssessmentLifecycleResult(study_session, job, estimate, True)
        if study_session.state != StudyWorkflowState.GAME_ESTIMATE_PROCESSING.value:
            attempt.status = "discarded"
            attempt.error_code = "workflow_changed_during_generation"
            attempt.completed_at = utc_now()
            db.commit()
            db.refresh(study_session)
            db.refresh(job)
            return AssessmentLifecycleResult(study_session, job, None, False)
        attempt.status, attempt.error_code, attempt.response_sha256 = attempt_status, attempt_error, response_sha
        now = utc_now()
        attempt.completed_at = now
        if result_payload is not None:
            if package.fixture_only:
                rendered = FixtureReportRenderer().render(result_payload, study_session.language)
            else:
                from study.holiday_assessment_v5 import render
                if package.manifest.package_id == 'production-island-letter-v2':
                    from study.production_letter import render
                rendered = render(result_payload)
                if result_payload['data_sufficiency']=='insufficient':
                    target_state = StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT
            output_sha256 = _sha(
                {"result": result_payload, "report_text": rendered, "package": job.package_sha256}
            )
            estimate = StudyGameEstimate(
                study_session_id=study_session.id,
                assessment_job_id=job.id,
                analysis_version=job.analysis_version,
                result_schema_version=package.result_schema_version,
                result_kind=result_payload["result_kind"],
                fixture_only=package.fixture_only,
                result_json=canonical_json(result_payload),
                report_text=rendered,
                output_sha256=output_sha256,
                frozen_at=now,
            )
            db.add(estimate)
            db.flush()
            job.status = "insufficient" if target_state is StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT else "frozen"
            job.last_error_code = None
            job.completed_at = now
            related_type = "game_estimate"
            related_id = str(estimate.id)
            reason_code = (
                "game_estimate_data_insufficient"
                if target_state is StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT
                else "fixture_game_estimate_frozen" if package.fixture_only else "observation_report_frozen"
            )
        else:
            job.last_error_code = attempt.error_code
            job.status = "technical_incomplete" if target_state is StudyWorkflowState.TECHNICAL_INCOMPLETE else "failed"
            job.completed_at = now if target_state is StudyWorkflowState.TECHNICAL_INCOMPLETE else None
            related_type = "assessment_attempt"
            related_id = str(attempt.id)
            reason_code = attempt.error_code or "provider_error"
        job.updated_at = now
        transition = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=target_state,
            expected_revision=study_session.revision,
            idempotency_key=f"{idempotency_key}:result",
            source="assessment_system",
            reason_code=reason_code,
            related_record_type=related_type,
            related_record_id=related_id,
        )
        db.refresh(job)
        if estimate is not None:
            db.refresh(estimate)
        # Error details stay server-side; the lifecycle state is the API contract.
        _ = error
        return AssessmentLifecycleResult(transition.study_session, job, estimate, False)


def assessment_status(db: DBSession, study_session: StudySession) -> dict[str, Any]:
    job = _job_for(db, study_session.id)
    if job is None:
        return {
            "state": study_session.state,
            "revision": study_session.revision,
            "job_status": "not_started",
            "fixture_only": False,
        }
    estimate = db.query(StudyGameEstimate).filter_by(assessment_job_id=job.id).one_or_none()
    return {
        "state": study_session.state,
        "revision": study_session.revision,
        "job_status": job.status,
        "attempt_count": job.attempt_count,
        "last_error_code": job.last_error_code,
        "package_id": job.package_id,
        "package_version": job.package_version,
        "package_sha256": job.package_sha256,
        "input_sha256": job.input_sha256,
        "output_sha256": estimate.output_sha256 if estimate else None,
        "fixture_only": bool(estimate.fixture_only) if estimate else job.mode == "fixture",
        "frozen_at": estimate.frozen_at.isoformat() if estimate else None,
    }

