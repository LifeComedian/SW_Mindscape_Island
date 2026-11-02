"""Object feedback and residential scene definitions."""
from copy import deepcopy


def enrich_feedback(systems, places):
    endings = {
        "act_01": "观察牌画着三处地标：灯塔在海湾尽头，旧船影靠近木栈道，转角小路通向岛心广场。你沿着所选方向，在景色中找到了对应的轮廓。",
        "act_02": "港口就在眼前，你们对照观察牌交换了关注的细节：褪色木栏、弯曲的海岸线和停泊小船的倒影。",
        "act_04": "两端绳子在桌上交叉，绕回、收紧后形成一个平结。你们完成了这次桌面演示，可以把绳子松开重新试一次。",
        "act_05": "你把所选景物画成一张小速写：先勾轮廓，再留出海面反光的空白。纸角写着今天的日期，这幅港边小画完成了。",
        "act_06": "你们把各自选中的景物放进同一张画里，一人补上轮廓，另一人留出海面的亮处。桌上多了一张共同完成的港口速写。",
        "act_07": "你在图鉴页留下了所选的贴纸。空白页多了一个海边印记，旁边还留着以后可以继续填写的位置。",
        "act_08": "你在长椅上坐了一会儿。风从海面吹来，远处船身轻轻晃动，近处的浪花没过石阶又退了下去。",
        "act_10": "许玉兰把白色小雏菊、淡紫补血草和绿色尤加利叶摆开，你们按所选的搭配比了比颜色，花材已经备在桌边。",
        "act_11": "你调整了花瓶边几枝花的位置，按所选轮廓整理高低。转动花瓶看一圈，枝叶之间留下了透光的空隙。",
        "act_12": "许玉兰扶住花瓶，你们把选好的花枝依次放入，最后加上尤加利叶。桌上完成了一束白紫相间的小桌花；花束会留在院落桌上。",
        "act_13": "色卡贴在木牌边，你把选中的配色铺在预览板上。木纹透过浅色底面显出来，可以再选另一张比较。",
        "act_14": "木片按所选形状在桌上拼好，接缝处逐一对齐，一个小摆件完成了。它现在摆在工艺桌边。",
        "act_15": "你停在长椅旁，按自己的选择坐下、看看木纹，或让双手放松片刻。院子里的光慢慢移过椅背。",
        "act_17": "陈惠芬把三张零食卡放在柜台：原味薄饼清淡、海盐脆片偏咸香、蜂蜜小饼偏甜。你们对照所选口味挑出了想试的那张。",
        "act_18": "柜台上的口味卡翻开了：A 是原味薄饼，B 是海盐脆片，C 是蜂蜜小饼。你可以把刚才的选择和说明对照看看。",
        "act_20": "谜底揭开：这张旧纸套原来装的是短途渡船上的薄饼。船形图案提示旅途，背面的空白方便乘客记下返航时刻。",
        "act_23": "配色卡并排摆在镜子边。你和沈安按所选方案搭配好颜色，完成了一张今日穿搭配色卡。",
        "act_24": "你们按选定方式站到取景框前，调整了画面边缘。快门响过，留下的是这次虚拟取景的文字留念。",
        "act_25": "林若岚把菜单卡翻到搭配页：清爽可以选蔬菜与清汤，暖胃可以选热汤和软面，少量尝新则把两种小份放在一起比较。",
        "act_26": "你选中的说明卡放到了餐盘旁，店员可以据此了解你的口味偏好。餐点的选择仍由你自己决定。",
        "act_27": "两张小份口味卡摆在一起：清淡版保留食材本味，浓味版突出酱汁。你说出了自己的选择，这一轮比较结束了。",
        "act_28": "你们对照卡片比较：脆口蔬菜配软面形成口感反差，浅色汤与绿色叶菜使颜色更清楚。偏好不同也可以各选各的。",
        "act_29": "你按所选风格把餐具放好，杯子留在伸手方便的位置，盘边空出一块位置。你的临窗座位布置好了。",
        "act_30": "你们一起摆好餐垫、盘子和杯子，比较了从两侧看过去的样子。最后保留了所选的桌面方案。",
        "act_31": "答案卡翻开：番茄属于茄科，原产于南美洲。它可以与鸡蛋或清汤搭配；这张卡没有需要记住的考试答案。",
        "act_32": "你们完成了这一小轮互动：按选定方式抛球、接球或看过示范，球回到了收纳篮里。可以休息，也可以再玩。",
        "act_34": "你们把桌游卡摆好，轮流放下一张颜色卡，按相同颜色接续。最后一张接上后，这轮简化合作桌游完成了。",
        "act_36": "软球按约定的传递方式绕过这一轮，最后回到起点。你们把球放回篮里，结束了这次小练习。",
        "act_38": "你们翻看同一张曲目卡，用所选方式交换了联想。卡片留在桌边，可以带着不同的感受继续逛岛。",
        "act_39": "椅子和矮桌按所选用途摆好了。中间留出通行空间，广场多了一个可以坐下歇脚的角落。",
        "act_42": "风味卡在杯垫旁展开，你们圈出所选的描述词。它表达的是此刻的偏好；之后也可以换一种词来描述。",
        "act_44": "书页停在选中的片段。你们按自己的方式读过、分享或安静坐了一会儿，书签留在了这一页。",
        "act_46": "你们选好明信片主题，把一句海边问候写在空白处。卡片上留下这次共同选择的句子。",
        "act_47": "窗框、海面和桌沿排成了画面的几条线，你们按选定构图完成了一次虚拟取景。此刻的景色留在文字日志里。",
    }
    sources = {a['id']: a for a in places['actions']}
    for action in systems['action_definitions']:
        source = action['action_id'].split('_choice_')[0]
        if source in endings:
            action['consequences'].append({'effect_type': 'set_object_state', 'state_key': 'result', 'value': endings[source]})
        if source in sources and action.get('text_record'):
            # Text itself is saved to the correct visibility-aware record table.
            continue
        if action['action_id'].startswith(('welcome_', 'bonfire_')):
            label = action['label']['zh-CN']
            party = '欢迎派对' if action['action_id'].startswith('welcome') else '篝火晚会'
            outcomes = {
                '点心桌边': '你在点心桌旁坐下，面前是薄饼、热茶和空杯。大家为你留出了一个位置。',
                '看看花与木托盘': '白紫色桌花摆在浅木托盘上，尤加利叶从花瓶边垂下来。你走近看了看这些细节。',
                '了解六个地点': '桌上的地图标出港口、民宿、便利店、餐馆、广场和旧书咖啡馆；客房在民宿旁，住宅区在广场另一侧。',
                '坐在外侧旁观': '你在灯光稍暗的外侧坐下，可以看到大家，也保留一段安静的距离。',
                '选择桌花配色': '你选了白色小雏菊配淡紫补血草，把配色卡放到桌花旁。',
                '为点心选一个预制名称': '你从名称卡中挑出“海风小饼”，把小牌立在点心盘旁。',
                '拼出小岛的一角': '你把海岸、木桥和树影三块卡片接在一起，桌面上拼出小岛的一角。',
                '记下想去的地点': '你在便签上圈了旧书咖啡馆，明天可以去看看，也可以随时改变主意。',
                '在交谈区坐下': '你在篝火旁选了一个位置，火光照着杯沿。可以打开讨论和在场居民聊聊。',
                '看看热饮桌': '热饮桌上放着茶壶和纸杯。你走到桌边，给自己留了一个拿杯子的位置。',
                '看看纪念桌': '纪念桌上摊着空白明信片、彩色笔和海岸图案卡，供大家自由取用。',
                '选择海边主题卡': '你挑出一张画着海岸线的主题卡，放在自己面前。',
                '留一句预制道别': '你留下了一句：“谢谢这几天的陪伴，愿下一段旅途也有好天气。”',
                '向在场居民道别': '你向在场的居民道了晚安，沿着广场边的小路慢慢离开热闹的人群。',
            }
            text = outcomes.get(label, f'你在{party}中选择了“{label}”，为自己留下一段放松的时间。可以继续下一环节，或打开日志回看已经发生的事。')
            action['consequences'].append({'effect_type': 'set_object_state', 'state_key': 'result', 'value': text})
    sample = deepcopy(systems['action_definitions'][0])
    sample.update(action_id='view_table_games', label={'en': '查看这里有什么桌游', 'zh-CN': '查看这里有什么桌游'},
        actor_types=['participant'], min_participants=1, duration_minutes=0, inputs=[], text_record=None, preconditions={},
        consequences=[{'effect_type': 'set_object_state', 'state_key': 'result', 'value': '架子上有 UNO、德国心脏病和图形拼图卡。UNO 按颜色或数字接牌；德国心脏病要找出桌面上恰好五个相同水果；图形卡可以独自解，也可以查看提示。想约居民一起玩，可以在手机“邀约”中发起活动。'}])
    systems['action_definitions'].append(sample)
    systems['affordances'].append({'affordance_id': 'table_games_view', 'action_id': 'view_table_games', 'location_ids': ['loc_05'], 'object_ids': ['obj_21'], 'enabled': True, 'conditions': {}, 'permission_keys': [], 'capability_keys': []})


