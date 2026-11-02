"""V6 content overrides; older saves retain their bound version."""
from copy import deepcopy
from content.holiday_v4 import CATALOGUE as V4_CATALOGUE

VERSION = 'chaoxi-holiday-v6'
CATALOGUE = deepcopy(V4_CATALOGUE)
CATALOGUE.pop('rope',None)
for venue,prices in [('restaurant',[28,26,12]),('cafe',[22,16,20])]:
    for item,price in zip(CATALOGUE[venue+'_menu']['actions'][0]['items'],prices):
        item['price']=price
    CATALOGUE[venue+'_table']['actions']=[a for a in CATALOGUE[venue+'_table']['actions'] if a['kind']=='consume']
    CATALOGUE[venue+'_table']['actions'][0]['name']='用餐' if venue=='restaurant' else '享用饮品'
for item,price in zip(CATALOGUE['shelf']['actions'][0]['items'],[8,5,10]):
    item['price']=price
CATALOGUE['shelf']['actions'][0]['items']=[
    {'id':key,'name':name,'price':price,'text':text}
    for key,name,price,text in [
        ('biscuit','海盐饼干',8,'一小袋薄脆饼干。'),('juice','橙汁',12,'一瓶清爽的橙汁。'),
        ('nuts','混合坚果',15,'一份小包装坚果。'),('pencil','铅笔',3,'一支木质铅笔。'),
        ('sketchbook','素描本',18,'一本留白的素描本。'),('tissue','纸巾',4,'一包便携纸巾。')]]
CATALOGUE['wood_work']['actions'][-1]['name']='拼装木船'
CATALOGUE['wood_work']['actions'][-1]['items']=CATALOGUE['wood_work']['actions'][-1]['items'][:1]
CATALOGUE['wood_work']['actions'][-1]['geometry_version']='tight-v6'
CATALOGUE['wood_work']['actions'][-1]['items'][0]['text']='把预制船身、桅杆和帆片对齐，即可完成木船。'
CATALOGUE['wood_work']['actions'].append({'id':'free','name':'自由拼搭木作','kind':'freecraft','items':[]})
CATALOGUE['wood_work']['actions'][0]['items'][0]['text']='船身、桅杆和帆片用于拼装木船；自由拼搭还提供长木条、方块、圆片和三角片，可以移动、旋转、叠放与复制。'
CATALOGUE['beach']['actions']=[a for a in CATALOGUE['beach']['actions'] if a['id']!='walk']
CATALOGUE['beach']['actions'][0].update(kind='search',name='潮间带寻物',items=[])
CATALOGUE['volleyball']['actions']=[a for a in CATALOGUE['volleyball']['actions'] if a['id']!='serve']
CATALOGUE['volleyball']['actions'][0]['items'][0]['text']='单人垫球练习共12球。移动到落点附近，在球靠近手臂时点击或按空格垫球；标准模式每球1.8秒，挑战模式每球1.1秒。也可以邀请1—3位居民一起进行多人垫球练习。'
CATALOGUE['volleyball']['actions'][1]['kind']='timed_volley'
CATALOGUE['games']['actions'][0]['items']=[
    {'id':'uno','name':'UNO','text':'轻松UNO：2—4人，每人5张；同色或同数字出牌，也有变色牌。摸牌自动处理，没有罚牌，不用手动喊UNO。先出完者结束本局。'},
    {'id':'huarong','name':'华容道','text':'将棋子在4×5棋盘上平移，让2×2的曹操从下方中央出口离开。不能旋转或重叠。六个关卡，可撤销、重开或查看下一步提示。'}]
CATALOGUE['games']['actions'][1].update(kind='huarong',name='游玩华容道')
from content.holiday_reading_v6 import BOOKS,POSTCARDS
CATALOGUE['books']['actions']=[a for a in CATALOGUE['books']['actions'] if a['id']=='read']
CATALOGUE['books']['actions'][0].update(name='选书阅读',items=deepcopy(BOOKS))

CATALOGUE['postcards']['actions'][0]['items']=deepcopy(POSTCARDS)
CATALOGUE['flowers']['actions'].append({'id':'browse','name':'看看完成的插花','kind':'read','items':[]})
CATALOGUE['flowers']['actions'][0]['items'][0]['text']='小雏菊、暖色小花和尤加利叶摆在桌上，可选浅口花器或小陶瓶，拖动花头来安排高低与位置。'
for oid in ('wood_display','photos','plants','sketch'):
    for act in CATALOGUE[oid]['actions']:
        if act['kind']=='read':
            for item in act['items']:
                if act['id'] in ('browse','album'):item['art_id']=f"exhibit.{oid}.{item['id']}"


from content.holiday_chinese import edit_catalogue, edit_pack
edit_catalogue(CATALOGUE)


