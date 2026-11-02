from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


STUDY_CONTRACT_VERSION = "study-session-contract-v1"
OBSERVATION_SCHEMA_VERSION = "game-observation-v1"


class StudyContractError(ValueError):
    """Raised when a caller attempts to violate a frozen study contract."""


class StudyWorkflowState(StrEnum):
    CONSENT_PENDING = "consent_pending"
    CONSENT_DECLINED = "consent_declined"
    CONSENTED = "consented"
    ELIGIBILITY_PENDING = "eligibility_pending"
    ELIGIBILITY_INELIGIBLE = "eligibility_ineligible"
    ELIGIBILITY_CONFIRMED = "eligibility_confirmed"
    ONBOARDING = "onboarding"
    ISLAND_ACTIVE = "island_active"
    ISLAND_DEPARTURE_PENDING = "island_departure_pending"
    ISLAND_COMPLETED = "island_completed"
    GAME_ESTIMATE_PROCESSING = "game_estimate_processing"
    GAME_ESTIMATE_FROZEN = "game_estimate_frozen"
    GAME_ESTIMATE_INSUFFICIENT = "game_estimate_insufficient"
    GAME_ESTIMATE_FAILED = "game_estimate_failed"
    QUESTIONNAIRE_ACTIVE = "questionnaire_active"
    QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
    PRE_RESULT_FEEDBACK = "pre_result_feedback"
    RESULTS_READY = "results_ready"
    RESULT_ONE_ACTIVE = "result_one_active"
    RESULT_ONE_RATED = "result_one_rated"
    RESULT_TWO_ACTIVE = "result_two_active"
    RESULT_TWO_RATED = "result_two_rated"
    COMPARATIVE_FEEDBACK = "comparative_feedback"
    DEBRIEF = "debrief"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"
    TECHNICAL_INCOMPLETE = "technical_incomplete"


TERMINAL_STATES = frozenset(
    {
        StudyWorkflowState.CONSENT_DECLINED,
        StudyWorkflowState.ELIGIBILITY_INELIGIBLE,
        StudyWorkflowState.COMPLETED,
        StudyWorkflowState.WITHDRAWN,
        StudyWorkflowState.TECHNICAL_INCOMPLETE,
    }
)


