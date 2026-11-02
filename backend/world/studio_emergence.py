"""Read-only simulation of authored emergence rules."""
from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
import hashlib
import json
from typing import Any

from world.atomic_actions import (
    AtomicActionRegistry, AtomicActionRuntimeError, AtomicActorSnapshot,
    AtomicActionTarget, AtomicRuntimeContext,
)

VERSION = "studio-emergence-projection-v1"
MAX_CANDIDATES = 20000


def rule_graph(draft: dict) -> dict:
    nodes, edges = [], []
    def node(kind, ident, file, path):
        key = f"{kind}:{ident}"
        nodes.append(dict(id=key, kind=kind, label=str(ident), file=file, json_path=path))
        return key
    def refs(source, kind, values, relation, file, path):
        for i, value in enumerate(values):
            edges.append(dict(source=source, target=f"{kind}:{value}", relation=relation,
                              file=file, json_path=f"{path}[{i}]"))
    for i, loc in enumerate(draft["locations"]["locations"]):
        path = f"$.locations[{i}]"
        key = node("location", loc["location_id"], "locations.json", path)
        refs(key, "location", loc["connected_location_ids"], "route", "locations.json", path + ".connected_location_ids")
        for j, obj in enumerate(loc["interaction_points"]):
            obj_key = node("object", obj["object_id"], "locations.json", path + f".interaction_points[{j}]")
            refs(obj_key, "location", [loc["location_id"]], "at", "locations.json", path)
    for i, actor in enumerate(draft["residents"]["residents"]):
        key = node("actor", actor["agent_id"], "residents.json", f"$.residents[{i}]")
        for j, block in enumerate(actor["schedule"]):
            schedule = node("schedule", f"{actor['agent_id']}/{block['state_id']}", "residents.json", f"$.residents[{i}].schedule[{j}]")
            refs(key, "schedule", [f"{actor['agent_id']}/{block['state_id']}"], "schedule", "residents.json", f"$.residents[{i}].schedule")
            refs(schedule, "location", [block["location_id"]], "at", "residents.json", f"$.residents[{i}].schedule[{j}].location_id")
    systems = draft.get("systems", {})
    for i, arc in enumerate(systems.get("narrative_arcs", [])):
        path = f"$.narrative_arcs[{i}]"
        arc_key = node("arc", arc["arc_id"], "systems.json", path)
        for j, story_node in enumerate(arc["nodes"]):
            ident = f"{arc['arc_id']}/{story_node['node_id']}"
            story_key = node("narrative", ident, "systems.json", path + f".nodes[{j}]")
            refs(arc_key, "narrative", [ident], "organizes", "systems.json", path)
            refs(story_key, "recipe", [story_node["recipe_id"]], "normal_recipe", "systems.json", path)
            refs(story_key, "narrative", [f"{arc['arc_id']}/{r}" for r in story_node["requires_nodes"]], "known_followup", "systems.json", path)
    for group, kind, field in (("action_definitions", "action", "action_id"), ("affordances", "affordance", "affordance_id"), ("activity_recipes", "recipe", "recipe_id"), ("stage_recipes", "stage", "stage_recipe_id")):
        for i, item in enumerate(systems.get(group, [])):
            path = f"$.{group}[{i}]"
            key = node(kind, item[field], "systems.json", path)
            for target_kind, ref_field in (("location", "location_ids"), ("object", "object_ids"), ("action", "action_ids"), ("action", "allowed_action_ids"), ("recipe", "variant_recipe_ids")):
                refs(key, target_kind, item.get(ref_field, []), ref_field, "systems.json", path + "." + ref_field)
            if "action_id" in item:
                refs(key, "action", [item["action_id"]], "verb", "systems.json", path + ".action_id")
            for j, effect in enumerate(item.get("consequences", [])):
                effect_key = node("effect", f"{item[field]}/{j}", "systems.json", path + f".consequences[{j}]")
                refs(key, "effect", [f"{item[field]}/{j}"], "effect_allowlist", "systems.json", path)
            for role in item.get("role_slots", []):
                node("role", f"{item[field]}/{role}", "systems.json", path + ".role_slots")
                refs(key, "role", [f"{item[field]}/{role}"], "role", "systems.json", path + ".role_slots")
            for outcome in item.get("terminal_outcomes", []):
                node("outcome", f"{item[field]}/{outcome}", "systems.json", path + ".terminal_outcomes")
                refs(key, "outcome", [f"{item[field]}/{outcome}"], "terminal", "systems.json", path)
            conditions = item.get("conditions", {})
            if conditions.get("stage_recipe_id"):
                refs(key, "stage", [conditions["stage_recipe_id"]], "stages", "systems.json", path + ".conditions.stage_recipe_id")
            refs(key, "recipe", conditions.get("followup_recipe_ids", []), "followup", "systems.json", path + ".conditions.followup_recipe_ids")
            refs(key, "actor", conditions.get("organizer_agent_ids", []), "organizer", "systems.json", path + ".conditions.organizer_agent_ids")
            if kind == "recipe":
                for policy in ("emergence_policy", "plan_policy", "knowledge_policy", "candidate_policy"):
                    if policy in systems:
                        refs(key, "policy", [policy], "governed_by", "systems.json", path)
                social = node("invitation", item[field], "systems.json", path + ".conditions")
                refs(social, "recipe", [item[field]], "same_plan", "systems.json", path)
            for j, card in enumerate(item.get("stages", [])):
                card_id = f"{item[field]}/{card['stage_id']}"
                card_key = node("card", card_id, "systems.json", path + f".stages[{j}]")
                refs(key, "card", [card_id], "contains", "systems.json", path)
                for k, choice in enumerate(card["choices"]):
                    cp = path + f".stages[{j}].choices[{k}]"
                    if choice.get("next_stage_id"):
                        refs(card_key, "card", [f"{item[field]}/{choice['next_stage_id']}"], choice["choice_id"], "systems.json", cp)
                    if choice.get("outcome"):
                        refs(card_key, "outcome", [f"{item[field]}/{choice['outcome']}"], choice["choice_id"], "systems.json", cp)
                    for ck, target_kind in (("action_id", "action"), ("object_id", "object")):
                        if choice.get(ck):
                            refs(card_key, target_kind, [choice[ck]], ck, "systems.json", cp + "." + ck)
    for policy in ("emergence_policy", "plan_policy", "knowledge_policy", "candidate_policy", "llm_policy", "interaction_policy", "autonomy_policy"):
        if policy in systems:
            node("policy", policy, "systems.json", f"$.{policy}")
    if "llm_policy" in systems:
        for actor in draft["residents"]["residents"]:
            refs(f"actor:{actor['agent_id']}", "policy", ["llm_policy"], "legal_candidates_only", "systems.json", "$.llm_policy")
    for i, event in enumerate(draft["events"]["events"]):
        key = node("event", event["event_id"], "events.json", f"$.events[{i}]")
        refs(key, "location", event["location_ids"], "at", "events.json", f"$.events[{i}].location_ids")
        for j, card in enumerate(event.get("stages", [])):
            cid = f"{event['event_id']}/{card['stage_id']}"
            node("flow", cid, "events.json", f"$.events[{i}].stages[{j}]")
            refs(key, "flow", [cid], "contains", "events.json", f"$.events[{i}].stages")
            for k, choice in enumerate(card.get("actions", [])):
                for effect in choice.get("effects", []):
                    if effect["type"] == "goto_node":
                        refs(f"flow:{cid}", "flow", [f"{event['event_id']}/{effect['node_id']}"], choice["action_id"], "events.json", f"$.events[{i}].stages[{j}].actions[{k}]")
                    elif effect["type"] in ("start_event", "schedule_event"):
                        refs(f"flow:{cid}", "event", [effect["event_id"]], effect["type"], "events.json", f"$.events[{i}].stages[{j}].actions[{k}]")
        for j, publication in enumerate(event.get("social_publications", [])):
            social = node("social", publication["publication_id"], "events.json", f"$.events[{i}].social_publications[{j}]")
            refs(social, "event", [event["event_id"]], "provenance", "events.json", f"$.events[{i}]")
    known = {n["id"] for n in nodes}
    return dict(nodes=nodes, edges=[dict(e, missing=e["target"] not in known) for e in edges])


