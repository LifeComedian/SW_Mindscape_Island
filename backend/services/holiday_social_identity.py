from agents.output_safety import guarded_generate, ModelStop
"""Bind every holiday phone reply to the same resident used in the world."""
from models import WorldState
from dataclasses import replace
from world.registry import get_world_spec
from services.role_context_service import build_role_context
from services.world_memory_service import build_agent_memory_context


def note_grounding_reasons(text, source):
    """Small, explicit guard for errors observed in the style trial.

Not a semantic fact checker. On rejection the original sourced post is kept;
never rewrite another time or invent a nicer replacement.
"""
    import re
    reasons=[]
    # Keep result text unchanged when a rewrite could reverse the winner.
    if re.search(r'赢|输了|输掉|没输|没赢|胜出|获胜|打败|先出完|[0-9一二三四五六七八九十]+分',text):
        reasons.append('game_result_requires_original_post')
    for pattern in (r'昨天|前天|上次|刚从',r'这里没人|这儿没人|挺空的|人很少|人很多'):
        for match in re.findall(pattern,text):
            if match not in source:reasons.append('unsupported_time_or_scene')
    return list(dict.fromkeys(reasons))


def bind_request(db, request):
    world = db.query(WorldState).filter_by(session_id=request.session_id).first()
    if not world or not world.world_version.startswith('chaoxi-holiday-'):
        return request
    spec = get_world_spec(world.world_version)
    context = build_role_context(db, world=world, spec=spec, agent_id=request.agent_id,
        language=request.language, scene_kind='social_comment')
    memory = build_agent_memory_context(db, session_id=request.session_id, owner_agent_id=request.agent_id,
        current_day=world.current_day, current_time_minutes=world.current_time_minutes, location_id=world.participant_location_id,
        include_private=spec.world_version not in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'))
    # The role prompt treats the post and thread as quotations, not world facts.
    return replace(request, world_role_context=context, agent_memory=memory,
        recent_history=[*request.recent_history, *request.thread_history][-12:],
        user_comment=f'帖子原文：{request.post_content}\n当前要回应的话：{request.user_comment}')


def publish_daily_note(db, world, spec):
    from models import UserPost, CharacterState
    from services.simulation_service import USER_POST_ID_OFFSET
    from data.island import localized
    from services.plan_service import _json_dumps
    # Allow two posts per day, grounded in the resident's location.
    slot = 0 if world.current_time_minutes < 780 else 1
    key = f'holiday-daily:{world.current_day}:{slot}'
    if db.query(UserPost.id).filter_by(session_id=world.session_id,idempotency_key=key).first():
        return
    aid = ((world.current_day-1)*2+slot) % len(spec.residents)+1
    from content.experience_next import enabled,active,VISITORS
    if enabled():
        present=[i for i in spec.residents if active(i,world.current_day)]
        arrivals=[i for i,(first,last) in VISITORS.items() if first==world.current_day]
        aid=arrivals[0] if arrivals and slot==0 else present[((world.current_day-1)*2+slot)%len(present)]
    row = db.query(CharacterState).filter_by(session_id=world.session_id,agent_id=aid).first()
    if not row:
        return
    place = localized(spec.locations[row.current_location_id].name,'zh-CN')
    preferences = spec.residents[aid].profile.get('preferences', ())
    interest = localized(preferences[0],'zh-CN') if preferences else '到处逛逛'
    content = {
        1: f'在{place}。有空想聊聊{interest}。',
        2: f'今天想聊聊{interest}，有兴趣可以来找我。我现在在{place}。',
        3: f'现在在{place}。谁也喜欢{interest}？有空聊两句。',
        4: f'我在{place}。今天想抽空聊聊{interest}。',
        5: f'在{place}。想找同好聊聊{interest}。',
        6: f'现在在{place}。有空的话，想聊聊{interest}。',
        7: f'对{interest}感兴趣的话，可以找我聊聊。我现在在{place}。',
        8: f'今天想聊聊{interest}。我在{place}。',
    }.get(aid, f'现在在{place}，想聊聊{interest}。')
    if enabled() and aid in VISITORS:
        content={9:f'我叫宋以宁，来岛上住两天。现在在{place}，这次行程没有排得太满。',10:f'我是程越，平时忙会展项目。这两天在岛上歇歇，今天先在{place}看看。',11:f'我是唐沐，在科学馆做展教。这两天来岛上走走，现在在{place}。'}[aid]
    post=UserPost(feed_post_id=0,session_id=world.session_id,day=world.current_day,author_alias=spec.residents[aid].name,
        content=content,language='zh-CN',simulated_time=f'{world.current_time_minutes//60:02d}:{world.current_time_minutes%60:02d}',
        world_time_minutes=world.current_time_minutes,author_type='resident',author_agent_id=aid,post_type='holiday_note',visibility='island_public',
        source_type='resident_daily_note',location_id=row.current_location_id,idempotency_key=key,
        facts_json=_json_dumps({'author_location':row.current_location_id,'intent_only':True}))
    db.add(post); db.flush();post.feed_post_id=USER_POST_ID_OFFSET+post.id
    ensure_note_provenance(db,post)


async def naturalize_note(db, world, spec, agent_id):
    """One bounded background rewrite of an actor's own public, grounded note."""
    from models import UserPost
    from config import settings
    from agents.base import AgentRequest
    from agents.role_prompt import build_role_messages
    from agents.llm_transport import ChatTransport
    from services.world_service import session_write_lock, world_has_ended
    import json
    if spec.world_version not in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') or settings.agent_mode != 'llm':
        return False
    sid=world.session_id
    with session_write_lock(sid):
        db.rollback()
        row=next((p for p in db.query(UserPost).filter(UserPost.session_id==sid,UserPost.author_agent_id==agent_id,
            UserPost.source_type.in_(('resident_daily_note','activity_experience'))).order_by(UserPost.id.desc())
            if not json.loads(p.facts_json or '{}').get('narrative_status') and not json.loads(p.facts_json or '{}').get('journal_version')),None)
        if not row:
            return False
        identity=bind_request(db,AgentRequest(session_id=sid,agent_id=agent_id,post_id=0,post_content=row.content,
            user_comment='把上面自己的见闻写成一条日常动态，1到2句。只谈已经提供的事实和自己的感想，不增加新人物、天气或事件，不引用玩家的话。',language='zh-CN'))
        messages=build_role_messages(identity)
        messages[0]['content']+='\n此处是在发布自己的生活动态，不是回复或安慰玩家。只输出动态正文。只保留一件值得说的事，不强行升华或以提问收尾；原文有实际共同参与才提玩家，不能把意向写成已发生。'
        row_id=row.id; source_text=row.content; facts=json.loads(row.facts_json or '{}');facts['narrative_status']='pending';row.facts_json=json.dumps(facts,ensure_ascii=False)
        db.commit();db.rollback()
    grounding_reasons=[]
    try:
        text=(await guarded_generate(ChatTransport(), messages,max_output_tokens=160,retry=False,purpose='background')).strip()[:400]
        status='generated' if text else 'fallback'
        grounding_reasons=note_grounding_reasons(text,source_text)
        if grounding_reasons:text='';status='factual_fallback'
    except ModelStop as exc:
        text='';status='safety_blocked' if exc.safety else 'technical_failure'
    except Exception:
        text='';status='technical_failure'
    with session_write_lock(sid):
        db.rollback();row=db.get(UserPost,row_id); world=db.query(WorldState).filter_by(session_id=sid).one()
        if row and not world_has_ended(world):
            if text:row.content=text
            facts=json.loads(row.facts_json or '{}');facts['narrative_status']=status
            facts['narrative_guard_reasons']=grounding_reasons
            row.facts_json=json.dumps(facts,ensure_ascii=False);db.commit()
    return True


def ensure_note_provenance(db,post):
    """Backfill old server-authored public notes without inventing events."""
    from models import WorldKnowledgeFact
    import json
    if post.post_type!='holiday_note' or post.author_type!='resident' or post.visibility!='island_public' or post.source_type not in ('resident_daily_note','activity_experience'):
        return None
    fact=db.query(WorldKnowledgeFact).filter_by(session_id=post.session_id,source_type='phone_post',source_id=post.id).first()
    if fact:return fact
    source=json.loads(post.facts_json or '{}')
    payload={k:source[k] for k in ('author_location','intent_only','author_attended','runtime_id') if k in source}
    fact=WorldKnowledgeFact(session_id=post.session_id,fact_key=f'holiday-note:{post.id}',fact_type='resident_note',
        subject_type='user_post',subject_id=post.id,visibility='island_public',source_type='phone_post',source_id=post.id,
        payload_json=json.dumps(payload,ensure_ascii=False),world_day=post.day,world_time_minutes=post.world_time_minutes)
    db.add(fact);db.flush();return fact
