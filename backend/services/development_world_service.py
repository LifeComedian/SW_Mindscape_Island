"""Local-development world selection without participant-supplied paths."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, Request

from content.loader import load_all_builtin_content_packs
from content.serializers import content_pack_summary
from world.registry import get_world_spec


WORLD_SELECTOR_ENV_NAME = "WORLD_VERSION_SELECTOR_ENABLED"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def require_development_world_selector(request: Request) -> None:
    enabled = os.getenv(WORLD_SELECTOR_ENV_NAME, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    host = request.client.host.lower() if request.client else ""
    if not enabled or host not in _LOCAL_HOSTS:
        raise HTTPException(status_code=404, detail="Not found")


def development_world_options() -> dict[str, Any]:
    """Return validated installed JSON packs, never filesystem paths."""

    packs = load_all_builtin_content_packs()
    configured_default = (
        os.getenv("ISLAND_DEFAULT_WORLD_VERSION")
        or os.getenv("WORLD_DEFAULT_VERSION")
        or get_world_spec().world_version
    )
    return {
        "default_world_version": configured_default,
        "options": [
            {
                "directory_name": pack.root.name,
                **content_pack_summary(pack.world_spec),
            }
            for pack in packs
        ],
    }


def validate_development_world_selection(
    request: Request,
    requested_world_version: str | None,
) -> str | None:
    if requested_world_version is None:
        return None
    require_development_world_selector(request)
    allowed_versions = {
        pack.world_spec.world_version for pack in load_all_builtin_content_packs()
    }
    if requested_world_version not in allowed_versions:
        raise HTTPException(
            status_code=422,
            detail="Select an installed and validated content-pack world version.",
        )
    return requested_world_version