def _distance(locations, source, target):
    queue = deque([(source, 0)])
    seen = {source}
    while queue:
        current, distance = queue.popleft()
        if current == target:
            return distance
        for neighbor in locations[current].connected_location_ids:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, distance + 1))
    return None


def project_seven_days(spec, *, seed: int, response: str, public_consent: bool) -> dict:
    """Use validated immutable content and shared atomic authorization only."""
    systems = spec.systems
    registry = AtomicActionRegistry(systems)
    policy = systems["emergence_policy"]
    candidate_policy = systems["candidate_policy"]
    recipes = list(systems["activity_recipes"])
    actors = sorted(spec.residents)
    stages = {s["stage_recipe_id"]: s for s in systems["stage_recipes"]}
    actions = {a["action_id"]: a for a in systems["action_definitions"]}
    findings, rows, facts = [], [], []
    objects, flags = {}, {}
    inspected = 0
    def finding(code, path, detail, severity="warning", file="systems.json"):
        item = dict(code=code, severity=severity, file=file, json_path=path, detail=detail)
        if item not in findings:
            findings.append(item)
    # Structural relationship checks complement the authoritative schema validator.
    for index, recipe in enumerate(recipes):
        path = f"$.activity_recipes[{index}]"
        mode = recipe.get("conditions", {}).get("participant_mode", "optional")
        if recipe["min_participants"] > len(actors) + (mode != "exclude"):
            finding("impossible_headcount", path + ".min_participants", "居民与允许参加的玩家总数不足，人数永远无法成立。", "error")
        for loc in recipe["location_ids"]:
            if not any(_distance(spec.locations, r.home_location_id, loc) is not None for r in spec.residents.values()):
                finding("route_unreachable", path + ".location_ids", "没有居民能从住所到达活动地点。", "error")
        if recipe.get("conditions", {}).get("project_to_board") and not recipe.get("player_facing", True):
            finding("privacy_visibility", path + ".conditions.project_to_board", "私密活动请求公告板投影；请审阅可见性与实际查看边界。")
    follows = {r["recipe_id"]: list(r.get("conditions", {}).get("followup_recipe_ids", [])) for r in recipes}
    checked = set()
    def visit(node, stack):
        if len(stack) > 64:
            finding("followup_chain_bound", "$.activity_recipes", "后续链超过创作检查深度，运行时仍受有限链深预算限制。", "error")
            return
        if node in stack:
            finding("followup_cycle", "$.activity_recipes", "后续活动存在循环；运行时链深上限仍会阻止无限增长。")
            return
        if node in checked:
            return
        checked.add(node)
        for nxt in follows.get(node, []):
            visit(nxt, stack | {node})
    for recipe_id in follows:
        visit(recipe_id, set())
    if spec.calendar.total_days < 7:
        finding("calendar_short", "$.calendar.total_days", "七日模拟要求至少七天的日历。", "error", "manifest.json")
        return dict(days=[], findings=findings, complete=False, facts=[])
    def complete_plan(p, day):
        if p.get("unattended"):
            return  # Expiry releases proposed reservations, without attendance.
        for obj, effect in p["effects"]:
            if effect["effect_type"] == "set_object_state": objects.setdefault(obj, {})[effect["state_key"]] = effect["value"]
            elif effect["effect_type"] == "set_world_flag": flags[effect["flag_id"]] = effect["value"]
        facts.append(dict(day=day, minute=p["end"], recipe_id=p["recipe_id"], chain_depth=p["chain_depth"], source_type="experienced", witnesses=p["members"], visibility="island_public" if public_consent else "private", public_requires_all_witness_consent=True))
    for day in range(1, 8):
        counts = Counter()
        active = []
        declined = {}
        used = dict(player_facing=0, major=0, invitations=0)
        day_rows = []
        for minute in range(spec.calendar.day_start_minute, spec.calendar.day_end_minute, 30):
            for plan in active:
                if plan.get("release", plan["end"]) <= minute:
                    complete_plan(plan, day)
            active = [p for p in active if p.get("release", p["end"]) > minute]
            candidates = []
            for index, recipe in enumerate(recipes):
                c = recipe.get("conditions", {})
                if not c.get("emergence_enabled", True):
                    continue
                predecessors = [f for f in facts if f["day"] < day and recipe["recipe_id"] in follows.get(f["recipe_id"], [])]
                if c.get("followup_only", False) and not predecessors:
                    continue
                start = minute + c.get("start_delay_minutes", 30)
                end = start + recipe["duration_minutes"]
                if end > spec.calendar.day_end_minute:
                    continue
                mode = c.get("participant_mode", "optional")
                attempts = []
                for owner in c.get("organizer_agent_ids", actors):
                    for loc in recipe["location_ids"]:
                        reason, members = "candidate_valid", [owner]
                        chain_depth = 0
                        if c.get("followup_only", False):
                            known = next((f for f in reversed(predecessors) if owner in f["witnesses"]), None)
                            if known is None:
                                reason = "outcome_not_known"
                            else:
                                chain_depth = known["chain_depth"] + 1
                                if chain_depth > policy["max_event_chain_depth"]: reason = "chain_depth_limit"
                        direct = mode == "required" or (mode == "optional" and recipe["min_participants"] > len(actors))
                        if direct:
                            members.append("participant")
                        needed = max(0, recipe["min_participants"] - len(members))
                        available = []
                        for aid in [owner] + [a for a in actors if a != owner]:
                            resident = spec.residents[aid]
                            block = next((b for b in resident.schedule if (b.days is None or day in b.days) and b.start_minute <= minute <= b.end_minute), None)
                            distance = _distance(spec.locations, block.location_id if block else resident.home_location_id, loc)
                            free = next((b for b in resident.schedule if (b.days is None or day in b.days) and b.state_id in resident.autonomy.free_time_state_ids and b.start_minute <= start and end - 1 <= b.end_minute), None)
                            if distance is None:
                                if aid == owner: reason = "route_unreachable"
                                continue
                            if distance * spec.action_minutes.get("move", 15) > start - minute:
                                if aid == owner: reason = "travel_time"
                                continue
                            if not free:
                                if aid == owner: reason = "fixed_schedule"
                                continue
                            fixed = next((b for b in resident.schedule if (b.days is None or day in b.days) and b.state_id not in resident.autonomy.free_time_state_ids and b.start_minute >= end), None)
                            if fixed:
                                back = _distance(spec.locations, loc, fixed.location_id)
                                if back is None or end + back * spec.action_minutes.get("move", 15) > fixed.start_minute:
                                    if aid == owner: reason = "travel_time"
                                    continue
                            if any(aid in p["members"] and p["start"] < end and p["end"] > start for p in active):
                                if aid == owner: reason = "actor_overlap"
                                continue
                            available.append(aid)
                        members.extend([a for a in available if a != owner][:needed])
                        if len(members) < recipe["min_participants"] or len(members) > recipe["max_participants"]:
                            reason = "participant_bounds_unsatisfied"
                        if any(p["start"] < end and p["end"] > start and (p["loc"] == loc or set(p["objects"]) & set(recipe.get("object_ids", []))) for p in active):
                            reason = "resource_conflict"
                        source_types = {"activity_recipe", "actor_goal"}
                        if any(a["enabled"] and a["action_id"] in recipe["action_ids"] and loc in a["location_ids"] for a in systems["affordances"]): source_types.add("affordance")
                        if chain_depth: source_types.add("world_outcome")
                        if not source_types <= set(candidate_policy["allowed_source_types"]): reason = "candidate_source_not_allowed"
                        if recipe["complexity"] not in candidate_policy["allowed_complexities"]: reason = "candidate_complexity_not_allowed"
                        # Match the director's aggregate permission checks, even
                        # when the stage later chooses only one action branch.
                        for aid in recipe["action_ids"]:
                            definition = actions[aid]
                            matching = [a for a in systems["affordances"] if a["enabled"] and a["action_id"] == aid and loc in a["location_ids"]]
                            if "resident" not in definition["actor_types"] or definition.get("permission_keys") or any(a.get("permission_keys") for a in matching):
                                reason = "permission_denied"
                            elif definition.get("capability_keys") or any(a.get("capability_keys") for a in matching):
                                reason = "capability_missing"
                            for condition in [definition.get("preconditions", {})] + [a.get("conditions", {}) for a in matching]:
                                if any(value is not None for value in condition.get("actor_state_equals", {}).values()): reason = "actor_unavailable"
                                for obj in recipe.get("object_ids", []):
                                    if any(objects.get(obj, {}).get(k) != v for k, v in condition.get("object_state_equals", {}).items()): reason = "target_unavailable"
                        effects = []
                        stage = stages.get(c.get("stage_recipe_id"))
                        selected_choices = []
                        if reason == "candidate_valid":
                            try:
                                trial_objects = deepcopy(objects)
                                if stage:
                                    card_id = stage["initial_stage_id"]
                                    selected_id = None
                                    role_actors = {"organizer": [owner]}
                                    for role, member in zip(c.get("invitee_role_ids", []), members[1:]):
                                        role_actors.setdefault(role, []).append(member)
                                    while card_id:
                                        card = next(s for s in stage["stages"] if s["stage_id"] == card_id)
                                        authorities = [member for role in card["authority_roles"] for member in role_actors.get(role, [])]
                                        if not authorities:
                                            raise AtomicActionRuntimeError("No occupied authority role", reason_code="permission_denied")
                                        stage_actor = authorities[0]
                                        for obj_key, value in card.get("enter_conditions", {}).get("object_state", {}).items():
                                            if not all(trial_objects.get(obj, {}).get(obj_key) == value for obj in recipe.get("object_ids", [])):
                                                raise AtomicActionRuntimeError("Stage predicate", reason_code="target_unavailable")
                                        choice = next((ch for ch in card["choices"] if ch["choice_id"] == selected_id), card["choices"][0])
                                        selected_choices.append(choice["choice_id"])
                                        if card["kind"] == "decision": selected_id = choice["choice_id"]
                                        if card["kind"] == "action":
                                            if actions[choice["action_id"]]["duration_minutes"] > card["duration_minutes"]:
                                                raise AtomicActionRuntimeError("Stage window", reason_code="actor_unavailable")
                                            prepared = registry.prepare(action_id=choice["action_id"], actor=AtomicActorSnapshot("participant" if stage_actor == "participant" else "resident", None if stage_actor == "participant" else stage_actor, loc), target=AtomicActionTarget(location_id=loc, object_id=choice["object_id"]), context=AtomicRuntimeContext(0, True, len(members), frozenset(o["object_id"] for o in spec.locations[loc].interaction_points), participant_present="participant" in members, object_states=trial_objects), inputs=dict(choice["inputs"]))
                                            effects.extend((choice["object_id"], dict(e)) for e in prepared.effects)
                                            for effect in prepared.effects:
                                                if effect["effect_type"] == "set_object_state": trial_objects.setdefault(choice["object_id"], {})[effect["state_key"]] = effect["value"]
                                        card_id = choice["next_stage_id"]
                                else:
                                    for action_id in recipe["action_ids"]:
                                        definition = actions[action_id]
                                        target = next((o for o in recipe.get("object_ids", []) if any(a["action_id"] == action_id and o in a["object_ids"] for a in systems["affordances"])), None)
                                        if "object" in definition["target_types"]:
                                            prepared = registry.prepare(action_id=action_id, actor=AtomicActorSnapshot("resident", owner, loc), target=AtomicActionTarget(location_id=loc, object_id=target), context=AtomicRuntimeContext(0, True, len(members), frozenset(o["object_id"] for o in spec.locations[loc].interaction_points), object_states=trial_objects), inputs={})
                                            effects.extend((target, dict(e)) for e in prepared.effects)
                                        elif definition.get("permission_keys") or definition.get("capability_keys") or "resident" not in definition["actor_types"]:
                                            reason = "permission_denied"
                            except AtomicActionRuntimeError as exc:
                                reason = exc.reason_code
                        attempt = dict(recipe=recipe, index=index, owner=owner, loc=loc, start=start, end=end, members=members, direct=direct, effects=effects, choices=selected_choices, reason=reason, chain_depth=chain_depth)
                        attempts.append(attempt)
                        if reason == "candidate_valid": break
                    if attempts and attempts[-1]["reason"] == "candidate_valid": break
                if attempts:
                    candidates.append(attempts[-1])
            candidates.sort(key=lambda p: (counts[p["recipe"]["recipe_id"]], int(hashlib.sha256(f"{seed}:{day}:{minute}:{p['recipe']['recipe_id']}".encode()).hexdigest()[:8], 16)))
            selected = 0
            for candidate in candidates[:candidate_policy["max_candidates_per_evaluation"]]:
                inspected += 1
                if inspected > MAX_CANDIDATES:
                    return dict(days=rows, findings=findings + [dict(code="projection_limit", severity="error", file="systems.json", json_path="$", detail="模拟达到 20000 候选上限，结果不完整。")], complete=False, facts=facts)
                p = candidate
                r = p["recipe"]
                reason = p["reason"]
                # Earlier selections in this same evaluation may reserve actors
                # or resources; do not rely on the pre-ranking availability.
                if reason == "candidate_valid" and any(plan["start"] < p["end"] and plan["end"] > p["start"] and (set(plan["members"]) & set(p["members"]) or plan["loc"] == p["loc"] or set(plan["objects"]) & set(r.get("object_ids", []))) for plan in active):
                    reason = "resource_conflict"
                if reason == "candidate_valid" and any(sum(member in plan["members"] for plan in active) >= policy["max_open_commitments_per_actor"] for member in p["members"]):
                    reason = "open_commitment_limit"
                if reason == "candidate_valid":
                    tests = [(selected >= policy["max_activity_creations_per_tick"], "activity_creation_tick_limit"), (selected >= policy["max_invitations_per_tick"], "invitation_tick_limit"), (counts[r["recipe_id"]] >= policy["same_recipe_daily_limit"], "same_recipe_daily_limit"), (r.get("complexity") == "major" and used["major"] >= policy["max_new_major_events_per_day"], "major_daily_limit"), (r.get("player_facing", True) and used["player_facing"] >= policy["max_new_player_facing_events_per_day"], "player_facing_daily_limit"), (r.get("player_facing", True) and sum(p["facing"] for p in active) >= policy["max_concurrent_player_facing_events"], "player_facing_concurrent_limit"), (p["direct"] and used["invitations"] >= policy["max_direct_agent_invitations_to_player_per_day"], "direct_invitation_daily_limit"), (minute < declined.get(p["owner"], -1), "declined_pair_cooldown"), (policy["max_open_commitments_per_actor"] == 0, "open_commitment_limit")]
                    reason = next((code for condition, code in tests if condition), reason)
                if reason == "candidate_valid":
                    selected += 1
                    counts[r["recipe_id"]] += 1
                    used["player_facing"] += bool(r.get("player_facing", True))
                    used["major"] += r.get("complexity") == "major"
                    used["invitations"] += p["direct"]
                    if p["direct"] and response != "accept":
                        reason = "invitation_rejected" if response == "reject" else "invitation_expired"
                        if response == "reject":
                            declined[p["owner"]] = minute + policy["declined_pair_cooldown_minutes"]
                        else:
                            active.append(dict(start=p["start"], end=p["end"], release=min(p["start"], minute + r.get("conditions", {}).get("expires_after_minutes", 30)), loc=p["loc"], members=p["members"], objects=list(r.get("object_ids", [])), facing=r.get("player_facing", True), unattended=True))
                    else:
                        reason = "assumed_attendance_and_confirmation"
                        active.append(dict(start=p["start"], end=p["end"], loc=p["loc"], members=p["members"], objects=list(r.get("object_ids", [])), facing=r.get("player_facing", True), effects=p["effects"], recipe_id=r["recipe_id"], chain_depth=p["chain_depth"]))
                day_rows.append(dict(minute=minute, recipe_id=r["recipe_id"], location_id=p["loc"], organizer_id=p["owner"], reason_code=reason, json_path=f"$.activity_recipes[{p['index']}]", assumed_members=p["members"], choices=p["choices"] if reason == "assumed_attendance_and_confirmation" else []))
        for plan in active:
            complete_plan(plan, day)
        rows.append(dict(day=day, new_player_facing_events=used["player_facing"], major_events=used["major"], direct_invitations=used["invitations"], candidates=day_rows))
    for index, recipe in enumerate(recipes):
        relevant = [c for row in rows for c in row["candidates"] if c["recipe_id"] == recipe["recipe_id"]]
        if relevant and not any(c["reason_code"] == "assumed_attendance_and_confirmation" for c in relevant):
            reasons = ", ".join(sorted({c["reason_code"] for c in relevant}))
            finding("never_completed", f"$.activity_recipes[{index}]", "七日假设下没有完成；原因：" + reasons)
    return dict(days=rows, findings=findings, complete=True, facts=facts, object_states=objects, world_flags=flags)


def finish_result(result: dict) -> dict:
    result["projection_version"] = VERSION
    result["result_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return result
