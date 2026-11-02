from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from study.contracts import ObservationEvent
from study.contracts import BFI2_DOMAIN_IDS


FEATURE_SCHEMA_VERSION = "fixture-features-v1"
FIXTURE_EXTRACTOR_VERSION = "fixture-counts-v1"


@dataclass(frozen=True, slots=True)
class FeatureExtractionResult:
    features: Mapping[str, Any]
    opportunity_denominators: Mapping[str, int]
    missing_reasons: Mapping[str, str]
    sufficient: bool
    observation_count: int
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    extractor_version: str = FIXTURE_EXTRACTOR_VERSION


class FeatureExtractor(Protocol):
    def extract(self, observations: Sequence[ObservationEvent]) -> FeatureExtractionResult: ...


class EvidenceMapper(Protocol):
    def map_evidence(self, features: FeatureExtractionResult) -> Mapping[str, Any]: ...


class GameAssessmentProvider(Protocol):
    def assess(self, evidence: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ReportRenderer(Protocol):
    def render(self, assessment: Mapping[str, Any], language: str) -> str: ...


class FixtureCountFeatureExtractor:
    """Non-interpretive fixture used to validate the M6 plumbing only."""

    def extract(self, observations: Sequence[ObservationEvent]) -> FeatureExtractionResult:
        action_counts: dict[str, int] = {}
        opportunity_count = 0
        selected_count = 0
        for observation in observations:
            action_counts[observation.observation_type] = (
                action_counts.get(observation.observation_type, 0) + 1
            )
            if observation.offered_option_ids:
                opportunity_count += 1
            if observation.selected_option_id is not None:
                selected_count += 1
        missing: dict[str, str] = {}
        if not observations:
            missing["observations"] = "no_observations_recorded"
        if opportunity_count == 0:
            missing["choice_opportunities"] = "no_option_sets_observed"
        return FeatureExtractionResult(
            features={
                "action_counts": action_counts,
                "selected_option_count": selected_count,
            },
            opportunity_denominators={"choice_opportunities": opportunity_count},
            missing_reasons=missing,
            sufficient=bool(observations),
            observation_count=len(observations),
        )


class FixtureNeutralEvidenceMapper:
    """Passes only aggregate fixture evidence; it contains no trait mapping."""

    def map_evidence(self, features: FeatureExtractionResult) -> Mapping[str, Any]:
        return {
            "language_features": {},
            "behavior_choice_summary": dict(features.features),
            "opportunity_exposure": dict(features.opportunity_denominators),
            "data_sufficiency": {
                "sufficient": features.sufficient,
                "observation_count": features.observation_count,
            },
            "missing_reasons": dict(features.missing_reasons),
        }


class FixtureGameAssessmentProvider:
    """Deterministic plumbing double. It never infers participant traits."""

    def assess(self, evidence: Mapping[str, Any]) -> Mapping[str, Any]:
        sufficiency = evidence.get("data_sufficiency", {})
        is_sufficient = bool(
            isinstance(sufficiency, Mapping) and sufficiency.get("sufficient")
        )
        return {
            "schema_version": "game-estimate-result-v1",
            "result_kind": "fixture_pipeline_check",
            "fixture_only": True,
            "watermark": "TEST FIXTURE — NOT A PARTICIPANT RESULT",
            "domains": [
                {
                    "domain_id": domain_id,
                    "status": "not_estimated",
                    "description": "测试占位字段：未进行估计。",
                    "basis": [],
                }
                for domain_id in BFI2_DOMAIN_IDS
            ],
            "data_sufficiency": "sufficient" if is_sufficient else "insufficient",
            "uncertainty_note": "正式特征、映射和聚合方法尚未定义。",
            "limitations": [
                "该内容仅验证评估管线、版本门禁和数据隔离。",
                "该内容不代表参与者结果，也不得用于真人研究。",
            ],
            "gentle_summary": "测试管线已完成；未对参与者作出任何推断。",
        }


class FixtureReportRenderer:
    """Watermarked fixture rendering; formal result prose remains deferred."""

    def render(self, assessment: Mapping[str, Any], language: str) -> str:
        if language == "en":
            return (
                "TEST FIXTURE — NOT A PARTICIPANT RESULT\n"
                "The assessment pipeline completed without producing a participant estimate."
            )
        return (
            "测试夹具——不是参与者结果\n"
            "评估管线已完成，但没有生成任何参与者人格估计。"
        )
