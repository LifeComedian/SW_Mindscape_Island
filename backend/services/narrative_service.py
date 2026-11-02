"""Narrative views of facts acquired by the acting resident."""
import json
from models import WorldKnowledgeFact, WorldActorKnowledge, WorldCommitment, WorldState, Session as UserSession
from services import plan_service as plans
from services.world_service import world_has_ended
from world.narrative_arcs import VERSION


def project_narratives(db, *, session_id, actor_type="participant", actor_agent_id=None):
    world = db.query(WorldState).filter_by(session_id=session_id).first()
    if world is None:
        from services.world_service import initialize_world
        world = initialize_world(db, db.query(UserSession).filter_by(id=session_id).one())
    from world.registry import get_world_spec
    spec = get_world_spec(world.world_version)
    if not spec.systems.get("narrative_arcs"):
        return {"projection_version": VERSION, "arcs": []}
    actor_key = plans._actor_key(actor_type, actor_agent_id)
    facts = db.query(WorldKnowledgeFact).join(WorldActorKnowledge, WorldActorKnowledge.fact_id == WorldKnowledgeFact.id).filter(
        WorldKnowledgeFact.session_id == session_id, WorldActorKnowledge.session_id == session_id,
        WorldActorKnowledge.actor_key == actor_key,
        WorldKnowledgeFact.fact_type.in_(("stage_action", "stage_outcome", "activity_record"))).order_by(WorldKnowledgeFact.id).all()
    known = {}
    for fact in facts:
        payload = json.loads(fact.payload_json)
        plan_id = payload.get("commitment_id", payload.get("plan_id"))
        plan = db.query(WorldCommitment).filter_by(id=plan_id, session_id=session_id).first() if type(plan_id) is int else None
        if not plan:
            continue
        entry = known.setdefault(plan.recipe_id, {"outcome": None, "fact_ids": [], "contributions": 0})
        entry["fact_ids"].append(fact.id)
        if fact.fact_type == "stage_action":
            entry["contributions"] += 1
        elif payload.get("outcome"):
            entry["outcome"] = payload["outcome"]
    arcs = []
    for arc in spec.systems.get("narrative_arcs", ()):
        nodes = []
        for node in arc["nodes"]:
            evidence = known.get(node["recipe_id"], {})
            outcome = evidence.get("outcome")
            state = "completed" if outcome == "completed" else "partial" if outcome else "contributed" if evidence.get("contributions") else "unresolved" if world_has_ended(world) else "unobserved"
            nodes.append({"node_id": node["node_id"], "recipe_id": node["recipe_id"], "status": state,
                "outcome": outcome, "label": dict(node["terminal_labels"].get(outcome, {})),
                "fact_ids": evidence.get("fact_ids", []), "contributions": evidence.get("contributions", 0)})
        status = "completed" if all(n["status"] == "completed" for n in nodes) else "partial" if any(n["status"] in ("partial", "completed", "contributed") for n in nodes) else "unresolved" if world_has_ended(world) else "unobserved"
        arcs.append({"arc_id": arc["arc_id"], "label": dict(arc["label"]), "status": status, "nodes": nodes})
    return {"projection_version": VERSION, "arcs": arcs}
