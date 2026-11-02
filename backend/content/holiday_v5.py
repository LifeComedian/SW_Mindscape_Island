"""V5 experience rules using V4 object and action IDs."""
VERSION = 'chaoxi-holiday-v5'

def enrich(systems, locations, residents, manifest):
    manifest['experience']['behavior_audit_version']='holiday-opportunities-v5'
    for definition in systems['action_definitions']:
        minutes = definition['duration_minutes']
        definition['duration_minutes'] = ((minutes + 4) // 5) * 5


    # Work preferences do not reserve time or resources.
    routines = {
        1: [(540,570,'residential','吃早餐，准备出门'),(570,690,'loc_02','在木作台整理材料、制作小件，可以停下来聊聊'),(690,810,'loc_04','吃饭休息'),(810,960,'loc_02','按自己的进度做木作，也可以临时休息'),(960,1080,'loc_01','散步、看看海边的木料'),(1080,1140,'loc_04','晚饭与闲聊'),(1140,1201,'residential','回家休息')],
        2: [(540,570,'residential','早餐后出门'),(570,660,'loc_02','浇花与整理花架'),(660,720,'loc_02','闲时摆弄花草，可以一起插花'),(720,810,'loc_04','午餐休息'),(810,930,'loc_02','照看花坊，安排可以调整'),(930,1080,'loc_06','喝茶读书、休息'),(1080,1140,'loc_05','晚饭后散步'),(1140,1201,'residential','回家休息')],
        3: [(540,570,'residential','吃早餐'),(570,690,'loc_03','整理店内货架'),(690,810,'loc_04','午餐和休息'),(810,930,'loc_03','照看店铺，空闲时可以暂时离开'),(930,1080,'loc_02','逛花坊，安排自由时间'),(1080,1140,'loc_05','晚饭和闲逛'),(1140,1201,'residential','回家休息')],
        5: [(540,570,'residential','早餐后出门'),(570,720,'loc_03','整理和挑选照片'),(720,810,'loc_04','吃饭休息'),(810,960,'loc_01','按光线和兴趣拍照，可临时改变计划'),(960,1080,'loc_06','喝咖啡，看看今天的照片'),(1080,1140,'loc_05','晚饭后走走'),(1140,1201,'residential','回家休息')],
        4: [(540,570,'residential','吃早餐'),(570,690,'loc_04','少量备餐，闲时可以聊聊或出去休息'),(690,810,'loc_04','午餐饭点：厨房比较忙，可考虑短暂休息或换个时间'),(810,930,'loc_06','午后休息、喝点东西'),(930,1050,'loc_04','准备晚餐，进度可以调整'),(1050,1140,'loc_04','晚餐饭点：优先照顾餐馆，也可以自行决定腾出时间'),(1140,1201,'residential','收工回家休息')],
        6: [(540,570,'residential','吃早餐'),(570,660,'loc_06','准备咖啡和当天的书架'),(660,720,'loc_06','照看咖啡馆，可以边闲聊边休息'),(720,810,'loc_04','午餐休息'),(810,930,'loc_06','下午照看咖啡馆，安排可以调整'),(930,1080,'loc_01','海边散步，换换心情'),(1080,1140,'loc_05','吃晚饭、休息'),(1140,1201,'residential','回家休息')],
        7: [(540,570,'residential','早餐后出门'),(570,690,'loc_05','整理公共活动室'),(690,810,'loc_04','午餐休息'),(810,930,'loc_05','准备活动材料，可以抽空参加别的事'),(930,1080,'loc_03','逛店、看看大家'),(1080,1140,'loc_05','在广场休息和聊天'),(1140,1201,'residential','回家休息')],
        8: [(540,570,'residential','吃早餐'),(570,690,'loc_01','整理绳索、照看港口'),(690,810,'loc_04','午餐休息'),(810,930,'loc_01','港口日常事务，闲时可以离开'),(930,1080,'loc_05','自由活动或练球'),(1080,1140,'loc_01','晚饭后看看海边'),(1140,1201,'residential','回家休息')],
    }
    local=lambda text:{'zh-CN':text,'en':text}
    for person in residents:
        aid=person['agent_id']
        special=[b for b in person['schedule'] if b.get('days')]
        routed=[]
        for start,end,lid,activity in routines[aid]:
            if routed and routed[-1][2]!=lid and routed[-1][2]!='loc_05' and lid!='loc_05':
                previous=routed.pop()
                if aid==4 and '饭点' in previous[3]:
                    routed.append(previous)
                    routed.append((start,start+5,'loc_05','经过广场，前往下一处安排'))
                    start+=5
                else:
                    routed.append((previous[0],start-5,previous[2],previous[3]))
                    routed.append((start-5,start,'loc_05','经过广场，前往下一处安排'))
            routed.append((start,end,lid,activity))
        person['schedule']=[{'state_id':f'resident_{aid}_flex_{n}', 'start_minute':start, 'end_minute':end-1,
            'location_id':lid, 'activity':local(activity), 'goal':person['goals'][0]}
            for n,(start,end,lid,activity) in enumerate(routed)]+special
        person['autonomy']['free_time_state_ids']=[b['state_id'] for b in person['schedule']]

    for location in locations:
        for point in location['interaction_points']:
            if point['object_id']=='guidebook':point['description']=local('岛屿地点、居民介绍与相约玩法。打开即可阅读。')
