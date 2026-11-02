"""Stable serialization helpers for immutable content specifications."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from world.specs import WorldSpec


def to_plain_data(value: Any) -> Any:
    """Return JSON-compatible copies without exposing mutable registry state."""

    if is_dataclass(value):
        return {
            item.name: to_plain_data(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, (Mapping, MappingProxyType)):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_plain_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [to_plain_data(item) for item in sorted(value)]
    if isinstance(value, Path):
        return str(value)
    return value


def world_spec_to_dict(spec: WorldSpec) -> dict[str, Any]:
    return to_plain_data(spec)


def world_spec_fingerprint(spec: WorldSpec) -> str:
    encoded = json.dumps(
        world_spec_to_dict(spec),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def content_pack_summary(spec: WorldSpec) -> dict[str, Any]:
    map_spec = spec.map_spec
    return {
        "content_pack_version": spec.content_pack_version,
        "world_version": spec.world_version,
        "event_pack_version": spec.event_pack_version,
        "map": (
            {
                "map_id": map_spec.map_id,
                "version": map_spec.version,
                "width": map_spec.width,
                "height": map_spec.height,
            }
            if map_spec is not None
            else None
        ),
        "location_count": len(spec.locations),
        "path_count": len(map_spec.paths) if map_spec is not None else 0,
        "resident_count": len(spec.residents),
        "schedule_block_count": sum(
            len(resident.schedule) for resident in spec.residents.values()
        ),
        "event_count": len(spec.event_specs),
        "visual_version": (
            spec.visual_spec.visual_version if spec.visual_spec is not None else None
        ),
        "visual_asset_count": (
            len(spec.visual_spec.visual_assets) if spec.visual_spec is not None else 0
        ),
        "visual_slot_count": (
            len(spec.visual_spec.visual_slots) if spec.visual_spec is not None else 0
        ),
        "fingerprint": world_spec_fingerprint(spec),
    }
