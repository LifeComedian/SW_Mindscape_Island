"""Build only the acting resident's authored identity and acquired facts."""
import json
from models import WorldActorKnowledge, WorldKnowledgeFact, WorldPlanMember, WorldCommitment, CharacterState
from agents.role_prompt import WorldRoleContext
from data.island import localized
from world.schedules import resolve_resident_schedule


def current_resident_activity(db, *, world, spec, agent_id, language):
    """Describe authored schedules or a real job/accepted activity, not free-text caches."""
    from services.scheduled_action_service import jobs
    from models import WorldAtomicActionExecution, WorldEmergentEventRuntime, WorldEventStage
    key = f"resident:{agent_id}"
    schedule = resolve_resident_schedule(spec, agent_id, world.current_day, world.current_time_minutes)
    for job in jobs(world):
        if job.get("actor_key") != key or job.get("status") != "pending":
            continue
        if job.get("kind") in ("travel", "routine_travel") and job.get("destination") in spec.locations:
            place = localized(spec.locations[job["destination"]].name, language)
            if job.get("kind") == "routine_travel":
                return (f"正在前往{place}", "根据自己的日程与兴趣出门") if language == "zh-CN" else (f"Travelling to {place}", "Follow my daily plans and interests")
            return (f"正在前往{place}", "按已经确认的安排赴约") if language == "zh-CN" else (f"Travelling to {place}", "Attend the confirmed arrangement")
        audit = db.query(WorldAtomicActionExecution).filter_by(id=job.get("audit_id"), session_id=world.session_id, actor_agent_id=agent_id, status="scheduled").first()
        definition = next((a for a in spec.systems.get("action_definitions", ()) if audit and a["action_id"] == audit.action_id), None)
        if definition:
            return localized(definition["label"], language), localized(schedule.goal, language)
    active = db.query(WorldCommitment, WorldPlanMember).join(WorldPlanMember, WorldPlanMember.commitment_id == WorldCommitment.id).filter(
        WorldCommitment.session_id == world.session_id, WorldCommitment.status == "in_progress", WorldPlanMember.actor_key == key,
        WorldPlanMember.response_status == "accepted", WorldPlanMember.attendance_status.in_(("present", "late"))).first()
    actor = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=agent_id).first()
    if active and actor and actor.current_location_id == active[0].location_id:
        plan, member = active
        recipe = next(r for r in spec.systems.get("activity_recipes", ()) if r["recipe_id"] == plan.recipe_id)
        runtime = db.query(WorldEmergentEventRuntime).filter_by(commitment_id=plan.id).first()
        stage = db.query(WorldEventStage).filter_by(runtime_id=runtime.id, status="active").first() if runtime else None
        definition = json.loads(stage.definition_json) if stage else {}
        card = next((c for c in definition.get("stages", ()) if c["stage_id"] == stage.current_stage_id), None)
        role = "organizer" if plan.organizer_type == "resident" and plan.organizer_agent_id == agent_id else member.role_id
        return localized(card["label"] if card else recipe["label"], language), str(card["role_goals"].get(role, "尊重每个人的选择")) if card else localized(schedule.goal, language)
    if actor and spec.world_version.startswith("chaoxi-holiday-") and actor.current_location_id != schedule.location_id:
        return ("在" + localized(spec.locations[actor.current_location_id].name, language) + "自由活动", localized(schedule.goal, language))
    return localized(schedule.activity, language), localized(schedule.goal, language)


