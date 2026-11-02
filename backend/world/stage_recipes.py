"""Activity stage definitions and validation."""

from __future__ import annotations

from collections.abc import Mapping
import re

from world.specs import WorldSpecValidationError


def validate_stage_cards(definition: Mapping, systems: Mapping) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise WorldSpecValidationError(message)

    def keys(item, required, optional=()):
        require(isinstance(item, Mapping), "Stage card must be an object.")
        require(set(required) <= set(item) <= set(required) | set(optional), "Unknown or missing stage-card field.")

    def identifier(value):
        require(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)), "Invalid stage identifier.")

    def integer(value, minimum, maximum):
        require(type(value) is int and minimum <= value <= maximum, "Invalid stage time or bound.")

    def predicate(value):
        require(isinstance(value, Mapping) and set(value) <= {"object_state"}, "Unknown stage enter condition.")
        states = value.get("object_state", {})
        require(isinstance(states, Mapping), "Object predicates must be an object.")
        for key, val in states.items():
            identifier(key)
            require(type(val) in (str, bool, int), "Stage predicates require scalar values.")

    cards = definition.get("stages", ())
    if not cards:
        require("initial_stage_id" not in definition and "stages" not in definition, "Executable stages cannot be empty.")
        return  # Accept older bounds-only declarations.
    keys(definition, {"stage_recipe_id", "label", "allowed_action_ids", "terminal_outcomes", "max_stages", "max_player_choices_per_stage", "stages", "initial_stage_id"})
    integer(definition["max_stages"], 1, 3)
    integer(definition["max_player_choices_per_stage"], 1, 4)
    require(isinstance(cards, (list, tuple)) and 1 <= len(cards) <= min(3, definition["max_stages"]), "Stage sequence exceeds its bound.")
    actions = {item["action_id"]: item for item in systems.get("action_definitions", ())}
    ids = [item.get("stage_id") for item in cards if isinstance(item, Mapping)]
    for stage_id in ids:
        identifier(stage_id)
    require(len(ids) == len(cards) and len(set(ids)) == len(ids), "Duplicate or invalid stage IDs.")
    require(definition["initial_stage_id"] == ids[0], "Initial stage must be the first card.")
    edges = {}
    for card in cards:
        keys(card, {"stage_id", "label", "kind", "role_goals", "authority_roles", "duration_minutes", "timeout_outcome", "absence_outcome", "enter_conditions", "choices"}, {"confirm_in_place", "authority_actor_types"})
        if "authority_actor_types" in card:
            require(isinstance(card["authority_actor_types"], (list, tuple)) and bool(card["authority_actor_types"]) and set(card["authority_actor_types"]) <= {"participant", "resident"}, "Invalid stage authority actor types.")
        if "confirm_in_place" in card:
            require(card["confirm_in_place"] is True and card["kind"] == "action", "In-place confirmation is only valid for action cards.")
        identifier(card["stage_id"])
        require(card["kind"] in ("decision", "action", "closure"), "Unknown stage kind.")
        integer(card["duration_minutes"], 1, 480)
        require(isinstance(card["label"], Mapping) and card["label"] and set(card["label"]) <= {"en", "zh-CN"} and all(isinstance(v, str) and 0 < len(v) <= 500 for v in card["label"].values()), "Invalid stage label.")
        goals = card["role_goals"]
        require(isinstance(goals, Mapping) and goals, "Stage requires role goals.")
        for role, goal in goals.items():
            identifier(role)
            require(isinstance(goal, str) and 0 < len(goal) <= 500, "Invalid role goal.")
        roles = card["authority_roles"]
        require(isinstance(roles, (list, tuple)) and roles and len(set(roles)) == len(roles) and set(roles) <= set(goals), "Unknown stage authority role.")
        require(card["timeout_outcome"] in definition["terminal_outcomes"] and card["absence_outcome"] in definition["terminal_outcomes"], "Unknown timeout/absence outcome.")
        predicate(card["enter_conditions"])
        choices = card["choices"]
        require(isinstance(choices, (list, tuple)) and 1 <= len(choices) <= min(4, definition["max_player_choices_per_stage"]), "Stage choice bound exceeded.")
        for choice in choices:
            require(isinstance(choice, Mapping), "Stage choice must be an object.")
            identifier(choice.get("choice_id"))
        require(len({c["choice_id"] for c in choices}) == len(choices), "Duplicate stage choice IDs.")
        targets = []
        for choice in choices:
            keys(choice, {"choice_id", "label", "action_id", "object_id", "inputs", "next_stage_id", "outcome"}, {"runtime_input_ids"})
            identifier(choice["choice_id"])
            require(isinstance(choice["label"], Mapping) and choice["label"] and set(choice["label"]) <= {"en", "zh-CN"} and all(isinstance(v, str) and 0 < len(v) <= 500 for v in choice["label"].values()), "Invalid choice label.")
            require(isinstance(choice["inputs"], Mapping), "Choice inputs must be structured.")
            target, outcome = choice["next_stage_id"], choice["outcome"]
            require(bool(target) != bool(outcome), "A choice needs exactly one next stage or terminal outcome.")
            if target:
                require(target in ids, "Unknown next stage.")
                targets.append(target)
                if card["kind"] == "decision":
                    target_card = next(c for c in cards if c["stage_id"] == target)
                    if target_card["kind"] == "action":
                        require(any(c["choice_id"] == choice["choice_id"] for c in target_card["choices"]), "Decision has no matching action choice.")
            if outcome:
                require(outcome in definition["terminal_outcomes"], "Unknown terminal outcome.")
            if card["kind"] == "action":
                require(choice["action_id"] in definition["allowed_action_ids"] and choice["action_id"] in actions, "Unknown stage action.")
                require(actions[choice["action_id"]].get("execution_mode", "execute") == "execute", "A stage execution cannot use a text proposal.")
                inputs = {i["input_id"]: i for i in actions[choice["action_id"]].get("inputs", ())}
                runtime_inputs = choice.get("runtime_input_ids", ())
                require(isinstance(runtime_inputs, (list, tuple)) and len(set(runtime_inputs)) == len(runtime_inputs) and set(runtime_inputs) <= set(inputs) and not set(runtime_inputs) & set(choice["inputs"]), "Invalid runtime stage inputs.")
                require(set(choice["inputs"]) <= set(inputs) and all(i.get("required") is not True or key in choice["inputs"] or key in runtime_inputs for key, i in inputs.items()), "Unknown or missing stage action input.")
                require(choice["object_id"] is not None and any(a.get("enabled") is True and a["action_id"] == choice["action_id"] and choice["object_id"] in a.get("object_ids", ()) for a in systems.get("affordances", ())), "Stage action is not an existing object affordance.")
            else:
                require(choice["action_id"] is None and choice["object_id"] is None and not choice["inputs"], "Decision/closure cards cannot apply effects.")
        edges[card["stage_id"]] = targets
    require(cards[0]["kind"] == "decision" or cards[0].get("confirm_in_place") is True, "A staged activity must start with explicit confirmation.")
    visited = set()
    def walk(node, stack):
        require(node not in stack, "Stage cycles are forbidden.")
        visited.add(node)
        for target in edges[node]:
            walk(target, stack | {node})
    walk(ids[0], set())
    require(visited == set(ids), "Unreachable stage card.")
    for recipe in systems.get("activity_recipes", ()):
        if recipe.get("conditions", {}).get("stage_recipe_id") != definition["stage_recipe_id"]:
            continue
        recipes = {r["recipe_id"]: r for r in systems.get("activity_recipes", ())}
        require(all(recipes[v].get("conditions", {}).get("stage_recipe_id") == definition["stage_recipe_id"] for v in recipe.get("variant_recipe_ids", ()) if v in recipes), "Activity variants cannot replace the stage contract.")
        short_activity = recipe["duration_minutes"] <= 30 and recipe["max_participants"] <= 2 and all(c.get("confirm_in_place") is True for c in cards)
        require(len(cards) <= 1 or recipe["complexity"] == "major" or short_activity, "Multi-stage activities must consume the major-event budget.")
        require(sum(c["duration_minutes"] for c in cards) <= recipe["duration_minutes"], "Stage windows exceed the reserved activity duration.")
        for card in cards:
            require(set(card["role_goals"]) <= set(recipe.get("role_slots", ())) | {"organizer"}, "Stage role is not a recipe role.")
            for choice in card["choices"]:
                if choice["action_id"]:
                    require(choice["action_id"] in recipe["action_ids"] and choice["object_id"] in recipe["object_ids"], "Stage action/object is outside its activity recipe.")
                    require(any(a.get("enabled") is True and a["action_id"] == choice["action_id"] and choice["object_id"] in a.get("object_ids", ()) and set(recipe["location_ids"]) <= set(a.get("location_ids", ())) for a in systems.get("affordances", ())), "Stage affordance is unavailable at a recipe location.")
