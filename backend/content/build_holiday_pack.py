"""Compile and validate the Chinese holiday content pack."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from content.loader import load_content_pack
from world.interaction_policy import InteractionPolicy
from world.autonomy_policy import AutonomyPolicy

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT.parent / "outputs/seven-day-holiday-draft-v2"
VERSION = "chaoxi-holiday-v2"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def local(text):
    # Use Chinese text for missing translations.
    return {"en": text, "zh-CN": text}


def build(destination: Path, version: str = VERSION):
    VERSION = version
    people = read(SOURCE / "resident-content.json")
    places = read(SOURCE / "location-content.json")
    template = ROOT / "backend/content/templates/island_v07"
    manifest = read(template / "manifest.json")
    manifest.update(content_pack_version=VERSION + "-content", world_version=VERSION,
                    event_pack_version=VERSION + "-events", authoring_only=False, default_language="zh-CN",
                    start_location_id="loc_01")
    manifest["action_minutes"].update(move=5, approach=0)
    manifest["experience"]["rest_location_id"] = "loc_02"
    systems = read(template / "systems.json")
    systems["interaction_policy"] = asdict(InteractionPolicy())
    systems["autonomy_policy"] = asdict(AutonomyPolicy(enabled=True))
    systems["llm_policy"].update(enabled=True, timeout_ms=20000, max_calls_per_day=64, max_calls_per_session=448,
        max_units_per_day=524288, max_units_per_session=3670016, max_prompt_units=16384)
    coords = {"loc_01": [740, 220], "loc_02": [250, 190], "loc_03": [260, 450],
              "loc_04": [700, 450], "loc_05": [480, 320], "loc_06": [500, 560]}
    icons = ["harbor", "homes", "shop", "restaurant", "square", "restaurant"]
    locations = []
    for n, loc in enumerate(places["locations"]):
        objects = [o for o in places["objects"] if o["loc_id"] == loc["id"] and o["id"] != "obj_25"]
        locations.append({"location_id": loc["id"], "name": local(loc["name"]),
            "description": local(loc["atmosphere"]), "scene_type": icons[n], "version": VERSION,
            "connected_location_ids": [k for k in coords if k != "loc_05"] if loc["id"] == "loc_05" else ["loc_05"],
            "opening_hours": {"always_open": True},
            "interaction_points": [{"object_id": o["id"], "type": "notice_board" if o["id"] in ("obj_13", "obj_25", "obj_30") else "display", "name": local(o["name"]),
                "description": local(o["purpose"]), "renderer_key": "display"} for o in objects],
            "allowed_actions": ["move", "observe", "approach", "wait", "end_day", "end_conversation", "event_action"],
            "event_pool_ids": []})
    residents = []
    for person in people["residents"]:
        aid = int(person["id"].split("_")[1])
        relationships = []
        for rel in people["relationships"]:
            if person["id"] in (rel["a"], rel["b"]):
                other = rel["b"] if person["id"] == rel["a"] else rel["a"]
                name = next(p["name"] for p in people["residents"] if p["id"] == other)
                relationships.append(f"与{name}的初始关系：{rel['type']}。{rel['background']} 自己的看法：{rel['a_view'] if person['id'] == rel['a'] else rel['b_view']}")
        schedule = [{"state_id": f"resident_{aid}_day", "start_minute": 540, "end_minute": 1079,
            "location_id": person["home_base"], "activity": local(person["daily_rhythm"][0]), "goal": local(person["near_term_wish"])},
            {"state_id": f"resident_{aid}_evening", "start_minute": 1080, "end_minute": 1200,
             "location_id": person["home_base"], "activity": local("下班后的自由时间"), "goal": local("按自己的兴趣安排休息，也尊重来访者的选择")},
            {"state_id": f"resident_{aid}_welcome", "start_minute": 1095, "end_minute": 1185,
             "location_id": "loc_05", "days": [1], "activity": local("在公共广场附近自由活动"),
             "goal": local("自行决定是否参与当晚聚会；到场不等于参加了合作环节")},
            {"state_id": f"resident_{aid}_bonfire_walk", "start_minute": 1090, "end_minute": 1099,
             "location_id": "loc_05", "days": [7], "activity": local("经广场前往海边"), "goal": local("为出行留出时间")},
            {"state_id": f"resident_{aid}_bonfire", "start_minute": 1100, "end_minute": 1185,
             "location_id": "loc_01", "days": [7], "activity": local("在海边自由活动"),
             "goal": local("自行决定是否参与篝火小聚")},
            {"state_id": f"resident_{aid}_return", "start_minute": 1186, "end_minute": 1190,
             "location_id": "loc_05", "days": [7], "activity": local("经过广场返回休息"), "goal": local("慢慢结束假期") }]
        residents.append({"agent_id": aid, "name": person["name"], "adult_age_range": str(person["age"]),
            "role": local(person["role"]), "public_summary": local(person["experience_tag"]),
            "home_location_id": person["home_base"], "background": local(person["background"]),
            "personality": local(person["strengths"] + person["endearing_flaws"]),
            "values": [local(person["values"])], "preferences": [local(i) for i in person["interests"]],
            "communication_style": local(person["communication_style"]), "goals": [local(person["near_term_wish"])],
            "knowledge_boundaries": [local("初始关系是背景，不是本次游戏已经发生的活动；不知晓其他人的私聊。"), *map(local, relationships)],
            "avoid_patterns": [local(person["boundaries"])], "safety_rules": [local("不作心理诊断；玩家拒绝或退出时尊重决定。被问及时说明自己是 AI 角色。")],
            "avatar_key": "resident_default", "marker_color_key": ["resident_teal", "resident_blue", "resident_amber", "resident_rose", "resident_violet"][(aid-1)%5],
            "profile_version": VERSION + f"-resident-{aid}", "prompt_version": "world-role-prompt-v4",
            "autonomy": {"enabled": False, "allowed_intents": ["idle"],
                "free_time_state_ids": [b["state_id"] for b in schedule if not (aid == 5 and b["state_id"].endswith("_day"))]},
            "schedule": schedule})
    actions = {a["id"]: a for a in places["actions"]}
    actions["act_48"]["choices"][0] = "决定查看留言（请打开公告板，阅读回执另行记录）"
    object_locations = {o["id"]: o["loc_id"] for o in places["objects"]}
    source_mapping = {}
    for action in actions.values():
        variants = []
        if action["kind"] == "ui_read":
            source_mapping[action["id"]] = []  
            continue
        for index, choice in enumerate(action["choices"]):
            action_id = f"{action['id']}_choice_{index+1}"
            variants.append(action_id)
            collaborative = bool(action["npc_ids"]) or action["kind"] == "staged_activity"
            note_input = "private_note" if action["id"] in ("act_16", "act_45") else "public_note" if action["id"] == "act_22" or action["id"] == "act_48" and index == 1 else None
            inputs = [{"input_id": note_input, "value_type": "free_text", "required": True, "max_length": 500}] if note_input else []
            if note_input == "public_note":
                inputs.append({"input_id": "publish", "value_type": "boolean", "required": True})
            systems["action_definitions"].append({"action_id": action_id, "label": local(action["name"] + "：" + choice),
                "actor_types": ["participant"] if action["id"] in ("act_16", "act_22", "act_45", "act_48") else ["participant", "resident"],
                "target_types": ["object"], "location_scope": "co_located", "execution_mode": "execute",
                "min_participants": 2 if collaborative else 1, "max_participants": 20,
                "duration_minutes": 0 if collaborative else action["minutes"],
                "inputs": inputs, "preconditions": {"requires_stage": True} if collaborative else {},
                "text_record": note_input,
                "consequences": [] if note_input == "private_note" else [{"effect_type": "set_object_state", "state_key": action["id"], "value": ("选择稍后查看真实留言，请打开公告板；尚未计为阅读" if action["id"] == "act_48" and index == 0 else choice)}],
                "effect_allowlist": ["set_object_state"], "permission_keys": [], "capability_keys": [],
                "interruptible": True, "failure_reason_codes": []})
            systems["affordances"].append({"affordance_id": action_id + "_here", "action_id": action_id,
                "location_ids": [object_locations[action["obj_id"]]], "object_ids": [action["obj_id"]],
                "enabled": True, "conditions": {}, "permission_keys": [], "capability_keys": []})
        source_mapping[action["id"]] = variants
    # Unbundled cooperative actions use the same one-card activity contract.
    covered = {step["action_id"] for a in places["activities"] for step in a["steps"]}
    activities = deepcopy(places["activities"])
    for a in actions.values():
        if a["id"] not in covered and (a["npc_ids"] or a["kind"] == "staged_activity"):
            activities.append({"id": a["id"] + "_activity", "name": a["name"], "loc_id": object_locations[a["obj_id"]],
                "npc_ids": a["npc_ids"], "minutes": a["minutes"], "requires_partner": True,
                "steps": [{"action_id": a["id"], "minutes": a["minutes"]}]})
    # These are authored invitations, never a promise that another actor already consented.
    for activity in activities:
        ids = [step["action_id"] for step in activity["steps"]]
        all_actions = [v for source_id in ids for v in source_mapping[source_id]]
        cards = []
        for index, step in enumerate(activity["steps"]):
            a = actions[step["action_id"]]
            next_id = f"step_{index+2}" if index+1 < len(activity["steps"]) else None
            cards.append({"stage_id": f"step_{index+1}", "label": local(a["name"]), "kind": "action",
                "confirm_in_place": True,
                "role_goals": {"organizer": "尊重选择，确认自己愿意参与的部分", "guest": "选择自己的做法；可以随时离开"},
                "authority_roles": ["organizer", "guest"], "authority_actor_types": ["participant"], "duration_minutes": step["minutes"],
                "timeout_outcome": "timed_out", "absence_outcome": "not_completed", "enter_conditions": {},
                "choices": [{"choice_id": f"choice_{j+1}", "label": local(choice),
                    "action_id": source_mapping[a["id"]][j], "object_id": a["obj_id"], "inputs": {"private_note": "明信片模板：" + choice} if a["id"] == "act_45" else {},
                    "runtime_input_ids": ["public_note", "publish"] if a["id"] == "act_48" and j == 1 else [],
                    "next_stage_id": next_id, "outcome": "completed" if next_id is None else None}
                    for j, choice in enumerate(a["choices"])]})
        stage_id = activity["id"] + "_stages"
        systems["stage_recipes"].append({"stage_recipe_id": stage_id, "label": local(activity["name"]),
            "allowed_action_ids": all_actions, "terminal_outcomes": ["completed", "timed_out", "not_completed"],
            "max_stages": 3, "max_player_choices_per_stage": 4, "initial_stage_id": "step_1", "stages": cards})
        systems["activity_recipes"].append({"recipe_id": activity["id"], "label": local(activity["name"]),
            "location_ids": [activity["loc_id"]], "object_ids": list(dict.fromkeys(actions[i]["obj_id"] for i in ids)),
            "action_ids": all_actions, "role_slots": ["organizer", "guest"], "variant_recipe_ids": [],
            "min_participants": 2 if activity["npc_ids"] or activity.get("requires_partner") else 1, "max_participants": 2 if activity["npc_ids"] or activity.get("requires_partner") else 1, "duration_minutes": activity["minutes"],
            "complexity": "coordinated", "player_facing": True,
            "conditions": {"participant_mode": "required", "organizer_agent_ids": [int(i.split('_')[1]) for i in activity["npc_ids"]],
                "required_resident_ids": [int(i.split('_')[1]) for i in activity["npc_ids"]],
                "invitee_role_ids": ["guest"], "stage_recipe_id": stage_id, "participant_stage_control": True,
                "auto_emergence": bool(activity["npc_ids"]), "emergence_enabled": bool(activity["npc_ids"]),
                "start_delay_minutes": 15, "expires_after_minutes": 30}})
    # Dates constrain invitations; they do not imply attendance.
    parties = [
        ("welcome", 1, "loc_05", "欢迎派对", [
            ("找个舒服的位置", ["点心桌边", "看看花与木托盘", "了解六个地点", "坐在外侧旁观"]),
            ("选择今晚的小活动", ["为点心选一个预制名称", "选择桌花配色", "拼出小岛的一角", "安静休息"]),
            ("给明天留点期待", ["记下想去的地点", "看看当前可参加的活动", "向在场居民道别", "安静离场"])]),
        ("bonfire", 7, "loc_01", "篝火晚会", [
            ("选一个海边位置", ["在交谈区坐下", "看看热饮桌", "看看纪念桌", "安静看海"]),
            ("留下今晚的片段", ["查看实际共同经历", "选择海边主题卡", "选择与一人分享的意向", "安静陪伴"]),
            ("慢慢说再见", ["留一句预制道别", "保存自己的主题选择", "看看实际活动记录", "继续安静坐一会儿"])])]
    for key, day, lid, name, phases in parties:
        oid = key + "_table"
        loc = next(l for l in locations if l["location_id"] == lid)
        loc["interaction_points"].append({"object_id": oid, "type": "table", "name": local(name + "专用桌"),
            "description": local("大家为聚会准备的小桌子。活动开始后，可以从任务中参与桌边的小活动，也可以和在场居民聊聊。"), "renderer_key": "table"})
        cards, aids = [], []
        for index, (title, choices) in enumerate(phases):
            next_id = f"phase_{index+2}" if index < 2 else None
            options = []
            for j, label in enumerate(choices):
                aid = f"{key}_{index+1}_{j+1}"
                aids.append(aid)
                definition = deepcopy(systems["action_definitions"][0])
                definition.update(action_id=aid, label=local(label), actor_types=["participant"], duration_minutes=0,
                    preconditions={"requires_stage": True}, consequences=[{"effect_type": "set_object_state", "state_key": f"phase_{index+1}_choice", "value": label}])
                systems["action_definitions"].append(definition)
                systems["affordances"].append({"affordance_id": aid + "_here", "action_id": aid, "location_ids": [lid], "object_ids": [oid], "enabled": True, "conditions": {}, "permission_keys": [], "capability_keys": []})
                options.append({"choice_id": f"choice_{j+1}", "label": local(label), "action_id": aid, "object_id": oid,
                    "inputs": {}, "next_stage_id": next_id, "outcome": None if next_id else "completed"})
            cards.append({"stage_id": f"phase_{index+1}", "label": local(title), "kind": "action", "confirm_in_place": True,
                "role_goals": {"organizer": "让每个人自由选择", "guest": "决定自己怎样参与"}, "authority_roles": ["guest"],
                "duration_minutes": [15,30,15][index], "timeout_outcome": "timed_out", "absence_outcome": "not_completed", "enter_conditions": {}, "choices": options})
        systems["stage_recipes"].append({"stage_recipe_id": key + "_stages", "label": local(name), "allowed_action_ids": aids,
            "terminal_outcomes": ["completed", "partial", "timed_out", "not_completed"], "max_stages": 3, "max_player_choices_per_stage": 4,
            "initial_stage_id": "phase_1", "stages": cards})
        systems["activity_recipes"].append({"recipe_id": key, "label": local(name), "location_ids": [lid], "object_ids": [oid],
            "action_ids": aids, "role_slots": ["organizer", "guest"], "variant_recipe_ids": [], "min_participants": 1, "max_participants": 9,
            "duration_minutes": 60, "complexity": "major", "player_facing": True,
            "conditions": {"participant_mode": "optional", "organizer_agent_ids": [7], "invite_all_residents": True,
                "invitee_role_ids": ["guest"], "fixed_day": day, "fixed_start_minute": 1110,
                "open_admission_until_end": True, "fixed_stage_timeline": True,
                "stage_recipe_id": key + "_stages", "auto_emergence": True, "expires_after_minutes": 240}})
    from content.holiday_microcontent import enrich
    enrich(systems)
    from content.holiday_experience import enrich_feedback, add_homes
    enrich_feedback(systems, places)
    add_homes(locations, coords, icons, manifest, residents, systems)
    if VERSION in ("chaoxi-holiday-v3", "chaoxi-holiday-v4", "chaoxi-holiday-v5", "chaoxi-holiday-v6"):
        from content.holiday_v3 import enrich as enrich_v3
        enrich_v3(systems, locations, residents, places)
    if VERSION in ("chaoxi-holiday-v4", "chaoxi-holiday-v5", "chaoxi-holiday-v6"):
        from content.holiday_v4 import enrich as enrich_v4
        enrich_v4(systems, locations, residents, manifest)
        source_mapping = {o['object_id']: [a['action_id'] for a in systems['action_definitions'] if a['action_id'].startswith('v4_'+o['object_id']+'__')]
                          for loc in locations for o in loc['interaction_points']}
    if VERSION in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        from content.holiday_v5 import enrich as enrich_v5
        enrich_v5(systems, locations, residents, manifest)
    if VERSION == 'chaoxi-holiday-v6':
        from content.holiday_v6 import enrich as enrich_v6
        enrich_v6(systems, locations, residents, manifest)
        source_mapping = {o['object_id']: [a['action_id'] for a in systems['action_definitions'] if a['action_id'].startswith('v4_'+o['object_id']+'__')]
                          for loc in locations for o in loc['interaction_points']}
    from content.experience_next import enrich as enrich_next
    enrich_next(systems, locations, residents, manifest)
    source_mapping = {o['object_id']: [a['action_id'] for a in systems['action_definitions'] if a['action_id'].startswith('v4_'+o['object_id']+'__')]
                      for loc in locations for o in loc['interaction_points']}
    base_map = read(ROOT / "backend/content/packs/island_v06/map.json")
    base_map.update(map_id="chaoxi_map", version=VERSION + "-map", paths=[], location_nodes=[], scene_layouts=[])
    for index, loc in enumerate(locations):
        lid = loc["location_id"]
        x, y = coords[lid]
        if lid != "loc_05":
            target = "loc_02" if lid == "guest_room" else "loc_05"
            base_map["paths"].append({"path_id": lid + "_path", "from_location_id": lid, "to_location_id": target, "points": [[x,y],coords[target]]})
        base_map["location_nodes"].append({"location_id": lid, "x": x, "y": y, "click_radius": 30, "icon_key": icons[index], "label_offset": [0,40]})
        base_map["scene_layouts"].append({"location_id": lid, "width": 800, "height": 450,
            "participant_spawn": [80,380], "resident_slots": [[160+i*75,280+(i%2)*40] for i in range(8)],
            "interaction_point_positions": {o["object_id"]: [90+i*120,120] for i,o in enumerate(loc["interaction_points"])}})
    if VERSION in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        from content.holiday_art import apply_layout
        apply_layout(base_map)
    slots = [{"slot_id": "map.image", "slot_type": "map_image", "target_id": "chaoxi_map"}]
    for actor in ["participant", *[f"resident:{r['agent_id']}" for r in residents]]:
        for kind in ("map_thumbnail", "dialogue_portrait"):
            slots.append({"slot_id": f"actors.{actor}.{kind}", "slot_type": "actor_" + kind, "target_id": actor})
    for loc in locations:
        for kind in ("map_thumbnail", "scene_image"):
            slots.append({"slot_id": f"locations.{loc['location_id']}.{kind}", "slot_type": "location_" + kind, "target_id": loc["location_id"]})
    for slot in slots:
        slot.update(asset_key=None, fallback_palette_key="ocean_teal", fallback_title=local("潮栖岛"), fallback_description=local("七日假期"))
    documents = {"manifest.json": manifest, "locations.json": {"locations": locations}, "residents.json": {"residents": residents},
        "map.json": base_map, "events.json": {"events": []}, "systems.json": systems,
        "visuals.json": {"visual_version": VERSION + "-visuals", "visual_assets": [], "visual_slots": slots}}
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in documents.items():
        (destination/name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = load_content_pack(destination)
    print(json.dumps({"world": loaded.world_spec.world_version, "residents": len(residents), "locations": len(locations),
        "objects": sum(len(l["interaction_points"]) for l in locations), "source_actions": len(source_mapping), "choice_actions": len(systems["action_definitions"]), "activities": len(systems['activity_recipes'])}, ensure_ascii=False))
    (destination / "source-mapping.json").write_text(json.dumps({"actions": source_mapping, "relationships": people["relationships"],
        "source_status": "accepted_by_user_20261010" if VERSION == 'chaoxi-holiday-v4' else "accepted_by_user_20261007", "implementation_status": "runtime_validation_in_progress"}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    build(ROOT / "backend/content/staging/chaoxi_holiday_v2")