def enrich(systems, locations, residents, manifest):
    # Build seating options in a separate catalogue to preserve older worlds.
    CATALOGUE = base_catalogue()
    manifest['experience']['behavior_audit_version'] = 'holiday-experience-v6-20261020'
    manifest['calendar'].update(day_start_minute=480,day_end_minute=1320,rollover='next_day')
    from services.holiday_calendar_v6 import hours_text
    systems['activity_recipes']=[r for r in systems['activity_recipes'] if r['recipe_id'] not in ('rope_practice','volley_match')]
    systems['stage_recipes']=[r for r in systems['stage_recipes'] if r['stage_recipe_id'] not in ('rope_practice_stages','volley_match_stages')]
    for loc in locations:
        loc['interaction_points']=[p for p in loc['interaction_points'] if p['object_id']!='rope']
        for language in ('zh-CN','en'):
            loc['description'][language]+='\n开放时间：'+hours_text(loc['location_id'])+'。每日自由活动时间为08:00–22:00。'
    for person in residents:
        regular=[b for b in person['schedule'] if not b.get('days')]
        if regular:
            regular[0]['start_minute']=480
            regular[-1]['end_minute']=1320
        # Accepted invitations can override shop shifts.
        shifts={
            4:[(480,655,'residential','早餐和休息'),(655,660,'loc_05','经过广场去餐厅'),
               (660,840,'loc_04','午间营业，照看餐厅'),(840,845,'loc_05','经过广场'),
               (845,1015,'loc_06','午后休息'),(1015,1020,'loc_05','经过广场去餐厅'),
               (1020,1260,'loc_04','晚间营业，照看餐厅'),(1260,1265,'loc_05','收工回家'),
               (1265,1321,'residential','回家休息')],
            6:[(480,720,'loc_06','早间营业，照看咖啡馆'),(720,725,'loc_05','经过广场去吃午饭'),
               (725,805,'loc_04','午餐休息，咖啡馆暂停点单'),(805,810,'loc_05','经过广场回店'),
               (810,1260,'loc_06','下午和晚间营业，照看咖啡馆'),(1260,1265,'loc_05','收工回家'),
               (1265,1321,'residential','回家休息')],
        }
        if person['agent_id'] in shifts:
            special=[b for b in person['schedule'] if b.get('days')]
            person['schedule']=[{'state_id':f"resident_{person['agent_id']}_v6_shift_{i}",
                'start_minute':start,'end_minute':end-1,'location_id':lid,
                'activity':{k:text for k in ('zh-CN','en')},'goal':person['goals'][0]}
                for i,(start,end,lid,text) in enumerate(shifts[person['agent_id']])]+special
            person['autonomy']['free_time_state_ids']=[b['state_id'] for b in person['schedule']]
    # Retired interactions must disappear from execution, planning and prompts.
    allowed={f"v4_{o['id']}__{a['id']}":a for o in CATALOGUE.values() for a in o['actions']}
    template=deepcopy(systems['action_definitions'][0])
    systems['action_definitions']=[d for d in systems['action_definitions'] if d['action_id'] in allowed]
    systems['affordances']=[a for a in systems['affordances'] if a['action_id'] in allowed]
    existing={d['action_id'] for d in systems['action_definitions']}
    for oid,obj in CATALOGUE.items():
        for act in obj['actions']:
            aid=f"v4_{oid}__{act['id']}"
            if aid not in existing:
                definition=deepcopy(template)
                definition.update(action_id=aid,label={k:act['name'] for k in ('zh-CN','en')})
                systems['action_definitions'].append(definition)
                systems['affordances'].append({'affordance_id':aid+'_here','action_id':aid,'location_ids':[obj['location_id']],
                    'object_ids':[oid],'enabled':True,'conditions':{},'permission_keys':[],'capability_keys':[]})
    for definition in systems['action_definitions']:
        act=allowed[definition['action_id']]
        definition['label']={k:act['name'] for k in ('zh-CN','en')}
        for inp in definition['inputs']:
            if inp['input_id']=='payload':inp['max_length']=180000 if definition['action_id']=='v4_sketch__draw' else 2000
    for loc in locations:
        for point in loc['interaction_points']:
            obj=CATALOGUE.get(point['object_id'])
            if obj:point['description']={k:'、'.join(a['name'] for a in obj['actions']) for k in ('zh-CN','en')}
    for recipe in systems['activity_recipes']:
        recipe['action_ids']=[aid for aid in recipe['action_ids'] if aid in allowed]
        if recipe['recipe_id']=='woodcraft':recipe['action_ids'].append('v4_wood_work__free')
        if recipe['recipe_id']=='beach_walk':
            recipe['recipe_id']='beach_search'
            recipe['label']={k:'一起在海滩寻物' for k in ('zh-CN','en')}
        if recipe['recipe_id']=='volley_pass':recipe['label']={k:'多人垫球练习' for k in ('zh-CN','en')}
        if recipe['recipe_id']=='table_game':recipe['label']={k:'一起玩UNO' for k in ('zh-CN','en')}
    for recipe in systems['stage_recipes']:
        recipe['allowed_action_ids']=[aid for aid in recipe['allowed_action_ids'] if aid in allowed]
        for stage in recipe['stages']:
            stage['choices']=[c for c in stage['choices'] if c['action_id'] in allowed]
    def clean(value):
        if isinstance(value,str):return value.replace('沿水边散步','在海滩寻物').replace('沿沙滩走走','在海滩寻物').replace('颜色接龙','UNO').replace('数字拼图','华容道').replace('垫球和发球','垫球').replace('绳结练习台','木工台').replace('练习绳结','拼装木船').replace('绳结','木作')
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
        return value
    residents[:]=clean(residents)
    edit_pack(residents, locations, manifest)


def base_catalogue():
    from content.experience_next import enabled
    base = deepcopy(CATALOGUE)
    if enabled():
        for venue in ('restaurant', 'cafe'):
            base[venue+'_table']['actions'] = deepcopy(V4_CATALOGUE[venue+'_table']['actions'])
            base[venue+'_table']['actions'][0]['name'] = '选择座位'
    return base


def catalogue_for(spec, day=None, session_id=None):
    base=base_catalogue() if spec.world_version == VERSION else V4_CATALOGUE
    from content.experience_next_catalogue import catalogue
    from services.experience_next_daily import apply
    return apply(spec,catalogue(base, day or getattr(spec,'current_day',1), session_id or getattr(spec,'session_id',0))) if spec.world_version==VERSION else base
