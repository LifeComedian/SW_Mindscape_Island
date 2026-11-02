"""V3 interactions and invitation scenes."""
from copy import deepcopy


def local(text):
    return {"zh-CN": text, "en": text}


def enrich(systems, locations, residents, source):
    names = [r['name'] for r in residents]
    actions = {a['action_id']: a for a in systems['action_definitions']}
    # Recipes use shared objects; availability is checked at runtime.
    for recipe in systems['activity_recipes']:
        conditions = recipe['conditions']
        conditions['experience_scene'] = True
        conditions['fixed_stage_timeline'] = False
        if recipe['recipe_id'] in ('welcome', 'bonfire'):
            continue
        conditions.update(required_resident_ids=[], organizer_agent_ids=list(range(1, 9)),
                          participant_stage_control=True, auto_emergence=True, emergence_enabled=True)
        recipe['min_participants'] = 2
        recipe['max_participants'] = 4
        title = recipe['label']['zh-CN']
        for name in names:
            title = title.replace('和' + name, '').replace(name, '')
        recipe['label'] = local(title.strip(' 的·，'))
    for action in actions.values():
        if action['action_id'].startswith(('welcome_', 'bonfire_')):
            continue
        # Reading and making are shared affordances. Private authored journals
        # remain participant-owned; NPCs write through their own memory channel.
        if not action.get('text_record'):
            action['actor_types'] = ['participant', 'resident']
        action['min_participants'] = 1
        action['preconditions'].pop('requires_stage', None)
        if action['duration_minutes'] == 0 and not action.get('inputs'):
            action['duration_minutes'] = 2
        text = action['label']['zh-CN']
        for name in names:
            text = text.replace('和' + name, '').replace(name, '')
        action['label'] = local(text.strip(' 的·，'))
        # Feedback describes the object/result, never invents a named companion.
        for effect in action['consequences']:
            if effect.get('effect_type') == 'set_object_state' and isinstance(effect.get('value'), str):
                result = effect['value']
                for name in [*names, '陈惠芬', '沈安', '林若岚']:
                    result = result.replace('你和'+name, '你').replace(name+'把', '你把').replace(name+'扶住花瓶，', '').replace(name, '')
                effect['value'] = result.replace('你们', '你').replace('各自选中', '选中').replace('一人补上轮廓，另一人留出', '补上轮廓，留出').replace('共同完成', '完成')
    # Retain stage IDs for old records; hide redundant choices.
    redundant = set()
    for entry in source['actions']:
        choices = entry['choices']
        if any('先' in c for c in choices) or entry['id'] in ('act_03', 'act_09', 'act_33', 'act_35'):
            aid = entry['id'] + '_choice_1'
            if aid in actions:
                actions[aid]['label'] = local(entry['name'])
                redundant.update(entry['id'] + f'_choice_{i}' for i in range(2, len(choices)+1))
    for affordance in systems['affordances']:
        if affordance['action_id'] in redundant or affordance['action_id'] == 'view_table_games':
            affordance['enabled'] = False
    # Variants with exactly the same outcome are one action, not three choices.
    outcomes = set()
    for aff in systems['affordances']:
        action = actions[aff['action_id']]
        effects = tuple(str(e.get('value')) for e in action['consequences'] if e.get('state_key') == 'result')
        source_id = action['action_id'].split('_choice_')[0]
        signature = (source_id, effects)
        if effects and not action.get('inputs'):
            if signature in outcomes:
                aff['enabled'] = False
                redundant.add(action['action_id'])
            else:
                outcomes.add(signature)
                entry = next((e for e in source['actions'] if e['id'] == source_id), None)
                if entry:
                    text = entry['name']
                    for name in names:
                        text = text.replace('和'+name, '').replace('与'+name, '').replace(name, '')
                    action['label'] = local(text.strip(' 的·，'))
        if source_id == 'act_34':
            action['label'] = local('整理桌游卡牌')
            for e in action['consequences']:
                if e.get('state_key') == 'result':
                    e['value'] = '你把不同颜色的卡牌分好，放到桌边。牌已经准备好了；参加桌游活动后，可以和到场的人真正玩一局颜色接龙。'
    for recipe in systems['stage_recipes']:
        for stage in recipe['stages']:
            stage['choices'] = [c for c in stage['choices'] if c['action_id'] not in redundant]
        if recipe['stage_recipe_id'] not in ('welcome_stages', 'bonfire_stages'):
            recipe['stages'] = recipe['stages'][:1]
            recipe['max_stages'] = 1
            for choice in recipe['stages'][0]['choices']:
                choice['next_stage_id'], choice['outcome'] = None, 'completed'
    table = next(a for a in systems['affordances'] if a['action_id'] == 'act_33_choice_1')
    template = deepcopy(actions['act_33_choice_1'])
    for key, label, result in [
        ('table_catalog', '查看这里有哪些桌游', '柜子里有 UNO、德国心脏病和图形拼图。可以翻看规则；想一起玩时，到手机邀约中约几个人。'),
        ('table_uno_rules', '翻看 UNO 规则', '轮流出与桌面同色或同数字的牌；没有可出的牌就摸一张。最先出完手牌的人获胜。本岛的活动提供简化的颜色接龙小游戏。'),
        ('table_halli_rules', '翻看德国心脏病规则', '轮流翻开水果牌。当桌面某一种水果正好有五个时抢铃。这里可以阅读规则，当前活动小游戏先提供颜色接龙。'),
    ]:
        item = deepcopy(template)
        item.update(action_id=key, label=local(label), duration_minutes=1, inputs=[], preconditions={},
                    consequences=[{'effect_type': 'set_object_state', 'state_key': 'result', 'value': result}])
        systems['action_definitions'].append(item)
        aff = deepcopy(table)
        aff.update(affordance_id=key+'_here', action_id=key, enabled=True)
        systems['affordances'].append(aff)
    for party, items in {
        'welcome': [
            ('snack', '到点心桌尝一块海盐薄饼', '桌上有海盐薄饼、蜂蜜小饼和热茶。你拿了一块薄饼，掰开时掉下几粒酥屑，咸味过后是淡淡的麦香。空杯就在茶壶旁，可以边吃边和大家聊。'),
            ('map', '翻看桌上的小岛地图', '港口在海湾边，民宿和花坊相邻；穿过广场可以去便利店、餐馆和旧书咖啡馆。地图上还标着你的客房和居民住宅区。想认识哪位邻居，可以在下面选名字打个招呼。'),
            ('flowers', '看看今晚的桌花', '浅木托盘上放着一束白色小雏菊，淡紫补血草和尤加利叶从两侧伸出来。瓶子不高，坐在桌边聊天时不会挡住彼此的视线。'),
        ],
        'bonfire': [
            ('tea', '倒杯热茶，在火边坐下', '你从壶里倒出热茶，杯壁慢慢暖起来。木柴轻轻噼啪作响，空椅子围成一个松散的半圆，大家留着地方等人坐下。'),
            ('card', '挑一张海岸明信片', '纪念桌上有灯塔、木栈道和广场三种图案。你拿起一张海岸明信片，背面仍是空白。可以在聊天时说说这几天最想记住的片段，也可以把这张卡留作纪念。'),
            ('quiet', '听一会儿火声和大家的闲聊', '你把椅子往后挪了一点。风声、火声和交谈声混在一起，有人整理杯子，有人还在说白天的见闻。你在这里安静坐了一会儿。'),
        ],
    }.items():
        recipe = next(r for r in systems['activity_recipes'] if r['recipe_id'] == party)
        for key,label,result in items:
            aid = f'gathering_{party}_{key}'
            item = deepcopy(template)
            item.update(action_id=aid,label=local(label),duration_minutes=2,inputs=[],preconditions={'requires_stage':True},
                consequences=[{'effect_type':'set_object_state','state_key':'result','value':result}])
            systems['action_definitions'].append(item)
            aff=deepcopy(table)
            aff.update(affordance_id=aid+'_here',action_id=aid,enabled=True,location_ids=recipe['location_ids'],object_ids=recipe['object_ids'][:1])
            systems['affordances'].append(aff)
    # Accepted plans and travel take precedence over work schedules.
    for resident in residents:
        resident['autonomy']['free_time_state_ids'] = [s['state_id'] for s in resident['schedule']]
        resident['safety_rules'] = [local('尊重对方选择，不代替玩家同意；被问及时说明自己是 AI 角色。')]
    for location in locations:
        for obj in location['interaction_points']:
            if obj['object_id'] in ('welcome_table', 'bonfire_table'):
                obj['description'] = local('聚会准备的小桌子。活动到场后会进入独立的聚会场景。')