_CORE_TRANSITIONS: dict[StudyWorkflowState, frozenset[StudyWorkflowState]] = {
    StudyWorkflowState.CONSENT_PENDING: frozenset(
        {StudyWorkflowState.CONSENT_DECLINED, StudyWorkflowState.CONSENTED}
    ),
    StudyWorkflowState.CONSENTED: frozenset({StudyWorkflowState.ELIGIBILITY_PENDING}),
    StudyWorkflowState.ELIGIBILITY_PENDING: frozenset(
        {
            StudyWorkflowState.ELIGIBILITY_INELIGIBLE,
            StudyWorkflowState.ELIGIBILITY_CONFIRMED,
        }
    ),
    StudyWorkflowState.ELIGIBILITY_CONFIRMED: frozenset({StudyWorkflowState.ONBOARDING}),
    StudyWorkflowState.ONBOARDING: frozenset({StudyWorkflowState.ISLAND_ACTIVE}),
    StudyWorkflowState.ISLAND_ACTIVE: frozenset(
        {StudyWorkflowState.ISLAND_DEPARTURE_PENDING}
    ),
    StudyWorkflowState.ISLAND_DEPARTURE_PENDING: frozenset(
        {StudyWorkflowState.ISLAND_ACTIVE, StudyWorkflowState.ISLAND_COMPLETED}
    ),
    StudyWorkflowState.ISLAND_COMPLETED: frozenset(
        {StudyWorkflowState.GAME_ESTIMATE_PROCESSING}
    ),
    StudyWorkflowState.GAME_ESTIMATE_PROCESSING: frozenset(
        {
            StudyWorkflowState.GAME_ESTIMATE_FROZEN,
            StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT,
            StudyWorkflowState.GAME_ESTIMATE_FAILED,
        }
    ),
    StudyWorkflowState.GAME_ESTIMATE_FAILED: frozenset(
        {StudyWorkflowState.GAME_ESTIMATE_PROCESSING}
    ),
    StudyWorkflowState.GAME_ESTIMATE_FROZEN: frozenset(
        {StudyWorkflowState.QUESTIONNAIRE_ACTIVE}
    ),
    StudyWorkflowState.GAME_ESTIMATE_INSUFFICIENT: frozenset(
        {StudyWorkflowState.QUESTIONNAIRE_ACTIVE}
    ),
    StudyWorkflowState.QUESTIONNAIRE_ACTIVE: frozenset(
        {StudyWorkflowState.QUESTIONNAIRE_COMPLETED}
    ),
    StudyWorkflowState.QUESTIONNAIRE_COMPLETED: frozenset(
        {StudyWorkflowState.PRE_RESULT_FEEDBACK}
    ),
    StudyWorkflowState.PRE_RESULT_FEEDBACK: frozenset({StudyWorkflowState.RESULTS_READY}),
    StudyWorkflowState.RESULTS_READY: frozenset({StudyWorkflowState.RESULT_ONE_ACTIVE}),
    StudyWorkflowState.RESULT_ONE_ACTIVE: frozenset({StudyWorkflowState.RESULT_ONE_RATED}),
    StudyWorkflowState.RESULT_ONE_RATED: frozenset({StudyWorkflowState.RESULT_TWO_ACTIVE}),
    StudyWorkflowState.RESULT_TWO_ACTIVE: frozenset({StudyWorkflowState.RESULT_TWO_RATED}),
    StudyWorkflowState.RESULT_TWO_RATED: frozenset(
        {StudyWorkflowState.COMPARATIVE_FEEDBACK}
    ),
    StudyWorkflowState.COMPARATIVE_FEEDBACK: frozenset({StudyWorkflowState.DEBRIEF}),
    StudyWorkflowState.DEBRIEF: frozenset({StudyWorkflowState.COMPLETED}),
}


def _build_transitions() -> Mapping[StudyWorkflowState, frozenset[StudyWorkflowState]]:
    transitions: dict[StudyWorkflowState, frozenset[StudyWorkflowState]] = {}
    interruptible = {
        state
        for state in StudyWorkflowState
        if state
        not in TERMINAL_STATES
        | {StudyWorkflowState.CONSENT_PENDING}
    }
    for state in StudyWorkflowState:
        allowed = set(_CORE_TRANSITIONS.get(state, frozenset()))
        if state in interruptible:
            allowed.update(
                {StudyWorkflowState.WITHDRAWN, StudyWorkflowState.TECHNICAL_INCOMPLETE}
            )
        transitions[state] = frozenset(allowed)
    return MappingProxyType(transitions)


ALLOWED_TRANSITIONS = _build_transitions()


def allowed_next_states(state: StudyWorkflowState) -> frozenset[StudyWorkflowState]:
    return ALLOWED_TRANSITIONS[state]


def assert_transition_allowed(
    current: StudyWorkflowState,
    requested: StudyWorkflowState,
) -> None:
    if requested not in allowed_next_states(current):
        raise StudyContractError(
            f"Study transition {current.value!r} -> {requested.value!r} is not allowed."
        )


class AssessmentMode(StrEnum):
    DISABLED = "disabled"
    FIXTURE = "fixture"
    APPROVED = "approved"
    EXPERIMENTAL = "experimental"
    OBSERVATION = "observation"


class AssessmentPackageStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class RuntimeEnvironment(StrEnum):
    TEST = "test"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


BFI2_DOMAIN_IDS = (
    "extraversion",
    "agreeableness",
    "conscientiousness",
    "negative_emotionality",
    "open_mindedness",
)

ASSESSMENT_INTERFACE_NAMES = (
    "FeatureExtractor",
    "EvidenceMapper",
    "GameAssessmentProvider",
    "ReportRenderer",
)

