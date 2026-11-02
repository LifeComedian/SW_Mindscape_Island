"""Optional orientation based on completed actions."""
import json
from models import WorldAction, WorldCommitment, WorldAtomicActionExecution, UserPost

def guides(db,sid,spec):
    rows=db.query(WorldAction).filter_by(session_id=sid,actor_type='participant').all()
    requests=[json.loads(r.metadata_json or '{}').get('request',{}) for r in rows if r.action_type=='opportunity_seen']
    seen={r.get('target') for r in requests if r.get('kind')=='guidebook'}
    preferences=[r for r in requests if r.get('kind')=='guide_preferences']
    skipped=bool(preferences and preferences[-1].get('target')=='skip')
    actions=db.query(WorldAtomicActionExecution).filter_by(session_id=sid,actor_type='participant',status='completed').all()
    plans=db.query(WorldCommitment).filter_by(session_id=sid,organizer_type='participant').all()
    done=[bool(seen),any(r.action_type=='conversation_message' for r in rows),bool(actions),
          any(p.status in ('completed','in_progress') for p in plans),
          any(x.action_id in ('v4_restaurant_menu__order','v4_cafe_menu__order') for x in actions),
          bool(db.query(UserPost.id).filter_by(session_id=sid,author_type='participant',post_type='personal').first()),
          any(r.action_type=='holiday_phone_open' for r in rows)]
    copy=[('book','从介绍册开始','打开床头的介绍册，看看地图和玩法。看过就可以出门。','guest_room'),
          ('talk','先认识一个人','到公共广场或咖啡馆，点击一位有空的人物，随便聊一句。','loc_05'),
          ('object','动手试一件小事','到花坊看看插花桌，或挑自己感兴趣的物品，完成一次真实操作。','loc_02'),
          ('invite','试着约人一起玩','在物品窗口点“邀请别人一起”，选人和可用时段；对方答应后，在半小时到场窗口进入活动。','loc_02'),
          ('order','点一次餐品或饮品','餐馆11:00开门。老板在场时，打开菜单选好餐品并确认点单，再点击桌位选择座位。也可以到咖啡馆点饮品。','loc_04'),
          ('post','把见闻发到动态里','打开手机的动态页，写几句话并发布；内容由你自己决定。',None),
          ('phone','看看岛上的动态','打开手机，看看大家分享的见闻，也可以留一句评论。',None)]
    entries=[dict(id=k,title=t,detail=d,location_id=l,progress=int(ok),total=1) for (k,t,d,l),ok in zip(copy,done)]
    return {'guides':[] if skipped else [e for e in entries if not e['progress']][:1],'exploration':entries,'optional':True,'version':'orientation-next-v1','skipped':skipped}
