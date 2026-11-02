"""Meal orders, seating, and item snapshots."""
from copy import deepcopy
from content.holiday_v4 import SEATS
from content.holiday_v6 import catalogue_for


def leave_venue(world):
    """Close the participant's table on a real scene departure, retaining history."""
    from content.experience_next import enabled
    if not enabled(): return
    venue={'loc_04':'restaurant','loc_06':'cafe'}.get(world.participant_location_id)
    if not venue:return
    import json
    from services.atomic_action_service import _runtime_state
    root,runtime=_runtime_state(world)
    data=runtime.get('object_states',{}).get('_v4',{})
    own=data.get('actors',{}).get('participant',{})
    order=own.get('orders',{}).pop(venue,None)
    if order:
        record=deepcopy(order)
        if record['status'] not in ('finished','left'):record['status']='left'
        own.setdefault('order_history',[]).append({'venue':venue,**record})
        group=record.get('group','participant')
        if group=='participant':data.get('orders',{}).pop(venue+':'+group,None)
    own.get('rest_seats',{}).pop(venue,None)
    data['occupied']={k:v for k,v in data.get('occupied',{}).items() if not(k.startswith(venue+':') and v.get('group')=='participant')}
    world.state_json=json.dumps(root,ensure_ascii=False)


def item_facts(world, venue, order):
    from services.experience_next_daily import all_choices
    available = {i['id']: i for i in all_choices()[venue+'_menu']}
    # Compatibility with an order saved before item snapshots were introduced.
    return {key: deepcopy(order.get('items', {}).get(key) or available.get(key) or
                         {'id':key, 'name':'已点餐品', 'text':'', 'price':0})
            for key in order['cart']}


def prepare(db, world, spec, data, own, actor, act, payload, stage_runtime_id):
    from services.holiday_object_service import fail, _item
    from services.holiday_calendar_v6 import venue_available
    venue, kind = act['venue'], act['kind']
    orders, occupied = data.setdefault('orders', {}), data.setdefault('occupied', {})
    group = 'activity:'+str(stage_runtime_id) if stage_runtime_id else actor.actor_key
    order_key = venue+':'+group
    order = orders.get(order_key)
    previous_rest=own.setdefault('rest_seats',{}).get(venue)
    reservation=occupied.get(venue+':'+str(previous_rest),{})
    if reservation.get('day')!=world.current_day or reservation.get('group')!=group:
        own['rest_seats'].pop(venue,None)
    def release(seat):
        slot=venue+':'+str(seat)
        if occupied.get(slot, {}).get('group') == group: occupied.pop(slot, None)
    def reserve(seat):
        if seat not in {s['id'] for s in SEATS[venue]}: fail('请选择一个座位。')
        reservation=occupied.get(venue+':'+seat)
        if reservation and reservation['day']==world.current_day and reservation['group']!=group:
            fail('这个位置已被占用，请选择其他座位。')
        occupied[venue+':'+seat]={'group':group,'day':world.current_day}
    if order and order['day'] != world.current_day:
        release(order.get('seat')); orders.pop(order_key, None); order=None
    result, minutes = '', 0
    if kind=='order' and payload.get('command')=='confirm':
        available, reason=venue_available(db,world,venue)
        if not available: fail(reason)
        cart=payload.get('cart')
        if not isinstance(cart,dict) or not cart or len(cart)>len(act['items']): fail('请先选择餐点或饮品。')
        for k,v in cart.items():
            _item(act,k)
            if type(v) is not int or not 1<=v<=9: fail('每样请选择1—9份。')
        adding=bool(stage_runtime_id and order and order['status'] in ('preparing','served') and actor.actor_key not in order.get('contributions',{}))
        if order and order['status'] not in ('finished','left') and not adding: fail('已有未完成订单，请先享用或离座结束。')
        contributions=deepcopy(order.get('contributions',{})) if adding else {}
        facts=item_facts(world,venue,order) if adding else {}
        contributions[actor.actor_key]=cart
        facts.update({k:deepcopy(_item(act,k)) for k in cart})
        combined={}
        for selection in contributions.values():
            for k,v in selection.items(): combined[k]=combined.get(k,0)+v
        if not adding and order: release(order.get('seat'))
        seat=order.get('seat') if adding else own.setdefault('rest_seats',{}).get(venue)
        if seat: reserve(seat)
        selections=[]
        for who,selection in contributions.items():
            name='你' if who=='participant' else spec.residents[int(who.split(':')[1])].name
            selections.append(name+'：'+'、'.join(facts[k]['name']+f' ×{v}' for k,v in selection.items()))
        order={'cart':combined,'items':facts,'contributions':contributions,'selections':selections,
               'seat':seat,'day':world.current_day,'status':'served' if seat else 'preparing',
               'owner':actor.actor_key,'group':group,'round':(order or {}).get('round',0)+int(not adding),
               'total_price':sum(facts[k].get('price',0)*v for k,v in combined.items())}
        orders[order_key]=order
        result='已点单：'+'、'.join(facts[k]['name']+f' ×{v}' for k,v in cart.items())+f"。合计 ¥{order['total_price']}。"
        result+='餐点已送到桌边。' if seat else '请关闭菜单，点击场景中的桌位选择座位。'
    elif kind=='order': result='选好餐品后确认点单，再到桌位选择座位。'
    elif kind=='seat':
        seat=payload.get('seat') or (order or {}).get('seat')
        reserve(seat)
        previous=own.setdefault('rest_seats',{}).get(venue)
        if previous!=seat: release(previous)
        if order and order['status'] in ('preparing','served'):
            if order.get('seat')!=seat: release(order.get('seat'))
            order.update(seat=seat,status='served')
        own['rest_seats'][venue]=seat
        result='你在'+next(s['name'] for s in SEATS[venue] if s['id']==seat)+'坐下。'
        result+='餐饮已送到桌边，可以享用了。' if order and order['status']=='served' else '可以先看风景，想点单时再打开菜单。'
    elif kind=='consume':
        if not order or order['status']!='served' or not order.get('seat'): fail('请先点单，再点击桌位选择座位。')
        facts=item_facts(world,venue,order)
        order.update(items=facts,status='finished')
        result='你享用了'+'、'.join(facts[k]['name'] for k in order['cart'])+'。这次用餐已完成。'
        minutes=5
        release(order.get('seat')); own.setdefault('rest_seats',{}).pop(venue,None)
        result+=' 你收拾好桌面，离开了座位。'
    elif kind=='leave':
        if order: release(order.get('seat')); order['status']='left'
        release(own.setdefault('rest_seats',{}).pop(venue,None))
        result='你离开座位，位置已腾空。'
    own.setdefault('orders',{})[venue]=deepcopy(order)
    if stage_runtime_id:
        from services import stage_service as stages
        plan=stages._binding(db,world.session_id,stage_runtime_id)[3]
        for member in stages._members(db,plan):
            data['actors'].setdefault(member.actor_key,{}).setdefault('orders',{})[venue]=deepcopy(order)
    return result,minutes
