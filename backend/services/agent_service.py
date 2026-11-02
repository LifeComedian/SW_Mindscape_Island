from agents.personas import get_persona, list_agent_profiles
from data.timeline import get_timeline_post, posts, public_post


def get_static_agents() -> list[dict]:
    return list_agent_profiles()


def get_static_posts() -> list[dict]:
    return [public_post(post) for post in posts]


def get_static_post(post_id: int) -> dict | None:
    return get_timeline_post(post_id)


def get_static_agent(agent_id: int) -> dict | None:
    persona = get_persona(agent_id)
    if persona is None:
        return None
    return {
        "id": persona.agent_id,
        "name": persona.name,
        "role": persona.role,
        "personality": persona.persona,
        "avatar": persona.avatar,
        "communication_style": persona.communication_style,
        "prompt_version": persona.prompt_version,
    }
