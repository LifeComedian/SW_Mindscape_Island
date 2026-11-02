from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
import json
import os
from typing import Any, Mapping

from study.contracts import (
    AssessmentPackageManifest,
    AssessmentPackageStatus,
    BFI2_DOMAIN_IDS,
)


FIXTURE_PACKAGE_ID = "m6e-fixture-game-estimate"
FIXTURE_PACKAGE_VERSION = "1.0.0-test-only"
SYSTEM_CONTRACT_VERSION = "study-runtime-m6"
GAME_ESTIMATE_REQUEST_SCHEMA_VERSION = "game-estimate-request-v1"
GAME_ESTIMATE_RESULT_SCHEMA_VERSION = "game-estimate-result-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


_FIXTURE_PACKAGE_MATERIAL: dict[str, Any] = {
    "package_id": FIXTURE_PACKAGE_ID,
    "package_version": FIXTURE_PACKAGE_VERSION,
    "status": "draft",
    "compatible_versions": {
        "world_version": "study-m6-fixture-v1",
        "scenario_pack_version": "study-m6-fixture-scenarios-v1",
        "content_pack_version": "study-m6-fixture-content-v1",
        "event_pack_version": "study-m6-fixture-events-v1",
        "system_contract_version": SYSTEM_CONTRACT_VERSION,
    },
    "observation_schema_version": "game-observation-v1",
    "feature_schema_version": "fixture-features-v1",
    "extractor_version": "fixture-counts-v1",
    "evidence_mapping_version": "fixture-neutral-evidence-v1",
    "sufficiency_policy_version": "fixture-any-observation-v1",
    "prompt_version": "none-deterministic-fixture",
    "model_id": "deterministic-fixture-no-llm",
    "report_template_version": "fixture-watermarked-report-v1",
    "irb_status": "test_only_not_for_participants",
    "preregistration_status": "not_applicable_fixture",
    "enabled_domain_ids": list(BFI2_DOMAIN_IDS),
    "request_schema_version": GAME_ESTIMATE_REQUEST_SCHEMA_VERSION,
    "result_schema_version": GAME_ESTIMATE_RESULT_SCHEMA_VERSION,
    "feature_allowlist": [
        "language_features",
        "behavior_choice_summary",
        "opportunity_exposure",
        "temporal_context",
        "data_sufficiency",
        "missing_reasons",
    ],
}

FIXTURE_PACKAGE_SHA256 = hashlib.sha256(
    canonical_json(_FIXTURE_PACKAGE_MATERIAL).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class AssessmentPackageDefinition:
    manifest: AssessmentPackageManifest
    request_schema_version: str
    result_schema_version: str
    feature_allowlist: tuple[str, ...]
    fixture_only: bool


FIXTURE_PACKAGE = AssessmentPackageDefinition(
    manifest=AssessmentPackageManifest(
        package_id=FIXTURE_PACKAGE_ID,
        package_version=FIXTURE_PACKAGE_VERSION,
        status=AssessmentPackageStatus.DRAFT,
        compatible_versions=_FIXTURE_PACKAGE_MATERIAL["compatible_versions"],
        observation_schema_version=_FIXTURE_PACKAGE_MATERIAL["observation_schema_version"],
        feature_schema_version=_FIXTURE_PACKAGE_MATERIAL["feature_schema_version"],
        extractor_version=_FIXTURE_PACKAGE_MATERIAL["extractor_version"],
        evidence_mapping_version=_FIXTURE_PACKAGE_MATERIAL["evidence_mapping_version"],
        sufficiency_policy_version=_FIXTURE_PACKAGE_MATERIAL["sufficiency_policy_version"],
        prompt_version=_FIXTURE_PACKAGE_MATERIAL["prompt_version"],
        model_id=_FIXTURE_PACKAGE_MATERIAL["model_id"],
        report_template_version=_FIXTURE_PACKAGE_MATERIAL["report_template_version"],
        irb_status=_FIXTURE_PACKAGE_MATERIAL["irb_status"],
        preregistration_status=_FIXTURE_PACKAGE_MATERIAL["preregistration_status"],
        integrity_sha256=FIXTURE_PACKAGE_SHA256,
        enabled_domain_ids=BFI2_DOMAIN_IDS,
    ),
    request_schema_version=GAME_ESTIMATE_REQUEST_SCHEMA_VERSION,
    result_schema_version=GAME_ESTIMATE_RESULT_SCHEMA_VERSION,
    feature_allowlist=tuple(_FIXTURE_PACKAGE_MATERIAL["feature_allowlist"]),
    fixture_only=True,
)


_TEST_PACKAGES: dict[str, tuple[AssessmentPackageDefinition, dict]] = {}


def register_test_world_package(spec):
    """Explicit synthetic harness registration, with its own compatible-version hash."""
    if os.getenv("STUDY_RUNTIME_ENV") != "test" or os.getenv("DELIVERY_E2E_ENABLED") != "true":
        raise RuntimeError("Additional test packages require the synthetic delivery harness.")
    material = deepcopy(_FIXTURE_PACKAGE_MATERIAL)
    material["package_id"] = "delivery-holiday-fixture"
    material["compatible_versions"] = {"world_version": spec.world_version,
        "scenario_pack_version": spec.scenario_pack_version, "content_pack_version": spec.content_pack_version,
        "event_pack_version": spec.event_pack_version, "system_contract_version": SYSTEM_CONTRACT_VERSION}
    sha = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    package = replace(FIXTURE_PACKAGE, manifest=replace(FIXTURE_PACKAGE.manifest,
        package_id=material["package_id"], compatible_versions=material["compatible_versions"], integrity_sha256=sha))
    _TEST_PACKAGES[spec.world_version] = (package, material)


def fixture_package_for(world_version):
    return _TEST_PACKAGES.get(world_version, (FIXTURE_PACKAGE, None))[0]


def fixture_integrity_verified(package=FIXTURE_PACKAGE) -> bool:
    material = _TEST_PACKAGES.get(package.manifest.compatible_versions["world_version"], (None, _FIXTURE_PACKAGE_MATERIAL))[1]
    computed = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    configured = os.getenv("STUDY_ASSESSMENT_PACKAGE_SHA256", "").strip().lower()
    return computed == package.manifest.integrity_sha256 and (not configured or configured == computed)


def versions_match_fixture(actual: Mapping[str, str], package=FIXTURE_PACKAGE) -> bool:
    expected = package.manifest.compatible_versions
    return all(actual.get(key) == value for key, value in expected.items())