def add_homes(locations, coords, icons, manifest, residents, systems):
    local = lambda text: {'en': text, 'zh-CN': text}
    room = deepcopy(locations[1])
    room.update(location_id='guest_room', name=local('民宿客房'), description=local('你这七天的住处。窗边有日记本，床头放着小岛地图。每天可以从这里慢慢出发。'), connected_location_ids=['loc_02'], interaction_points=[])
    inn = locations[1]
    room['interaction_points'] = [o for o in inn['interaction_points'] if o['object_id'] == 'obj_10']
    inn['interaction_points'] = [o for o in inn['interaction_points'] if o['object_id'] != 'obj_10']
    inn['connected_location_ids'].append('guest_room')
    homes = deepcopy(room)
    homes.update(location_id='residential', name=local('岛民住宅区'), description=local('沿着树荫小路是一排居民住处。门牌上写着姓名，家中私人空间不对游客开放。居民清晨从这里出发，傍晚回来休息。'), connected_location_ids=['loc_05'], interaction_points=[])
    locations[4]['connected_location_ids'].append('residential')
    locations.extend([room, homes]); coords.update(guest_room=[130,80], residential=[780,600]); icons.extend(['homes','homes'])
    manifest['start_location_id'] = 'guest_room'; manifest['experience']['rest_location_id'] = 'guest_room'
    for affordance in systems['affordances']:
        if 'obj_10' in affordance['object_ids']: affordance['location_ids'] = ['guest_room']
    for person in residents:
        work = person['home_location_id']; aid = person['agent_id']
        person['home_location_id'] = 'residential'
        blocks = [(540,569,'residential','在家吃早饭，准备出门'), (570,719,work,'开始上午的日常工作'), (720,779,'loc_04','午间吃饭休息'), (780,959,work,'继续照看自己的日常事务'), (960,1049,['loc_01','loc_02','loc_03','loc_06'][aid%4],'按兴趣安排一段自由时间'), (1050,1139,'loc_04' if aid%2 else 'loc_05','吃晚饭，散步'), (1140,1200,'residential','回家整理今天的东西，准备休息')]
        routed = [blocks[0]]
        for start, end, lid, activity in blocks[1:]:
            previous = routed[-1][2]
            if previous != lid and previous != 'loc_05' and lid != 'loc_05':
                routed.append((start, start+4, 'loc_05', '经过广场，前往下一处安排'))
                start += 5
            routed.append((start, end, lid, activity))
        blocks = routed
        special = [b for b in person['schedule'] if b.get('days')]
        person['schedule'] = [{'state_id': f'resident_{aid}_routine_{n}', 'start_minute': start, 'end_minute': end, 'location_id': lid, 'activity': local(activity), 'goal': person['goals'][0]} for n,(start,end,lid,activity) in enumerate(blocks)] + special
        person['autonomy']['free_time_state_ids'] = [b['state_id'] for b in person['schedule']]
