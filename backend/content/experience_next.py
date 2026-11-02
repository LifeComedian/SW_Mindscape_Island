"""Select the island experience by version."""
import json
import os
import re
import random
from pathlib import Path
from copy import deepcopy

VERSION = 'island-life-20261026-v1'
ROOT = Path(__file__).parent
EVENT_OBJECTS = {'welcome_table', 'bonfire_table'}
VISITORS = {9: (2, 3), 10: (4, 5), 11: (6, 7)}

def enabled():
    return (os.getenv('ISLAND_EXPERIENCE_VERSION') == VERSION or
            (os.getenv('ISLAND_NEXT_LOCAL') == '1' and os.getenv('STUDY_RUNTIME_ENV') != 'production'))

def active(agent_id, day):
    return agent_id not in VISITORS or VISITORS[agent_id][0] <= day <= VISITORS[agent_id][1]

def profiles():
    return json.loads((ROOT / 'experience_next_characters.json').read_text(encoding='utf-8'))['characters']

def enrich(systems, locations, residents, manifest):
    if not enabled(): return
    manifest['content_pack_version'] = VERSION
    people = profiles()
    for index, person in enumerate(people):
        aid = index + 1
        identity=person['identity'].replace('新游客提案：','')
        if aid <= 8:
            resident = next(r for r in residents if r['agent_id'] == aid)
        else:
            resident = deepcopy(residents[7])
            resident.update(agent_id=aid, name=person['name'], adult_age_range=re.search(r'\d+',identity)[0],
                home_location_id='guest_room', avatar_key='resident_default',
                profile_version=f'{VERSION}-resident-{aid}', autonomy={'enabled':False,'allowed_intents':['idle'],'free_time_state_ids':[]})
            resident['schedule'] = []
            for day in range(1,8):
                places=['loc_01','loc_02','loc_03','loc_04','loc_05','loc_06']
                random.Random(aid*101+day*17).shuffle(places)
                itinerary=[(480,529,'loc_01' if day==VISITORS[aid][0] else 'loc_06','刚从码头抵达，随意逛逛' if day==VISITORS[aid][0] else '喝点东西，随时可以聊聊'),(530,539,'loc_05','沿广场散步')]
                for i,lid in enumerate(places):
                    start=540+i*110
                    if lid=='loc_04' and start<660:lid='loc_01'
                    itinerary += [(start,start+99,lid,'随意游览，可以停下来聊天'),(start+100,start+109,'loc_05','沿广场散步')]
                itinerary += [(1200,1209,'loc_02','走回民宿'),(1210,1320,'guest_room','在民宿外廊休息，准备回自己的房间')]
                for start,end,lid,activity in itinerary:
                    resident['schedule'].append({'state_id':f'visitor_{aid}_{day}_{start}', 'days':[day], 'start_minute':start,'end_minute':end,
                        'location_id':lid if active(aid,day) else 'guest_room', 'activity':{'zh-CN':activity if active(aid,day) else '尚未到岛或已经离岛'}, 'goal':{'zh-CN':'自在度过假期，尊重别人的安排'}})
            residents.append(resident)
            details={9:('保留自己的眼光，也给别人不同的理解留地方。',['书的装帧','随手散步','看展品'],'休假时暂时不用工作里的评价标准要求自己。'),10:('承诺了就尽力做到，也愿意把决定权交还给别人。',['出行路线','桌游','团队合作'],'试着过两天不必替所有人安排的日子。'),11:('允许尝试没有用途，也珍惜真正答应过的事情。',['手工组合','科学展览','新鲜玩法'],'看看手边的材料还能变成什么，不要求每个尝试有成果。')}
            value,prefs,goal=details[aid]
            resident['values']=[{'zh-CN':value}]
            resident['preferences']=[{'zh-CN':p} for p in prefs]
            resident['goals']=[{'zh-CN':goal}]
            resident['avoid_patterns']=[{'zh-CN':'不冒充岛上工作人员，不主持性格测试，不在休假聊天中反复讲职业。'}]
            resident['knowledge_boundaries']=[{'zh-CN':person['agency']}]
        resident['role']={'zh-CN':identity.split('；',1)[-1]}
        resident['background']={'zh-CN':person['biography']}
        resident['personality']={'zh-CN':person['tension']}
        resident['public_summary']={'zh-CN':identity}
        resident['communication_style']={'zh-CN':person['casual']+' 深入聊天时：'+person['deep']+' 先接住对方的话，不每轮讲自己的职业或追问。'}
        resident['knowledge_boundaries'] += [{'zh-CN':person['disclosure']},{'zh-CN':'人生背景不等于与玩家共同发生过的经历。岛外地点只属于回忆，不能邀约前往。'}]
    # Disable scripted welcome and farewell events.
    for key,id_key in [('activity_recipes','recipe_id'),('stage_recipes','stage_recipe_id')]:
        systems[key]=[r for r in systems[key] if r[id_key] not in ('welcome','bonfire','welcome_stages','bonfire_stages')]
    removed={a['action_id'] for a in systems['action_definitions'] if any(a['action_id'].startswith('v4_'+oid+'__') for oid in EVENT_OBJECTS)}
    systems['action_definitions']=[a for a in systems['action_definitions'] if a['action_id'] not in removed]
    systems['affordances']=[a for a in systems['affordances'] if a['action_id'] not in removed]
    for location in locations:
        location['interaction_points']=[p for p in location['interaction_points'] if p['object_id'] not in EVENT_OBJECTS]
    for resident in residents:
        resident['schedule']=[s for s in resident['schedule'] if not any(x in s['state_id'] for x in ('welcome','bonfire'))]
        resident['autonomy']['free_time_state_ids']=[s for s in resident['autonomy'].get('free_time_state_ids',[]) if not any(x in s for x in ('welcome','bonfire'))]
    for recipe in systems['activity_recipes']:
        if not recipe.get('conditions',{}).get('fixed_day'):
            recipe.setdefault('conditions',{})['arrival_grace_minutes']=30
            if recipe['conditions'].get('organizer_agent_ids'):
                recipe['conditions']['organizer_agent_ids']=list(range(1,12))
    def languages(value):
        if isinstance(value,dict):
            if 'zh-CN' in value and 'en' not in value:value['en']=value['zh-CN']
            for child in value.values():languages(child)
        elif isinstance(value,list):
            for child in value:languages(child)
    languages(residents)
    # Keep shop IDs stable for saved games.
    def snack_names(value):
        if isinstance(value,str):return value.replace('便利店','零食店').replace('杂货店','零食店')
        if isinstance(value,list):return [snack_names(v) for v in value]
        if isinstance(value,dict):return {k:snack_names(v) for k,v in value.items()}
        return value
    locations[:]=snack_names(locations);residents[:]=snack_names(residents)
    for location in locations:
        for point in location['interaction_points']:
            names={'shelf':'零食货架','flowers':'插花展架与工作桌','photos':'摄影展示架','cafe_menu':'咖啡店菜单','postcards':'明信片展示架'}
            if point['object_id'] in names:point['name']={'zh-CN':names[point['object_id']],'en':names[point['object_id']]}

def biography_facts(agent_id):
    if not enabled(): return []
    person=profiles()[agent_id-1]
    return ([{'fact_ref':f'visit:{agent_id}','type':'authored_visit_dates','data':{'first_day':VISITORS[agent_id][0],'last_day':VISITORS[agent_id][1],'note':'用当前day判断到岛多久；不冒充岛上长期居民。'}}] if agent_id in VISITORS else [])+[{'fact_ref':f'biography:{agent_id}:{i}', 'type':'authored_personal_memory',
             'data':{'memory':value,'scope':'本人往事；不是玩家经历；只在相关话题且适合熟悉程度时提起'}}
            for i,value in enumerate(person['memories'])]
