"""Build an interaction opportunity matrix from content definitions."""
import argparse
import hashlib
import json
from pathlib import Path
from content.serializers import to_plain_data


def opportunity_matrix(spec):
    systems = to_plain_data(spec.systems)
    rows = []
    stages = {s["stage_recipe_id"]: s for s in systems.get("stage_recipes", [])}
    actions = {a["action_id"]: a for a in systems.get("action_definitions", [])}
    for recipe in systems.get("activity_recipes", []):
        definition = stages.get(recipe.get("conditions", {}).get("stage_recipe_id"))
        rows.append({"recipe_id": recipe["recipe_id"], "locations": recipe["location_ids"],
            "registered_actions": [{"action_id": aid, "minutes": actions[aid]["duration_minutes"]} for aid in recipe["action_ids"]],
            "roles": recipe.get("role_slots", []), "participation": recipe.get("conditions", {}).get("participant_mode", "optional"),
            "modalities": ["invitation_response", "actual_attendance", "early_leave", *(["suggestion", "role_confirmation", "actual_contribution", "closure"] if definition else [])],
            "stage_choice_counts": {s["stage_id"]: len(s["choices"]) for s in definition["stages"]} if definition else {},
            "followups": recipe.get("conditions", {}).get("followup_recipe_ids", []),
            "outcomes": definition["terminal_outcomes"] if definition else ["completed", "cancelled", "absence"],
            "measurement": "Record exposure before interpreting a response; labels are not personality scores."})
    content_hash = hashlib.sha256(json.dumps({"version": spec.content_pack_version, "systems": systems,
        "residents": to_plain_data(spec.residents)}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"audit_version": "content-opportunity-draft-v1", "status": "draft", "world_version": spec.world_version,
        "content_sha256": content_hash, "runtime_replay": False, "personality_mapping_frozen": False,
        "missing_reason_allowlist": ["not_exposed", "explicit_decline", "ignored", "location_closed", "actor_unavailable", "headcount", "technical_failure", "left_early"],
        "rows": rows, "free_exploration": {"dialogue": "opt_in", "solitude": "valid", "ignored_invitation_is_decline": False},
        "review_required": ["P0 content identity", "actual route exposure", "human role language ratings", "research evidence mapping and sufficiency", "owner acceptance"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true")
    args = parser.parse_args()
    if args.fixture:
        from testing.m8_fixture import register
        register()
    from world.registry import get_world_spec
    result = opportunity_matrix(get_world_spec(args.world))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Draft opportunity rows: {len(result['rows'])}; no model call or participant data")