# Freeze these fields only after the world and opportunities are defined.
DEFERRED_ASSESSMENT_FIELDS = frozenset(
    {
        "feature_dictionary",
        "feature_directions",
        "feature_weights",
        "decision_thresholds",
        "minimum_evidence",
        "missing_data_rules",
        "language_coding_rules",
        "evidence_mapping",
        "production_prompt",
    }
)


@dataclass(frozen=True, slots=True)
class ObservationEvent:
    """Content-neutral fact emitted by the game before personality inference.

    It captures opportunities as well as responses.  Content-specific research
    annotations and personality scores do not belong in this record.
    """

    observation_id: str
    study_session_id: str
    world_session_id: int
    occurred_at: str
    world_day: int
    world_time_minutes: int
    actor_type: str
    observation_type: str
    source: str
    technical_status: str
    versions: Mapping[str, str]
    actor_id: str | None = None
    location_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    opportunity_id: str | None = None
    offered_option_ids: tuple[str, ...] = ()
    available_option_ids: tuple[str, ...] = ()
    selected_option_id: str | None = None
    outcome_code: str | None = None
    schema_version: str = OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.observation_id or not self.study_session_id:
            raise StudyContractError("Observation identifiers must be non-empty.")
        if self.world_session_id < 1:
            raise StudyContractError("world_session_id must be positive.")
        if self.world_day < 1 or not 0 <= self.world_time_minutes <= 1439:
            raise StudyContractError("World day or minute is outside the supported range.")
        if len(set(self.offered_option_ids)) != len(self.offered_option_ids):
            raise StudyContractError("offered_option_ids must be unique.")
        if len(set(self.available_option_ids)) != len(self.available_option_ids):
            raise StudyContractError("available_option_ids must be unique.")
        if not set(self.available_option_ids).issubset(self.offered_option_ids):
            raise StudyContractError("Available options must be a subset of offered options.")
        if (
            self.selected_option_id is not None
            and self.selected_option_id not in self.available_option_ids
        ):
            raise StudyContractError("The selected option must have been available.")
        if not self.versions:
            raise StudyContractError("Observation records must bind content versions.")


@dataclass(frozen=True, slots=True)
class AssessmentPackageManifest:
    """Immutable metadata envelope; no feature weights are defined in M6-A."""

    package_id: str
    package_version: str
    status: AssessmentPackageStatus
    compatible_versions: Mapping[str, str]
    observation_schema_version: str
    feature_schema_version: str
    extractor_version: str
    evidence_mapping_version: str
    sufficiency_policy_version: str
    prompt_version: str
    model_id: str
    report_template_version: str
    irb_status: str
    preregistration_status: str
    integrity_sha256: str
    enabled_domain_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.package_id or not self.package_version:
            raise StudyContractError("Assessment package identity is required.")
        if not set(self.enabled_domain_ids).issubset(BFI2_DOMAIN_IDS):
            raise StudyContractError("Assessment package contains an unknown BFI-2 domain.")
        if len(self.integrity_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.integrity_sha256.lower()
        ):
            raise StudyContractError("integrity_sha256 must be a 64-character hex digest.")


def assert_assessment_runtime_allowed(
    *,
    mode: AssessmentMode,
    environment: RuntimeEnvironment,
    package: AssessmentPackageManifest | None,
    versions_match: bool,
    integrity_verified: bool,
) -> None:
    """Fail closed when a test fixture or unapproved package could reach research."""

    if mode is AssessmentMode.DISABLED:
        return
    if mode is AssessmentMode.FIXTURE:
        if environment is RuntimeEnvironment.PRODUCTION:
            raise StudyContractError("Fixture assessments are forbidden in production.")
        if package is not None:
            raise StudyContractError("Fixture mode must not impersonate an assessment package.")
        return
    if package is None:
        raise StudyContractError("Approved mode requires an assessment package.")
    if package.status is not AssessmentPackageStatus.APPROVED:
        raise StudyContractError("Only an approved assessment package can run.")
    if not versions_match:
        raise StudyContractError("Assessment package is incompatible with the bound world.")
    if not integrity_verified:
        raise StudyContractError("Assessment package integrity verification failed.")