def build_role_context(db, *, world, spec, agent_id, language, scene_kind="island_conversation"):
    resident = spec.residents[agent_id]
    actor_key = f"resident:{agent_id}"
    rows = db.query(WorldKnowledgeFact).join(WorldActorKnowledge,
        WorldActorKnowledge.fact_id == WorldKnowledgeFact.id).filter(
        WorldKnowledgeFact.session_id == world.session_id, WorldActorKnowledge.session_id == world.session_id,
        WorldActorKnowledge.actor_key == actor_key).order_by(WorldKnowledgeFact.id.desc()).limit(16).all()
    facts = []
    for row in rows:
        payload = json.loads(row.payload_json)
        data = {k: v for k, v in payload.items() if k in ("recipe_id", "plan_id", "outcome", "stage_id", "location_id", "actual_attendance_count") and isinstance(v, (str, int, bool))}
        if row.fact_type == "participant_self_report" and row.source_type == "phone_post":
            data["unverified_author_statement"] = str(payload.get("self_report", ""))[:500]
        if row.fact_type == "stage_action":
            from models import WorldAction
            source = db.query(WorldAction).filter_by(session_id=world.session_id, id=payload.get("source_action_id")).first()
            action_id = json.loads(source.metadata_json).get("atomic_action", {}).get("action_id") if source else None
            definition = next((a for a in spec.systems.get("action_definitions", ()) if a["action_id"] == action_id), None)
            if definition:
                data["performed_action"] = localized(definition["label"], language)
        facts.append({"fact_ref": f"knowledge:{row.id}", "type": row.fact_type, "source_type": row.source_type,
            "day": row.world_day, "minute": row.world_time_minutes,
            "data": data})
    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        profile = json.loads(world.state_json or '{}').get('holiday_v5', {}).get('profile', {})
        if profile:
            facts.append({'fact_ref': 'player:appearance', 'type': 'player_role_profile',
                          'data': {'role_gender': profile['gender'], 'address_rule': '只使用已选择的角色性别；不猜测未提供资料。'}})
    if spec.world_version == 'chaoxi-holiday-v6':
        from services.holiday_work_service import work_facts
        from services.holiday_work_review import visible_features
        works=work_facts(db,world,agent_id)
        facts=facts[-8:]+[{'fact_ref':w['work_id'],'type':'saved_work','source_type':'completed_atomic_action',
            'data':visible_features(w)}
            for w in works[-8:]]
        shared=json.loads(world.state_json or '{}').get('holiday_v6',{}).get('shared_experiences',{}).get(str(agent_id),[])
        facts += [{'fact_ref':f"activity:{m['runtime_id']}",'type':'shared_experience',
                   'source_type':'completed_shared_activity','day':m['day'],'data':m} for m in shared[-4:]]
        from services.dialogue_catalogue import catalogue_facts, map_facts, dining_facts
        facts=(facts+catalogue_facts(agent_id,spec.world_version,world)+map_facts(spec)+dining_facts(world,agent_id))[-16:]
    from content.experience_next import biography_facts, enabled as next_enabled, EVENT_OBJECTS, VISITORS
    facts += biography_facts(agent_id)
    if next_enabled() and agent_id in VISITORS:
        start,end=VISITORS[agent_id]
        elapsed=world.current_day-start
        facts.append({'fact_ref':f'visit:elapsed:{agent_id}','type':'authored_visit_status','data':{'description':('今天刚到岛上，这是到岛的第一天。不能说昨天到的。' if elapsed==0 else f'已经到岛{elapsed}天，今天是到岛第{elapsed+1}天。'),'arrival_day':start,'departure_after_day':end}})
    from services.experience_next_topics import topic_fact
    facts += topic_fact(db,world,agent_id)
    plans = db.query(WorldCommitment, WorldPlanMember).join(WorldPlanMember,
        WorldPlanMember.commitment_id == WorldCommitment.id).filter(
        WorldCommitment.session_id == world.session_id, WorldPlanMember.actor_key == actor_key,
        WorldPlanMember.response_status == "accepted", WorldCommitment.status.in_(("accepted", "in_progress"))).order_by(WorldCommitment.scheduled_day, WorldCommitment.scheduled_time_minutes).limit(8).all()
    commitments = tuple({"plan_id": p.id, "role": member.role_id, "status": p.status,
        "day": p.scheduled_day, "minute": p.scheduled_time_minutes, "location_id": p.location_id} for p, member in plans)
    schedule = resolve_resident_schedule(spec, agent_id, world.current_day, world.current_time_minutes)
    style = resident.profile.get("communication_style", {})
    style = localized(style, language) if hasattr(style, "get") else str(style)
    actor = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=agent_id).first()
    location_id = actor.current_location_id if actor else world.participant_location_id
    def authored_list(key):
        limit = 10 if key == "knowledge_boundaries" else 4
        return tuple((localized(item, language) if hasattr(item, "get") else str(item))[:400] for item in resident.profile.get(key, ())[:limit])
    activity, goal = current_resident_activity(db, world=world, spec=spec, agent_id=agent_id, language=language)
    personality = resident.profile.get("personality", {})
    return WorldRoleContext(actor_id=agent_id, name=resident.name, role=localized(resident.role, language),
        background=localized(resident.background, language), style=style or "自然、简洁，按职责说明具体情况。",
        scene_kind=scene_kind, location=localized(spec.locations[location_id].name, language),
        activity=activity[:400], goal=goal[:400],
        day=world.current_day, minute=world.current_time_minutes, known_facts=tuple(facts[-16:]), commitments=commitments,
        values=authored_list("values"), long_term_goals=authored_list("goals"),
        personality=localized(personality, language) if hasattr(personality, "get") else str(personality),
        preferences=authored_list("preferences"),
        boundaries=authored_list("knowledge_boundaries") + authored_list("avoid_patterns"),
        scene_objects=tuple(localized(point.get("name", {}), language) for point in spec.locations[location_id].interaction_points[:10] if not (next_enabled() and point.get('object_id') in EVENT_OBJECTS)),
        authored_activity_options=tuple(localized(recipe["label"], language) for recipe in spec.systems.get("activity_recipes", ())
            if location_id in recipe.get("location_ids", ()))[:6])
