"""Safe filesystem loader for data-only JSON content packs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

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
from world.specs import WorldSpec


MAX_CONTENT_FILE_BYTES = 1_000_000
BUILTIN_PACKS_ROOT = Path(__file__).resolve().parent / "packs"
_BUILTIN_DIRECTORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class _DuplicateJsonKey(ValueError):
    pass


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _read_json(path: Path, *, root: Path, label: str) -> Any:
    if path.is_symlink():
        raise ContentPackValidationError(
            "symbolic links are not allowed in content packs",
            file=label,
            json_path="$",
        )
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ContentPackValidationError(
            "required content file does not exist",
            file=label,
            json_path="$",
        ) from exc
    if resolved.parent != root:
        raise ContentPackValidationError(
            "content file resolves outside the pack root",
            file=label,
            json_path="$",
        )
    if not resolved.is_file():
        raise ContentPackValidationError(
            "content path is not a regular file",
            file=label,
            json_path="$",
        )
    size = resolved.stat().st_size
    if size > MAX_CONTENT_FILE_BYTES:
        raise ContentPackValidationError(
            f"content file exceeds {MAX_CONTENT_FILE_BYTES} bytes",
            file=label,
            json_path="$",
        )
    try:
        raw = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ContentPackValidationError(
            "content file must be valid UTF-8",
            file=label,
            json_path="$",
        ) from exc
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (_DuplicateJsonKey, json.JSONDecodeError, ValueError) as exc:
        raise ContentPackValidationError(
            f"invalid JSON: {exc}",
            file=label,
            json_path="$",
        ) from exc


@dataclass(frozen=True)
class LoadedContentPack:
    root: Path
    manifest: Mapping[str, Any]
    world_spec: WorldSpec
    visual_asset_paths: Mapping[str, Path]

    @property
    def summary(self) -> dict[str, Any]:
        return content_pack_summary(self.world_spec)


def load_content_pack(pack_path: str | Path) -> LoadedContentPack:
    requested_root = Path(pack_path)
    if requested_root.is_symlink():
        raise ContentPackValidationError(
            "the content pack directory cannot be a symbolic link",
            file="manifest.json",
            json_path="$",
        )
    try:
        root = requested_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ContentPackValidationError(
            "content pack directory does not exist",
            file="manifest.json",
            json_path="$",
        ) from exc
    if not root.is_dir():
        raise ContentPackValidationError(
            "content pack path must be a directory",
            file="manifest.json",
            json_path="$",
        )

    manifest = _read_json(root / "manifest.json", root=root, label="manifest.json")
    files = validate_manifest_for_loading(manifest)
    documents = {
        key: _read_json(root / file_name, root=root, label=file_name)
        for key, file_name in files.items()
    }
    spec = build_world_spec(manifest=manifest, documents=documents)
    asset_paths = _load_visual_asset_paths(root, spec)
    return LoadedContentPack(
        root=root,
        manifest=_freeze(manifest),
        world_spec=spec,
        visual_asset_paths=MappingProxyType(asset_paths),
    )


def _load_visual_asset_paths(root: Path, spec: WorldSpec) -> dict[str, Path]:
    visual_spec = spec.visual_spec
    if visual_spec is None:
        return {}
    asset_paths: dict[str, Path] = {}
    total_bytes = 0
    declared_resolved_paths: set[Path] = set()
    for asset in visual_spec.visual_assets.values():
        relative_parts = asset.file_name.split("/")
        candidate = root.joinpath(*relative_parts)
        current = root
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise ContentPackValidationError(
                    "symbolic links are not allowed for visual assets",
                    file="visuals.json",
                    json_path=f"$.visual_assets[{asset.asset_key}].file_name",
                )
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ContentPackValidationError(
                "declared visual asset does not exist",
                file="visuals.json",
                json_path=f"$.visual_assets[{asset.asset_key}].file_name",
            ) from exc
        if root not in resolved.parents or not resolved.is_file():
            raise ContentPackValidationError(
                "visual asset resolves outside the pack or is not a regular file",
                file="visuals.json",
                json_path=f"$.visual_assets[{asset.asset_key}].file_name",
            )
        data = resolved.read_bytes()
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
        total_bytes += checked.size_bytes
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ContentPackValidationError(
                f"visual assets exceed {MAX_TOTAL_IMAGE_BYTES} total bytes",
                file="visuals.json",
                json_path="$.visual_assets",
            )
        asset_paths[asset.asset_key] = resolved
        declared_resolved_paths.add(resolved)

    assets_root = root / "assets"
    if assets_root.exists():
        if assets_root.is_symlink() or not assets_root.is_dir():
            raise ContentPackValidationError(
                "assets must be a regular directory",
                file="visuals.json",
                json_path="$.visual_assets",
            )
        for candidate in assets_root.iterdir():
            if candidate.is_symlink() or not candidate.is_file():
                raise ContentPackValidationError(
                    "assets directory cannot contain links or nested directories",
                    file="visuals.json",
                    json_path="$.visual_assets",
                )
            if candidate.resolve(strict=True) not in declared_resolved_paths:
                raise ContentPackValidationError(
                    f"undeclared asset file {candidate.name!r}",
                    file="visuals.json",
                    json_path="$.visual_assets",
                )
    return asset_paths


def load_builtin_content_pack(directory_name: str) -> LoadedContentPack:
    if not _BUILTIN_DIRECTORY_RE.fullmatch(directory_name):
        raise ContentPackValidationError(
            "built-in pack directory must use lowercase letters, digits, and underscores",
            file="manifest.json",
            json_path="$",
        )
    return load_content_pack(BUILTIN_PACKS_ROOT / directory_name)


def load_all_builtin_content_packs() -> tuple[LoadedContentPack, ...]:
    """Discover trusted installed packs without hard-coding pack names."""

    loaded: list[LoadedContentPack] = []
    seen_content_versions: set[str] = set()
    for candidate in sorted(BUILTIN_PACKS_ROOT.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or not _BUILTIN_DIRECTORY_RE.fullmatch(candidate.name):
            continue
        pack = load_content_pack(candidate)
        content_version = pack.world_spec.content_pack_version
        if content_version is None:
            raise ContentPackValidationError(
                "built-in content pack requires content_pack_version",
                file="manifest.json",
                json_path="$.content_pack_version",
            )
        if content_version in seen_content_versions:
            raise ContentPackValidationError(
                f"duplicate built-in content_pack_version {content_version!r}",
                file="manifest.json",
                json_path="$.content_pack_version",
            )
        seen_content_versions.add(content_version)
        loaded.append(pack)
    return tuple(loaded)


def read_builtin_visual_asset(
    world_version: str,
    asset_key: str,
) -> tuple[bytes, str, str]:
    """Resolve a validated asset by registry identity, never by a client path."""

    for pack in load_all_builtin_content_packs():
        if pack.world_spec.world_version != world_version:
            continue
        visual_spec = pack.world_spec.visual_spec
        if visual_spec is None or asset_key not in visual_spec.visual_assets:
            break
        path = pack.visual_asset_paths.get(asset_key)
        if path is None:
            break
        asset = visual_spec.visual_assets[asset_key]
        return path.read_bytes(), asset.mime_type, asset.sha256
    raise KeyError((world_version, asset_key))


def register_content_pack(pack_path: str | Path, *, default: bool = False) -> WorldSpec:
    """Load and register a pack; import lazily to avoid a registry cycle."""

    loaded = load_content_pack(pack_path)
    from world.registry import register_world_spec

    register_world_spec(loaded.world_spec, default=default)
    return loaded.world_spec
