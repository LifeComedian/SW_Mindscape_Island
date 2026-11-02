"""A shared budget for resident greetings and unsolicited invitations."""
from models import WorldEmergentEventRuntime, WorldInteractionPrompt


def daily_contacts(db, world):
    greetings = db.query(WorldInteractionPrompt).filter_by(
        session_id=world.session_id, created_day=world.current_day).count()
    invitations = db.query(WorldEmergentEventRuntime).filter_by(
        session_id=world.session_id, started_day=world.current_day,
        direct_participant_invite=True).count()
    return greetings + invitations


def pending_fixed_recipes(db, world, spec):
    published = {r.recipe_id for r in db.query(WorldEmergentEventRuntime).filter_by(
        session_id=world.session_id, started_day=world.current_day).all()}
    return {r["recipe_id"] for r in spec.systems.get("activity_recipes", ())
            if r.get("conditions", {}).get("fixed_day") == world.current_day
            and r["conditions"].get("auto_emergence") is True
            and world.current_time_minutes <= r["conditions"].get("fixed_start_minute", -1)
            and r["recipe_id"] not in published}
