"""Pure queries and validation for a world's location graph."""

from collections import deque

from world.specs import LocationSpec, WorldSpec, WorldSpecValidationError


def get_location(spec: WorldSpec, location_id: str) -> LocationSpec:
    try:
        return spec.locations[location_id]
    except KeyError as exc:
        raise KeyError(f"Unknown location_id: {location_id}") from exc


def can_travel(spec: WorldSpec, source_id: str, target_id: str) -> bool:
    if source_id not in spec.locations or target_id not in spec.locations:
        return False
    return target_id in spec.locations[source_id].connected_location_ids


def shortest_travel_path(
    spec: WorldSpec,
    source_id: str,
    target_id: str,
) -> tuple[str, ...] | None:
    """Return a deterministic shortest graph path, including both endpoints.

    This query is intentionally separate from ``can_travel``. Resident movement
    uses ``can_travel`` to enforce one graph edge per simulation step, while a
    participant travel request may traverse every edge in this returned path in
    one action and pay time for each edge.
    """
    if source_id not in spec.locations or target_id not in spec.locations:
        return None
    if source_id == target_id:
        return (source_id,)

    queue: deque[tuple[str, ...]] = deque([(source_id,)])
    visited = {source_id}
    while queue:
        path = queue.popleft()
        current_id = path[-1]
        for neighbor_id in sorted(
            spec.locations[current_id].connected_location_ids,
        ):
            if neighbor_id in visited:
                continue
            next_path = (*path, neighbor_id)
            if neighbor_id == target_id:
                return next_path
            visited.add(neighbor_id)
            queue.append(next_path)
    return None


def object_exists(spec: WorldSpec, location_id: str, object_id: str) -> bool:
    if location_id not in spec.locations:
        return False
    return any(
        item.get("object_id") == object_id
        for item in spec.locations[location_id].interaction_points
    )


def validate_location_graph(spec: WorldSpec) -> None:
    if spec.start_location_id not in spec.locations:
        raise WorldSpecValidationError(
            f"Start location {spec.start_location_id!r} does not exist."
        )

    for location_key, location in spec.locations.items():
        if location_key != location.location_id:
            raise WorldSpecValidationError(
                f"Location key {location_key!r} does not match "
                f"location_id {location.location_id!r}."
            )
        if len(set(location.connected_location_ids)) != len(
            location.connected_location_ids
        ):
            raise WorldSpecValidationError(
                f"Location {location.location_id!r} has duplicate graph edges."
            )
        dangling = [
            target
            for target in location.connected_location_ids
            if target not in spec.locations
        ]
        if dangling:
            raise WorldSpecValidationError(
                f"Location {location.location_id!r} links to missing "
                f"location(s): {', '.join(sorted(dangling))}."
            )

        object_ids: list[str] = []
        for item in location.interaction_points:
            object_id = item.get("object_id")
            if not isinstance(object_id, str) or not object_id:
                raise WorldSpecValidationError(
                    f"Location {location.location_id!r} has an interaction "
                    "point without an object_id."
                )
            object_ids.append(object_id)
        if len(set(object_ids)) != len(object_ids):
            raise WorldSpecValidationError(
                f"Location {location.location_id!r} has duplicate object ids."
            )
