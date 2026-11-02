"""Content Studio validation and in-memory exports."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
import zipfile

from fastapi import HTTPException, Request

from content.loader import (
    BUILTIN_PACKS_ROOT,
    load_all_builtin_content_packs,
    load_builtin_content_pack,
)
from content.serializers import content_pack_summary
from content.validator import (
    ContentPackValidationError,
    build_world_spec,
    validate_manifest_for_loading,
)
from content.visual_assets import (
    MAX_TOTAL_IMAGE_BYTES,
    VisualAssetValidationError,
    validate_image_bytes,
)
from world.registry import get_world_spec, list_world_versions


STUDIO_ENV_NAME = "CONTENT_STUDIO_ENABLED"
MAX_DRAFT_BYTES = 5_000_000
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_ARCHIVE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
AUTHORING_TEMPLATES_ROOT = Path(__file__).resolve().parents[1] / "content" / "templates"
_DIRECTORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def require_content_studio(request: Request) -> None:
    enabled = os.getenv(STUDIO_ENV_NAME, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    host = request.client.host.lower() if request.client else ""
    if not enabled or host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=404, detail="Not found")


def list_installed_packs() -> list[dict[str, Any]]:
    runtime_packs = [
        {
            "directory_name": pack.root.name,
            "kind": "runtime_pack",
            **content_pack_summary(pack.world_spec),
        }
        for pack in load_all_builtin_content_packs()
    ]
    templates: list[dict[str, Any]] = []
    if AUTHORING_TEMPLATES_ROOT.is_dir():
        for root in sorted(AUTHORING_TEMPLATES_ROOT.iterdir(), key=lambda item: item.name):
            if not root.is_dir() or not _DIRECTORY_RE.fullmatch(root.name):
                continue
            manifest = _read_trusted_json(root / "manifest.json")
            if manifest.get("authoring_only") is not True:
                continue
            templates.append(
                {
                    "directory_name": root.name,
                    "kind": "authoring_template",
                    "content_pack_version": manifest.get("content_pack_version"),
                    "world_version": manifest.get("world_version"),
                    "location_count": 0,
                    "resident_count": 0,
                    "event_count": 0,
                }
            )
    return [*runtime_packs, *templates]


def read_installed_pack(directory_name: str) -> dict[str, dict[str, Any]]:
    if not _DIRECTORY_RE.fullmatch(directory_name):
        raise HTTPException(status_code=404, detail="Content pack not found")
    template_root = (AUTHORING_TEMPLATES_ROOT / directory_name).resolve()
    if (
        AUTHORING_TEMPLATES_ROOT.is_dir()
        and template_root.parent == AUTHORING_TEMPLATES_ROOT.resolve()
        and template_root.is_dir()
    ):
        manifest = _read_trusted_json(template_root / "manifest.json")
        if manifest.get("authoring_only") is not True:
            raise HTTPException(status_code=404, detail="Content pack not found")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) not in (
            {"map", "locations", "residents", "events", "visuals"},
            {"map", "locations", "residents", "events", "visuals", "systems"},
        ):
            raise HTTPException(status_code=422, detail="Authoring template manifest is incomplete")
        result: dict[str, Any] = {"manifest": manifest}
        for document_name, file_name in files.items():
            if not isinstance(file_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json", file_name):
                raise HTTPException(status_code=422, detail="Authoring template contains an unsafe filename")
            result[document_name] = _read_trusted_json(template_root / file_name)
        return result

    loaded = load_builtin_content_pack(directory_name)
    root = loaded.root.resolve(strict=True)
    if root.parent != BUILTIN_PACKS_ROOT.resolve(strict=True):
        raise HTTPException(status_code=404, detail="Content pack not found")

    manifest = _read_trusted_json(root / "manifest.json")
    file_names = validate_manifest_for_loading(manifest)
    result: dict[str, Any] = {
        "manifest": manifest,
        **{
            document_name: _read_trusted_json(root / file_name)
            for document_name, file_name in file_names.items()
        },
    }
    if loaded.visual_asset_paths:
        result["asset_urls"] = {
            asset_key: f"/world-assets/{loaded.world_spec.world_version}/{asset_key}"
            for asset_key in loaded.visual_asset_paths
        }
    return result


def validate_studio_draft(
    draft: Mapping[str, Any],
    asset_blobs: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    manifest = draft.get("manifest") if isinstance(draft, Mapping) else None
    if isinstance(manifest, Mapping) and manifest.get("authoring_only") is True:
        return {
            "valid": False,
            "errors": [{
                "file": "manifest.json",
                "json_path": "$.start_location_id",
                "reason": "Create the first location before runtime validation or export.",
                "message": "manifest.json:$.start_location_id: Create the first location before runtime validation or export.",
            }],
            "version_conflicts": [],
            "summary": None,
        }
    try:
        normalized = _normalize_draft(draft)
        file_names = validate_manifest_for_loading(normalized["manifest"])
        spec = build_world_spec(
            manifest=normalized["manifest"],
            documents={key: normalized[key] for key in file_names},
        )
        _validate_studio_assets(spec, asset_blobs or {})
    except ContentPackValidationError as exc:
        return {
            "valid": False,
            "errors": [
                {
                    "file": exc.file,
                    "json_path": exc.json_path,
                    "reason": exc.reason,
                    "message": str(exc),
                }
            ],
            "version_conflicts": [],
            "summary": None,
        }

    return {
        "valid": True,
        "errors": [],
        "version_conflicts": _version_conflicts(spec),
        "summary": content_pack_summary(spec),
    }


def export_studio_draft(
    draft: Mapping[str, Any],
    asset_blobs: Mapping[str, bytes] | None = None,
) -> tuple[bytes, str]:
    validation = validate_studio_draft(draft, asset_blobs)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation)
    if validation["version_conflicts"]:
        raise HTTPException(
            status_code=409,
            detail={
                **validation,
                "message": "Choose new content, world, map, event, visual, and item versions before export.",
            },
        )

    normalized = _normalize_draft(draft)
    manifest = normalized["manifest"]
    file_names = validate_manifest_for_loading(manifest)
    version = str(manifest["content_pack_version"])
    archive_name = f"{_ARCHIVE_NAME_RE.sub('-', version).strip('-') or 'content-pack'}.zip"

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for document_name, file_name in file_names.items():
            archive.writestr(file_name, _json_bytes(normalized[document_name]))
        visual_spec = build_world_spec(
            manifest=manifest,
            documents={key: normalized[key] for key in file_names},
        ).visual_spec
        if visual_spec is not None:
            for asset_key, asset in visual_spec.visual_assets.items():
                archive.writestr(asset.file_name, (asset_blobs or {})[asset_key])
    return output.getvalue(), archive_name


def audit_studio_draft(draft: Mapping[str, Any], *, seed: int = 7,
                       response: str = "accept", public_consent: bool = False) -> dict[str, Any]:
    """No-write rule graph and seven-day authoring projection; no runtime Session."""
    from world.studio_emergence import rule_graph, project_seven_days, finish_result
    if type(seed) is not int or not 0 <= seed <= 2147483647 or response not in {"accept", "reject", "ignore"} or type(public_consent) is not bool:
        raise HTTPException(status_code=422, detail="Invalid dry-run assumptions.")
    # Rule analysis does not require images; validation and export do.
    try:
        normalized = _normalize_draft(draft)
        filenames = validate_manifest_for_loading(normalized["manifest"])
        spec = build_world_spec(manifest=normalized["manifest"], documents={k: normalized[k] for k in filenames})
    except ContentPackValidationError as exc:
        try:
            graph = rule_graph(normalized)
        except (KeyError, TypeError, AttributeError, UnboundLocalError):
            graph = dict(nodes=[], edges=[])
        if len(graph["nodes"]) + len(graph["edges"]) > 5000:
            graph = dict(nodes=[], edges=[])
        return finish_result(dict(valid=False, complete=False, graph=graph, days=[], findings=[dict(code="schema_error", severity="error", file=exc.file, json_path=exc.json_path, detail=exc.reason)], assumptions=dict(seed=seed, participant_response=response, all_witness_public_consent=public_consent)))
    if spec.systems.get("contract_version") != "modular-emergence-authoring-v1":
        return finish_result(dict(valid=False, complete=False, graph=rule_graph(normalized), days=[], findings=[dict(code="v5_required", severity="error", file="manifest.json", json_path="$.schema_version", detail="请先升级为完整 v5 模块草稿。旧版校验与导出仍可使用。")]))
    graph = rule_graph(normalized)
    if len(graph["nodes"]) + len(graph["edges"]) > 5000:
        raise HTTPException(status_code=413, detail="Rule graph exceeds the 5000-node/edge authoring limit.")
    projection = project_seven_days(spec, seed=seed, response=response, public_consent=public_consent)
    return finish_result(dict(valid=True, **projection, graph=graph, assumptions=dict(seed=seed, participant_response=response, all_witness_public_consent=public_consent, resident_response="accept_if_available", attendance="available_members_arrive", stage_choice="first_lawful_branch_confirmed_by_authority", tick_minutes=30, llm="disabled", note="规则投影；到场、确认和公开同意是显式模拟假设。不是实际 Session 回放，也不运行模型。")))


def _normalize_draft(draft: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        manifest = deepcopy(dict(draft["manifest"]))
        file_names = validate_manifest_for_loading(manifest)
        normalized = {
            "manifest": manifest,
            **{
                key: deepcopy(dict(draft[key]))
                for key in file_names
            },
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ContentPackValidationError(
            "draft is missing a required JSON document",
            file="manifest.json",
            json_path="$.files",
        ) from exc
    encoded_size = sum(len(_json_bytes(document)) for document in normalized.values())
    if encoded_size > MAX_DRAFT_BYTES:
        raise ContentPackValidationError(
            f"browser draft exceeds {MAX_DRAFT_BYTES} bytes",
            file="manifest.json",
            json_path="$",
        )
    return normalized


def _validate_studio_assets(spec: Any, asset_blobs: Mapping[str, bytes]) -> None:
    visual_spec = spec.visual_spec
    if visual_spec is None:
        if asset_blobs:
            raise ContentPackValidationError(
                "content-pack-v1 cannot include visual asset uploads",
                file="manifest.json",
                json_path="$.schema_version",
            )
        return
    expected = set(visual_spec.visual_assets)
    supplied = set(asset_blobs)
    missing = sorted(expected - supplied)
    extra = sorted(supplied - expected)
    if missing:
        raise ContentPackValidationError(
            "missing uploaded asset(s): " + ", ".join(missing),
            file="visuals.json",
            json_path="$.visual_assets",
        )
    if extra:
        raise ContentPackValidationError(
            "undeclared uploaded asset(s): " + ", ".join(extra),
            file="visuals.json",
            json_path="$.visual_assets",
        )
    total = 0
    for asset_key, asset in visual_spec.visual_assets.items():
        data = asset_blobs[asset_key]
        try:
            checked = validate_image_bytes(
                data,
                declared_mime_type=asset.mime_type,
                declared_width=asset.width,
                declared_height=asset.height,
                declared_sha256=asset.sha256,
            )
        except VisualAssetValidationError as exc:
            raise ContentPackValidationError(
                str(exc),
                file=asset.file_name,
                json_path="$",
            ) from exc
        total += checked.size_bytes
        if total > MAX_TOTAL_IMAGE_BYTES:
            raise ContentPackValidationError(
                f"uploaded assets exceed {MAX_TOTAL_IMAGE_BYTES} total bytes",
                file="visuals.json",
                json_path="$.visual_assets",
            )


def _version_conflicts(spec: Any) -> list[dict[str, str]]:
    installed_specs = [get_world_spec(version) for version in list_world_versions()]
    candidates = {
        "content_pack_version": spec.content_pack_version,
        "world_version": spec.world_version,
        "map_version": spec.map_spec.version,
        "event_pack_version": spec.event_pack_version,
        "visual_version": (
            spec.visual_spec.visual_version if spec.visual_spec is not None else None
        ),
    }
    conflicts: list[dict[str, str]] = []
    for field, value in candidates.items():
        if value is None:
            continue
        if any(_spec_version(installed, field) == value for installed in installed_specs):
            conflicts.append(
                {
                    "field": field,
                    "value": str(value),
                    "message": f"{field} {value!r} is already installed; export a new version.",
                }
            )
    return conflicts


def _spec_version(spec: Any, field: str) -> Any:
    if field == "map_version":
        return spec.map_spec.version if spec.map_spec is not None else None
    if field == "visual_version":
        return spec.visual_spec.visual_version if spec.visual_spec is not None else None
    return getattr(spec, field)


def _read_trusted_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContentPackValidationError(
            "must be a JSON object", file=path.name, json_path="$"
        )
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
