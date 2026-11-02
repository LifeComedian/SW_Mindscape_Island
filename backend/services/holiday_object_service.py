"""Object commands executed within the atomic action transaction."""
import json
from copy import deepcopy
from dataclasses import replace
from content.holiday_v4 import CATALOGUE, VERSION, SEATS, action_id
from content.holiday_v6 import catalogue_for
from world.atomic_actions import AtomicActionRuntimeError


def fail(message):
    raise AtomicActionRuntimeError(message, reason_code='target_unavailable')


def visible(spec, day, oid):
    if spec.world_version not in (VERSION, 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        return True
    from content.experience_next import enabled, EVENT_OBJECTS
    if enabled() and oid in EVENT_OBJECTS:return False
    obj = catalogue_for(spec).get(oid)
    return bool(obj and (obj['day'] is None or obj['day'] == day))


def catalogue(spec, day, location_id, session_id=0):
    return [deepcopy(o) for o in catalogue_for(spec,day,session_id).values() if o['location_id']==location_id and visible(spec,day,o['id'])]


def read(db, sid):
    from services.atomic_action_service import _world_and_spec, _runtime_state
    from services.world_service import world_has_ended
    world,spec=_world_and_spec(db,sid)
    if spec.world_version not in (VERSION, 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') or world_has_ended(world):
        return {'objects':[], 'state':{}, 'seats':SEATS, 'locations':[], 'map':None}
    runtime=_runtime_state(world)[1]
    data=runtime.get('object_states',{}).get('_v4',{})
    # Never expose another actor's drafts or reading/work progress.
    own=deepcopy(data.get('actors',{}).get('participant',{}))
    own['public_cards']=deepcopy(data.get('public_cards',[]))
    own['occupied']={k:deepcopy(v) for k,v in data.get('occupied',{}).items() if v['day']==world.current_day}
    own['rest_seats']={venue:seat for venue,seat in own.get('rest_seats',{}).items()
                       if own['occupied'].get(venue+':'+seat,{}).get('group')=='participant'}
    own['orders']={k:(v if v and v.get('day')==world.current_day else None) for k,v in own.get('orders',{}).items()}
    from content.experience_next import enabled as next_enabled
    if next_enabled():
        from services.holiday_dining_service import item_facts
        for venue,order in own['orders'].items():
            if order: order['items']=item_facts(world,venue,order)
    if world.world_version=='chaoxi-holiday-v6':
        import time
        for progress in own.get('progress',{}).values():
            if progress.get('game_version')=='timed-volley-v6':
                progress['remaining_ms']=max(0,progress['deadline_ms']-int(time.time()*1000))
    from services.world_service import _serialize_map
    objects=[deepcopy(o) for o in catalogue_for(world).values() if o['location_id']==world.participant_location_id and visible(spec,world.current_day,o['id'])]
    if world.world_version=='chaoxi-holiday-v6':
        from services.holiday_calendar_v6 import venue_available,is_open,location_status
        for obj in objects:
            from services.holiday_work_service import gallery
            for a in obj['actions']:
                if a['id'] in ('browse','album') and a['kind'] in ('read','wall'):
                    a['items'].extend(gallery(db,world,obj['id']))
                if a['kind']=='search':
                    from content.holiday_search_v6 import SCENES
                    a['scenes']=[{**{k:s[k] for k in ('id','name','art_id')},'targets':[{'id':t[0],'name':t[1]} for t in s['targets']]} for s in SCENES]
            if obj['id'] in ('welcome_table','bonfire_table') and world.current_time_minutes<1110:
                obj['unavailable_reason']=('欢迎活动' if obj['id']=='welcome_table' else '篝火晚会')+'18:30开始，现在还不能互动。'
            elif not is_open(obj['location_id'],world.current_time_minutes):
                obj['unavailable_reason']='这里已经打烊。未完成的作品草稿会保留，下次开放时可以继续。'
            for act in obj['actions']:
                if act['kind']=='order':
                    act['can_order'],act['order_unavailable_reason']=venue_available(db,world,act['venue'])
    return {'objects':objects,'state':own,'seats':SEATS,'separate_dining':next_enabled(),
            'hours':location_status(world,world.participant_location_id) if world.world_version=='chaoxi-holiday-v6' else None,
            'minute':world.current_time_minutes,
            'locations':[{'id':l.location_id,'name':l.name['zh-CN'],'text':l.description['zh-CN']} for l in spec.locations.values()],
            'residents':[{'id':r.agent_id,'name':r.name,'detail':r.public_summary.get('zh-CN') or r.role.get('zh-CN','')} for r in spec.residents.values() if not __import__('content.experience_next',fromlist=['enabled']).enabled() or __import__('content.experience_next',fromlist=['active']).active(r.agent_id,world.current_day)],
            'map':_serialize_map(spec.map_spec),'day':world.current_day,'world_version':world.world_version}


def _item(action, key):
    found=next((x for x in action.get('items',[]) if x['id']==key),None)
    if not found: fail('请选择列表中的内容。')
    return found


def resident_inputs(world, runtime, actor_key, oid, aid, stage_runtime_id=None):
    """Server-owned concrete options for NPCs; no invented JSON/tool arguments."""
    obj=catalogue_for(world).get(oid)
    act=next((a for a in obj['actions'] if action_id(oid,a['id'])==aid),None) if obj else None
    if not act: return None
    state=runtime.get('object_states',{}).get('_v4',{})
    own=state.get('actors',{}).get(actor_key,{})
    p=own.get('progress',{}).get(aid,{})
    kind=act['kind'];payload={}
    if kind in ('write','sketch','map'): return None
    if kind in ('read','wall','book'):
        if not act['items']:return None
        payload={'item':act['items'][0]['id']}
    elif kind in ('steps','craft'):
        payload={'command':'step','step':p['step']} if 'step' in p and not p.get('done') else {'command':'start',**({'item':act['items'][0]['id']} if kind=='craft' else {})}
    elif kind=='volley': payload={'command':'hit','zone':p['target']} if 'round' in p and not p.get('done') else {'command':'start'}
    elif kind in ('huarong','timed_volley','search','freecraft'):return None
    elif kind=='puzzle':
        if not p.get('board') or p.get('done'):payload={'command':'start'}
        else:
            board=p['board'];z=board.index(0);next_tile=next(n for i,n in enumerate(board) if n and abs(i//3-z//3)+abs(i%3-z%3)==1)
            payload={'command':'move','tile':next_tile}
    elif kind=='snack' and world.current_time_minutes<1110:return None
    elif kind in ('order','seat','consume','leave'):
        venue=act['venue'];group='activity:'+str(stage_runtime_id) if stage_runtime_id else actor_key
        order=state.get('orders',{}).get(venue+':'+group)
        if order and order['day']!=world.current_day:order=None
        seats=[s['id'] for s in SEATS[venue] if not state.get('occupied',{}).get(venue+':'+s['id']) or state['occupied'][venue+':'+s['id']]['day']!=world.current_day]
        if kind=='order':
            adding=bool(stage_runtime_id and order and order['status'] in (('preparing','served') if world.world_version=='chaoxi-holiday-v6' else ('preparing',)) and actor_key not in order.get('contributions',{}))
            if (order and order['status'] not in ('left','finished') and not adding) or (not seats and not adding):return None
            payload={'command':'confirm','cart':{act['items'][0]['id']:1},'seat':order['seat'] if adding else seats[0]}
        elif kind=='seat':
            if order and order['status']=='preparing' and order.get('seat'):payload={}
            elif seats:payload={'seat':seats[0]}
            else:return None
        elif kind=='consume' and (not order or order['status']!='served'):return None
        elif kind=='leave' and not order and not own.get('rest_seats',{}).get(venue):return None
    return {'payload':json.dumps(payload,ensure_ascii=False)}


def prepare(db, world, spec, runtime, actor, target, prepared, stage_runtime_id=None):
    from content.experience_next import enabled as next_enabled
    if spec.world_version not in (VERSION, 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        return prepared
    obj=catalogue_for(world).get(target.object_id)
    if not obj or obj['location_id'] != actor.location_id or (not visible(spec,world.current_day,target.object_id) and not stage_runtime_id):
        fail('这里现在没有这个互动点。')
    act=next((a for a in obj['actions'] if action_id(obj['id'],a['id'])==prepared.action_id),None)
    if act is None: fail('这个动作已不在当前内容中。')
    act=deepcopy(act)
    if world.world_version=='chaoxi-holiday-v6' and act['id'] in ('browse','album') and act['kind'] in ('read','wall'):
        from services.holiday_work_service import gallery
        act['items'].extend(gallery(db,world,obj['id']))
    if world.world_version=='chaoxi-holiday-v6':
        from services.holiday_calendar_v6 import is_open
        if not is_open(obj['location_id'],world.current_time_minutes):
            fail('这里已打烊。未完成的草稿会保留，请下次开放时继续。')
        if obj['id'] in ('welcome_table','bonfire_table') and world.current_time_minutes<1110:
            fail(('欢迎活动' if obj['id']=='welcome_table' else '篝火晚会')+'18:30开始，现在还不能互动。')
    try:
        payload=json.loads(prepared.normalized_inputs.get('payload') or '{}')
    except (ValueError,TypeError):
        fail('操作内容格式不正确。')
    if not isinstance(payload,dict): fail('操作内容格式不正确。')
    if actor.actor_type=='resident' and not prepared.normalized_inputs.get('payload'):
        defaults=resident_inputs(world,runtime,actor.actor_key,obj['id'],prepared.action_id,stage_runtime_id)
        if defaults is None: fail('这个动作现在不适合执行。')
        payload=json.loads(defaults['payload'])
    kind=act['kind']; command=payload.get('command','open')
    data=deepcopy(runtime.get('object_states',{}).get('_v4',{}))
    states=data.setdefault('actors',{}); own=states.setdefault(actor.actor_key,{})
    progress=own.setdefault('progress',{})
    key=prepared.action_id; p=progress.setdefault(key,{})
    result=''; minutes=0
    if kind in ('read','wall'):
        if command=='buy':
            if not next_enabled() or obj['id']!='shelf' or act['id']!='browse':
                fail('这里不能购买商品。')
            item=_item(act,payload.get('item'))
            quantity=payload.get('quantity')
            if type(quantity)!=int or not 1<=quantity<=9:
                fail('请选择1到9份零食。')
            total=item['price']*quantity
            own.setdefault('purchases',[]).append({'object_id':'shelf','day':world.current_day,
                'minute':world.current_time_minutes,'item_id':item['id'],'name':item['name'],
                'art_id':item['art_id'],'quantity':quantity,'unit_price':item['price'],
                'total_price':total,'status':'purchased'})
            result=f"已购买：{item['name']} × {quantity}，合计 ¥{total}。零食已交到你手里。"
        elif payload.get('item'):
            item=_item(act,payload['item']);result=item['name']+'\n'+item['text']
        else: result='、'.join(i['name'] for i in act['items'])
    elif kind=='freecraft':
        if command!='finish_graphical':fail('请完成拼搭后保存。')
        from services.holiday_play_service import freecraft
        completed,result=freecraft(payload)
        p.clear();p.update(completed)
        own.setdefault('works',[]).append({'object_id':obj['id'],'title':p['title'],'text':result,
            'design':deepcopy(p['design']),'day':world.current_day,'visibility':'scene_public'})
        minutes=10
    elif kind=='map':
        if payload.get('item'):
            loc=spec.locations.get(payload['item'])
            if not loc: fail('请选择地图上的地点。')
            result=loc.name['zh-CN']+'\n'+loc.description['zh-CN']
        else: result='翻开度假册，点击地图上的地点即可阅读介绍。'
    elif kind=='schedule':
        result='今天是10月%d日。%s'%(world.current_day,'18:30 在这里举行欢迎派对。' if world.current_day==1 else '18:30 海边有篝火晚会。' if world.current_day==7 else '今天可以自由使用活动室。手机中可以查看和发起邀约。')
    elif kind=='rest':
        if command not in ('open','leave'): fail('无法完成这个操作。')
        p['seated']=command!='leave'
        result=('你起身离开，继续逛小岛。' if command=='leave' else '你在长凳坐下，海浪轻拍岸边，一艘小船正在远处转弯。' if obj['id']=='bench' else '你在活动室坐下，窗外有脚步声经过，屋里留着安静的空座。')
        minutes=2 if command=='leave' else 0
    elif kind in ('steps','craft'):
        steps=act['steps']
        if command=='finish_graphical':
            from services.holiday_play_service import complete
            completed, result = complete(obj['id'], act, payload)
            p.clear(); p.update(completed)
            own.setdefault('works',[]).append({'object_id':obj['id'], 'title':completed['title'] if kind=='craft' else obj['name'],
                'text':result, 'design':deepcopy(p['design']), 'day':world.current_day})
            minutes=10 if kind=='craft' else 5
        elif command=='start':
            item=_item(act,payload.get('item')) if kind=='craft' else None
            p.clear();p.update(step=0,item=item['id'] if item else None,done=False)
            result='准备好了：'+steps[0]
        elif command=='step':
            if 'step' not in p or p.get('done'): fail('请先开始一次新的制作或练习。')
            if payload.get('step')!=p['step']: fail('进度已变化，请按当前步骤继续。')
            result='已完成：'+steps[p['step']];p['step']+=1
            if p['step']==len(steps):
                p['done']=True
                result+= '\n'+(_item(act,p['item'])['text'] if kind=='craft' else act['result'])
                own.setdefault('works',[]).append({'object_id':obj['id'],'title':_item(act,p['item'])['name'] if kind=='craft' else obj['name'],'text':result,'day':world.current_day})
            else: result+='\n接下来：'+steps[p['step']]
            minutes=(10 if kind=='craft' else 5) if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') and p.get('done') else 0 if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') else 1
        else: result='选择作品后开始。' if kind=='craft' else '按示范逐步尝试。'
    elif kind=='sketch':
        if command=='save':
            item=_item(act,payload.get('item')); strokes=payload.get('strokes')
            from services.holiday_sketch_service import validate_drawing
            normalized,styles=validate_drawing(strokes,payload.get('stroke_styles'),world.world_version,fail)
            p.update(item=item['id'],strokes=normalized,stroke_styles=styles,drawing_version='canvas-v1')
            result='你完成了一张'+item['name']+'速写。'
            own.setdefault('works',[]).append({'object_id':obj['id'],'title':item['name']+'速写','strokes':normalized,'stroke_styles':styles,'day':world.current_day});minutes=3
        else: result='选一个题材，在画纸上留下自己的线条。'
    elif kind=='write':
        if command=='save':
            text=payload.get('text');public=payload.get('public',False)
            if not isinstance(text,str) or not text.strip() or len(text)>500 or type(public)!=bool: fail('请填写1—500字。')
            if public and obj['id'] not in ('postcards','welcome_table'): fail('这份文字只保存为个人记录。')
            record={'object_id':obj['id'],'title':obj['name'],'text':text.strip(),'day':world.current_day,
                    'visibility':'island_public' if public else 'private'}
            if next_enabled() and obj['id']=='postcards':
                from services.experience_next_postcard_service import save_face
                record.update(save_face(world,states,actor.actor_key,payload))
            own.setdefault('works',[]).append(record)
            if public:
                data.setdefault('public_cards',[]).append({**record,'author':actor.actor_key})
            p.update(text=text.strip(),public=public)
            result=('已挂到公开留言处，并保存到日志。' if public else '已经保存到你的日志。')+'\n'+text.strip();minutes=2
        else: result='写好后预览并确认；默认仅保存到个人日志。'
    elif kind=='book':
        item=_item(act,payload.get('item',act['items'][0]['id'])); pages=item.get('pages') or item['text'].split('\n\n')
        page=payload.get('page',p.get(item['id'],0))
        if type(page)!=int or not 0<=page<len(pages): fail('这一页不存在。')
        p[item['id']]=page; result=f"{item['name']} · 第{page+1}页\n{pages[page]}"
    elif kind=='snack':
        if world.current_time_minutes<1110: fail('点心和热饮还在准备，18:30 后可以领取。')
        result=act['result'];minutes=1
    elif kind in ('order','seat','consume','leave') and next_enabled():
        from services.holiday_dining_service import prepare as prepare_dining
        result,minutes=prepare_dining(db,world,spec,data,own,actor,act,payload,stage_runtime_id)
    elif kind in ('order','seat','consume','leave'):
        venue=act['venue'];orders=data.setdefault('orders',{});occupied=data.setdefault('occupied',{})
        # A foreground party shares one order, owned by the actual plan members.
        group='activity:'+str(stage_runtime_id) if stage_runtime_id else actor.actor_key
        order_key=venue+':'+group
        order=orders.get(order_key)
        if order and order['day']!=world.current_day:
            occupied.pop(venue+':'+order['seat'],None);orders.pop(order_key,None);order=None
        if kind=='order' and command=='confirm':
            if world.world_version=='chaoxi-holiday-v6':
                from services.holiday_calendar_v6 import venue_available
                available,reason=venue_available(db,world,venue)
                if not available:fail(reason)
            cart=payload.get('cart'); seat=payload.get('seat')
            if not isinstance(cart,dict) or not cart or len(cart)>len(act['items']): fail('请先选择餐点或饮品。')
            for k,v in cart.items():
                _item(act,k)
                if type(v)!=int or not 1<=v<=9: fail('每样请选择1—9份。')
            if seat not in {s['id'] for s in SEATS[venue]}: fail('请选择用餐位置。')
            slot=venue+':'+seat; reservation=occupied.get(slot)
            if reservation and reservation['day']==world.current_day and reservation['group']!=group: fail('这个位置已被占用，请选择其他位置。')
            adding=bool(stage_runtime_id and order and order['status'] in (('preparing','served') if world.world_version=='chaoxi-holiday-v6' else ('preparing',)) and actor.actor_key not in order.get('contributions',{}))
            if order and order.get('status') not in ('finished','left') and not adding: fail('已有未完成订单，请先享用或离座结束。')
            if adding and seat!=order['seat']:fail('共同订单已有座位，请使用相同位置。')
            contributions=deepcopy(order.get('contributions',{})) if adding else {}
            contributions[actor.actor_key]=cart
            combined={}
            for selection in contributions.values():
                for k,v in selection.items():combined[k]=combined.get(k,0)+v
            resting=own.setdefault('rest_seats',{}).pop(venue,None)
            if resting and occupied.get(venue+':'+resting,{}).get('group')==group: occupied.pop(venue+':'+resting,None)
            if order and occupied.get(venue+':'+order['seat'],{}).get('group')==group: occupied.pop(venue+':'+order['seat'],None)
            occupied[slot]={'group':group,'day':world.current_day}
            selections=[]
            for who,selection in contributions.items():
                name='你' if who=='participant' else spec.residents[int(who.split(':')[1])].name
                selections.append(name+'：'+'、'.join(_item(act,k)['name']+f' ×{v}' for k,v in selection.items()))
            order={'cart':combined,'contributions':contributions,'selections':selections,'seat':seat,'day':world.current_day,'status':'preparing','owner':actor.actor_key,'group':group,'round':(order or {}).get('round',0)+int(not adding)}
            orders[order_key]=order
            result='已接单：'+ '、'.join(_item(act,k)['name']+f' ×{v}' for k,v in cart.items())+'。位置：'+next(s['name'] for s in SEATS[venue] if s['id']==seat)+'。入座后将送到桌边。'
            if world.world_version=='chaoxi-holiday-v6':
                order['status']='served'
                order['total_price']=sum(_item(act,k).get('price',0)*v for k,v in combined.items())
                result='已点单：'+'、'.join(_item(act,k)['name']+f' ×{v}' for k,v in cart.items())+f"。合计 ¥{order['total_price']}，餐点已送到桌边，点击用餐即可享用。"
        elif kind=='order':
            result='浏览菜单，把想要的加入清单，选好座位后一起确认。'
        elif kind=='seat':
            if order and order['status'] in ('preparing','served'):
                order['status']='served';result='你在预订的位置坐下，餐点已送到桌边，可以开始享用了。'
            else:
                seat=payload.get('seat')
                if seat not in {s['id'] for s in SEATS[venue]}: fail('请选择一个空座。')
                slot=venue+':'+seat; reservation=occupied.get(slot)
                if reservation and reservation['day']==world.current_day and reservation['group']!=group: fail('这个位置已被占用。')
                previous=own.setdefault('rest_seats',{}).get(venue)
                if previous and occupied.get(venue+':'+previous,{}).get('group')==group: occupied.pop(venue+':'+previous,None)
                occupied[slot]={'group':group,'day':world.current_day}
                own.setdefault('rest_seats',{})[venue]=seat
                result='你在'+next(s['name'] for s in SEATS[venue] if s['id']==seat)+'坐下休息，菜单处可以点单。'
        elif kind=='consume':
            if not order or order['status']!='served': fail('请先点单并入座，等餐点送到后再享用。')
            from content.holiday_v4 import MENUS
            names={i['id']:i['name'] for i in MENUS[venue]}
            order['status']='finished';result='你享用了'+ '、'.join(names[k] for k in order['cart'])+'。这次用餐已完成。';minutes=5
            if world.world_version=='chaoxi-holiday-v6':
                occupied.pop(venue+':'+order['seat'],None)
                result+=' 你收拾好桌面，离开了座位。'
        elif kind=='leave':
            if order:
                if occupied.get(venue+':'+order['seat'],{}).get('group')==group: occupied.pop(venue+':'+order['seat'],None)
                order['status']='left'
            resting=own.setdefault('rest_seats',{}).pop(venue,None)
            if resting and occupied.get(venue+':'+resting,{}).get('group')==group: occupied.pop(venue+':'+resting,None)
            result='你离开座位，位置已腾空。'
        own.setdefault('orders',{})[venue]=deepcopy(order)
        if stage_runtime_id:
            from services import stage_service as stages
            plan=stages._binding(db,world.session_id,stage_runtime_id)[3]
            for member in stages._members(db,plan):
                states.setdefault(member.actor_key,{}).setdefault('orders',{})[venue]=deepcopy(order)
    elif kind in ('huarong','timed_volley','search'):
        from services.holiday_games_v6 import huarong,timed_volley,search
        from services.holiday_volley_v7 import command as position_volley
        if world.world_version=='chaoxi-holiday-v6':timed_volley=position_volley
        was_done=bool(p.get('done'))
        result={'huarong':huarong,'timed_volley':timed_volley,'search':search}[kind](p,payload,fail)
        if p.get('done') and not was_done:minutes=5
    elif kind=='puzzle':
        if command=='start': p.clear();p.update(board=[1,2,3,4,0,6,7,5,8],moves=0,done=False)
        elif command=='move':
            board=p.get('board');tile=payload.get('tile')
            if not board or p.get('done') or type(tile)!=int or tile==0 or tile not in board: fail('请开始一局拼图。')
            a=board.index(0);b=board.index(tile)
            if abs(a//3-b//3)+abs(a%3-b%3)!=1: fail('只能移动空格旁边的数字。')
            board[a],board[b]=board[b],board[a];p['moves']+=1;p['done']=board==[1,2,3,4,5,6,7,8,0]
        elif command!='open': fail('无法完成这个操作。')
        result='拼图完成！你用了%d步。'%p['moves'] if p.get('done') else '点击与空格相邻的数字。'
    elif kind=='volley':
        if command=='start':
            p.clear();p.update(round=0,score=0,target=1,done=False)
        elif command=='hit':
            if 'round' not in p or p.get('done'): fail('请先开始练习。')
            zone=payload.get('zone')
            if type(zone)!=int or zone not in (0,1,2): fail('请选择左、中、右区域。')
            good=zone==p['target'];p['score']+=int(good);p['round']+=1;p['done']=p['round']>=5
            result='球落在目标区域。' if good else '这次偏离了目标，下次调整方向。'
            p['target']=(p['target']+2)%3
        elif command!='open': fail('无法完成这个操作。')
        result+=(f" 本轮命中{p.get('score',0)}/5次。" if p.get('done') else ' 看清目标后选择击球方向。')
    else:
        fail('当前内容不支持这个操作。')
    # Shared state is committed together with the atomic audit, never in a later request.
    runtime.setdefault('object_states',{})['_v4']=data
    effects=({'effect_type':'set_object_state','state_key':'result','value':result},)
    if world.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        minutes=((minutes+4)//5)*5
    return replace(prepared,effects=effects,duration_minutes=0 if stage_runtime_id or actor.actor_type=='resident' else minutes)
