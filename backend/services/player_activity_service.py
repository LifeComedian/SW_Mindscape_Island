"""Participant-created plans and invitations."""
from models import (WorldEmergenceEvaluation, WorldEmergenceCandidate,
                    WorldEmergentEventRuntime, WorldEventInstance)
from services import plan_service as plans


def attach_player_stage(db, *, world, spec, plan):
    recipe = plans._recipe(spec, plan.recipe_id)
    if plan.organizer_type != "participant" or not recipe.get("conditions", {}).get("participant_stage_control"):
        return
    if db.query(WorldEmergentEventRuntime.id).filter_by(commitment_id=plan.id).first():
        return
    origin = {"source": "participant_request", "commitment_id": plan.id}
    origin_hash = plans._request_hash(origin)
    evaluation = WorldEmergenceEvaluation(session_id=world.session_id,
        idempotency_key=f"participant-plan:{plan.id}", request_hash=origin_hash,
        source="participant_request", world_day=world.current_day, world_time_minutes=world.current_time_minutes,
        simulation_seed=0, policy_id="participant-choice", policy_version="v1",
        state_fingerprint=origin_hash, status="completed", candidate_count=1, selected_count=1,
        budget_json=plans._json_dumps({"origin": "participant_request", "autonomous_invitation": False}))
    db.add(evaluation)
    db.flush()
    candidate = WorldEmergenceCandidate(evaluation_id=evaluation.id, session_id=world.session_id,
        candidate_key=f"participant-plan:{plan.id}", recipe_id=plan.recipe_id, complexity=recipe["complexity"],
        player_facing=True, direct_participant_invite=False, organizer_actor_key="participant",
        location_id=plan.location_id, scheduled_day=plan.scheduled_day, scheduled_time_minutes=plan.scheduled_time_minutes,
        expires_day=plan.deadline_day, expires_time_minutes=plan.deadline_time_minutes,
        source_types_json=plans._json_dumps(["participant_request", "activity_recipe"]),
        source_facts_json=plans._json_dumps([origin]), outcome="selected", reason_code="participant_requested",
        selected_commitment_id=plan.id)
    db.add(candidate)
    db.flush()
    instance = WorldEventInstance(session_id=world.session_id, event_type="emergent_activity",
        event_version="participant-stage-v1", status="emergent_pending", location_id=plan.location_id,
        trigger_key=f"participant-stage:{plan.id}", started_day=world.current_day,
        started_time_minutes=world.current_time_minutes, metadata_json=plans._json_dumps(origin))
    db.add(instance)
    db.flush()
    candidate.selected_event_instance_id = instance.id
    db.add(WorldEmergentEventRuntime(session_id=world.session_id, candidate_id=candidate.id,
        event_instance_id=instance.id, commitment_id=plan.id, recipe_id=plan.recipe_id,
        complexity=recipe["complexity"], player_facing=True, direct_participant_invite=False,
        organizer_actor_key="participant", status=plan.status, chain_depth=0, fact_chain_id=str(plan.id),
        started_day=world.current_day, started_time_minutes=world.current_time_minutes,
        expires_day=plan.deadline_day, expires_time_minutes=plan.deadline_time_minutes,
        metadata_json=plans._json_dumps(origin)))


def catalog(db, *, session_id):
    world, spec = plans._world_and_spec(db, session_id)
    # Phone invitations can be prepared anywhere; plans validate travel and time.
    return {"activities": [
        {"recipe_id": r["recipe_id"], "label": dict(r["label"]), "object_ids": list(r["object_ids"]),
         "location_id": r["location_ids"][0], "duration_minutes": r["duration_minutes"],
         "min_participants": r['min_participants'], "max_participants": r['max_participants'],
         "required_resident_ids": list(r["conditions"].get("required_resident_ids", ())),
         "needs_partner": r["min_participants"] > 1}
        for r in spec.systems.get("activity_recipes", ())
        if r.get("conditions", {}).get("participant_stage_control")]}
