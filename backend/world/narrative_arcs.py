"""Narrative definitions and fact projections."""
import re
from collections.abc import Mapping
from world.specs import WorldSpecValidationError

VERSION = "narrative-projection-v1"


def validate_arcs(value, systems):
    def fail(message):
        raise WorldSpecValidationError("Narrative arc: " + message)
    def identifier(value):
        return isinstance(value, str) and bool(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value))
    def label(value):
        return isinstance(value, Mapping) and set(value) == {"en", "zh-CN"} and all(isinstance(v, str) and 0 < len(v) <= 300 for v in value.values())
    if not isinstance(value, (list, tuple)) or len(value) > 4:
        fail("at most four arcs are supported")
    recipes = {r["recipe_id"]: r for r in systems["activity_recipes"]}
    stages = {s["stage_recipe_id"]: s for s in systems["stage_recipes"]}
    ids = set()
    for arc in value:
        if not isinstance(arc, Mapping) or set(arc) != {"arc_id", "version", "label", "nodes"} or not identifier(arc["arc_id"]) or arc["arc_id"] in ids or arc["version"] != VERSION or not label(arc["label"]):
            fail("invalid arc fields, version, label or duplicate ID")
        ids.add(arc["arc_id"])
        if not isinstance(arc["nodes"], (list, tuple)) or not 1 <= len(arc["nodes"]) <= 3:
            fail("each arc needs one to three nodes")
        nodes = {}
        for node in arc["nodes"]:
            if not isinstance(node, Mapping) or set(node) != {"node_id", "recipe_id", "requires_nodes", "terminal_labels"} or not identifier(node["node_id"]) or node["node_id"] in nodes or node["recipe_id"] not in recipes:
                fail("unknown recipe, invalid node or duplicate ID")
            requires = node["requires_nodes"]
            if not isinstance(requires, (list, tuple)) or len(set(requires)) != len(requires) or any(not identifier(r) for r in requires):
                fail("invalid prerequisite node references")
            recipe = recipes[node["recipe_id"]]
            definition = stages.get(recipe.get("conditions", {}).get("stage_recipe_id"))
            outcomes = set(definition["terminal_outcomes"]) if definition else {"completed"}
            terminals = node["terminal_labels"]
            if not isinstance(terminals, Mapping) or not terminals or set(terminals) - outcomes or any(not label(v) for v in terminals.values()):
                fail("terminal labels need registered outcomes")
            if definition and not any(c.get("action_id") for s in definition["stages"] for c in s["choices"]):
                fail("stage node has no registered action evidence")
            nodes[node["node_id"]] = node
        visiting, done = set(), set()
        def visit(node_id):
            if node_id in visiting:
                fail("cycles are not supported")
            if node_id in done:
                return
            if node_id not in nodes:
                fail("unknown prerequisite node")
            visiting.add(node_id)
            for source in nodes[node_id]["requires_nodes"]:
                visit(source)
                prior_recipe = recipes[nodes[source]["recipe_id"]]
                if nodes[node_id]["recipe_id"] not in prior_recipe.get("conditions", {}).get("followup_recipe_ids", ()):
                    fail("node dependency requires the normal recipe followup link")
            visiting.remove(node_id)
            done.add(node_id)
        for node_id in nodes:
            visit(node_id)
    return value
