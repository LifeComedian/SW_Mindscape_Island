"""Provide residents with the current shop catalogue."""
def catalogue_facts(agent_id, world_version, world=None):
    if world_version != 'chaoxi-holiday-v6':
        return []
    key={3:'shelf',4:'restaurant_menu',6:'cafe_menu'}.get(agent_id)
    if key is None:
        return []
    from content.holiday_v6 import CATALOGUE, catalogue_for
    CATALOGUE=catalogue_for(world) if world is not None else CATALOGUE
    items=[{k:item[k] for k in ('id','name','price','text') if k in item}
           for item in CATALOGUE[key]['actions'][0]['items']]
    order_facts=[]
    if world is not None:
        from content.experience_next import enabled
        if enabled():
            import json
            own=json.loads(world.state_json or '{}').get('modular_runtime',{}).get('object_states',{}).get('_v4',{}).get('actors',{}).get('participant',{})
            venue={4:'restaurant',6:'cafe'}.get(agent_id)
            records=[r for r in own.get('order_history',[]) if r.get('venue')==venue][-3:]
            current=own.get('orders',{}).get(venue)
            if current:records.append(current)
            if records:order_facts=[{'fact_ref':'customer_orders:'+key,'type':'customer_order_history','data':{'orders':[{'day':r['day'],'status':r['status'],'items':r.get('selections',[])} for r in records],'limits':'仅本人店内点单记录；过去用餐不代表现在又点了同样的餐品。'}}]
            if agent_id==3 and own.get('purchases'):
                order_facts.append({'fact_ref':'customer_purchases:shelf','type':'customer_purchase_history',
                    'data':{'purchases':own['purchases'][-10:],
                            'limits':'这是用户已完成的零食购买记录。只证明购买并领取，不证明已经吃掉，也不代表这次又买了同样的零食。'}})
    return order_facts+[{'fact_ref':'catalogue:'+key, 'type':'authored_catalogue',
             'data':{'items':items,'complete_choice_list':True,'today_note':CATALOGUE[key].get('daily_note'),
                     'tomorrow':'只能表达愿意参考偏好，不能承诺未确认的次日商品。次日实际发布后才能说已准备。',
                     'limits':'只证明提供的商品/价格，不证明已点单、已付款或已递交。未列出的品种不能说有货；未列出的咖啡豆/产地不能猜。没有钱包余额限制。'}}]


def map_facts(spec):
    """Authored destinations/objects only; no inferred routes or facilities."""
    if spec.world_version != 'chaoxi-holiday-v6':
        return []
    from data.island import localized
    places = [{'name': localized(place.name, 'zh-CN'),
               'points': [localized(p.get('name', {}), 'zh-CN') for p in place.interaction_points if not (__import__('content.experience_next',fromlist=['enabled']).enabled() and p.get('object_id') in ('welcome_table','bonfire_table'))]}
              for place in spec.locations.values()]
    from content.holiday_v4 import SEATS
    return [{'fact_ref': 'map:destinations', 'type': 'authored_map', 'data': {
        'places': places, 'complete_destination_list': True,
        'dining_seats':{'餐馆':SEATS['restaurant'],'咖啡馆':SEATS['cafe']},
        'seat_rule':'餐馆有门外阳光位，咖啡馆有二楼阳台位，均为已实现设施。不得因地点总览没有展开桌位而否认其存在。位置名称不证明此刻天气或空位。',
        'limits': '这是可到达地点与设施清单，不证明此刻开放、人在那里或已经移动。不要补造未列出的屋顶、露台、楼层、分店或路线。海边/海滩可指沙滩等已列地点；地名存在不证明附加设施存在。'}}]


def dining_facts(world,agent_id):
    """The public local menu and the speaker's own shared table, for guests too."""
    if world.world_version!='chaoxi-holiday-v6':return []
    import json
    from content.holiday_v4 import SEATS
    from content.holiday_v6 import catalogue_for
    venue={'loc_04':'restaurant','loc_06':'cafe'}.get(world.participant_location_id)
    if not venue:return []
    menu=catalogue_for(world)[venue+'_menu']['actions'][0]['items']
    root=json.loads(world.state_json or '{}')
    own=root.get('modular_runtime',{}).get('object_states',{}).get('_v4',{}).get('actors',{}).get('resident:'+str(agent_id),{})
    order=own.get('orders',{}).get(venue)
    if order and order.get('day')!=world.current_day:order=None
    return [{'fact_ref':'dining:'+venue,'type':'authored_dining_options','data':{
        'venue':venue,'seats':SEATS[venue],'menu':[{'id':i['id'],'name':i['name'],'price':i.get('price')} for i in menu],
        'own_shared_order':order,'limits':'菜单和桌位是所有到场者可见的选项；只有own_shared_order证明自己的这桌点单，不能从玩家意向推断完成。空订单不代表其他人没有点单。选座不证明正在晴天。'}}]
