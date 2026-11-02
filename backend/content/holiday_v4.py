"""V4 object catalogue and action definitions."""
from copy import deepcopy

VERSION = 'chaoxi-holiday-v4'


def local(s):
    return {'zh-CN': s, 'en': s}


def entry(key, name, text):
    return {'id': key, 'name': name, 'text': text}


def op(key, name, kind='read', items=None, **extra):
    return {'id': key, 'name': name, 'kind': kind, 'items': items or [], **extra}


FLOWERS = [entry('daisy', '小雏菊', '白色花瓣围着黄色花心，花茎纤细。'), entry('fern', '蕨类盆景', '叶片舒展，细小的新叶卷在枝头。'), entry('mint', '薄荷', '叶片边缘有细齿，轻轻靠近可以闻到清新的香气。')]
BOOKS = [entry('shore', '沿岸的一天', '清晨，小船靠上码头。有人把绳索绕在木桩上，鞋底留下两道湿痕。\n\n午后，码头安静下来。修船的人把工具收进箱子，坐在阴影里喝了一口水。\n\n傍晚，窗户一扇接一扇亮起来。渡船转过防波堤，最后一道浪贴着岸边散开。'), entry('window', '窗边三则', '有人把一片落叶夹进书里，后来忘记了那天读到哪一页。\n\n咖啡杯在桌上留下一圈浅印。擦桌子的人顺手把花瓶往光里挪了一点。\n\n雨停之后，阳台上的椅子还湿着。客人站着看了一会儿海，说下次再坐。')]
GAMES = [entry('colour', '颜色接龙', '2—4 人。轮流出与桌面同色或同数字的牌；无牌可出时摸牌，先出完者获胜。活动中可以实际游玩。'), entry('puzzle', '数字拼图', '1 人。点击与空格相邻的数字，将 1—8 按顺序排列。可以独自游玩。')]
SEATS = {'restaurant': [entry('window', '临窗海景位', '海面就在窗外。'), entry('indoor', '常规室内位', '靠近室内用餐区。'), entry('sun', '门外阳光位', '阳光照着门外的桌椅。')], 'cafe': [entry('window', '临窗海景位', '透过玻璃可以看见海。'), entry('balcony', '二楼阳台位', '坐在阳台上，吹着海风。'), entry('indoor', '室内普通位', '安静的室内桌位。')]}
MENUS = {'restaurant': [entry('rice', '时蔬盖饭', '米饭配当日蔬菜。'), entry('noodles', '番茄鸡蛋面', '热汤面，配番茄与鸡蛋。'), entry('soup', '菌菇汤', '一小碗清淡的热汤。')], 'cafe': [entry('coffee', '拿铁', '咖啡与牛奶，热饮。'), entry('tea', '柠檬茶', '柠檬清香，冷饮。'), entry('cocoa', '热可可', '温热的可可饮品。')]}

# (id, name, location, main actions, optional appearance day)
OBJECTS = [
    ('rope', '绳结练习台', 'loc_01', [op('guide', '查看绳结示范', items=[entry('reef', '平结示范', '先右压左交叉，再左压右交叉，最后同时拉紧两端。平结适合轻便捆扎，不用于攀爬或承重。')]), op('make', '练习打结', 'steps', steps=['右绳压左绳交叉', '左绳压右绳交叉', '同时拉紧两端'], result='一枚平结完成了，两端对称地伸向两侧。')], None),
    ('sketch', '港边速写桌', 'loc_01', [op('draw', '画一张速写', 'sketch', items=[entry('boat', '小船', '描下船身、桅杆与水面的倒影。'), entry('shore', '海岸', '画出海岸的轮廓和远处的山。'), entry('house', '港边建筑', '勾勒屋顶、窗户和沿岸的小路。')]), op('album', '翻看速写册', items=[entry('morning', '清晨的码头', '一张以小船和系船桩为主的速写，作者在角落记着“起得早，码头还没人”。')])], None),
    ('bench', '观海长凳', 'loc_01', [op('sit', '坐下观海', 'rest')], None),
    ('beach', '沙滩', 'loc_01', [op('walk', '沿水边散步', 'steps', steps=['走到潮线边', '沿着脚印慢慢走', '回到干燥的沙地'], result='你沿潮线走了一段，浪花把身后的脚印渐渐抹平。'), op('shell', '寻找贝壳', items=[entry('clam', '扇形贝壳', '浅色贝壳上有一道道放射状纹路。你看过后把它留在沙地上。'), entry('spiral', '螺旋小壳', '小壳的尖端旋成细细的圈，里面已经没有住客。')]), op('sand', '在沙上画画或写字', 'write')], None),
    ('bonfire_table', '篝火晚会专用桌', 'loc_01', [op('schedule', '查看晚会安排', items=[entry('plan', '篝火晚会', '10月7日 18:30，海边围坐、聊天与告别。请在手机中处理邀约。')]), op('tea', '取一杯热饮', 'snack', result='你倒了一杯热茶，坐到火光旁，杯壁慢慢暖起来。'), op('card', '写一张告别卡', 'write')], 7),
    ('plants', '花草盆景展示架', 'loc_02', [op('browse', '浏览花草盆景', items=FLOWERS)], None),
    ('flowers', '插花工作桌', 'loc_02', [op('tools', '查看花材与工具', items=[entry('kit', '桌上的材料', '小雏菊、尤加利叶、浅口花器和剪刀整齐地放在桌上。')]), op('make', '制作插花', 'craft', items=[entry('white', '白绿桌花', '白色小雏菊配上尤加利叶，放进浅口花器。'), entry('bright', '暖色桌花', '暖色小花配上绿叶，放进小陶瓶。')], steps=['挑选花材', '安排高低与位置', '整理并完成'])], None),
    ('wood_display', '木作展示架', 'loc_02', [op('browse', '浏览木作作品', items=[entry('boat', '木头小船', '浅色木片拼成的小船，船身保留着自然木纹。'), entry('coaster', '方形杯垫', '边缘磨圆的木杯垫，摸起来平滑。')])], None),
    ('wood_work', '木作工作桌', 'loc_02', [op('tools', '查看材料与工具', items=[entry('kit', '拼装材料', '桌上备有预制木片、连接件和砂纸，可以拼成小船或杯垫。')]), op('make', '拼装小木作', 'craft', items=[entry('boat', '木头小船', '船身与桅杆已经连接，木片小船可以稳稳地立在桌上。'), entry('coaster', '木杯垫', '木条排列整齐，边角已经打磨平滑。')], steps=['选择预制木片', '拼合并连接', '打磨边缘并完成'])], None),
    ('shelf', '货架', 'loc_03', [op('browse', '浏览商品', items=[entry('food', '食物', '海盐饼干、果汁和小包装坚果摆在这一层。'), entry('stationery', '文具', '铅笔、便笺和素描本按大小排列。'), entry('daily', '生活用品', '纸巾、毛巾和日常洗漱用品摆在另一侧。')])], None),
    ('photos', '摄影作品展示墙', 'loc_03', [op('browse', '浏览摄影作品', items=[entry('harbor', '第一班船', '林予安拍摄于潮汐港口。那天为了赶第一班船，他提早到了码头，等到船头进入晨光才按下快门。'), entry('street', '午后的巷子', '林予安拍摄于花坊门外。花盆的影子落在墙上，他蹲在路边等了一会儿，让一只路过的猫走出画面。')])], None),
    ('restaurant_menu', '菜单墙', 'loc_04', [op('order', '浏览并点餐', 'order', venue='restaurant', items=MENUS['restaurant'])], None),
    ('restaurant_table', '餐桌', 'loc_04', [op('sit', '入座', 'seat', venue='restaurant'), op('eat', '用餐', 'consume', venue='restaurant'), op('leave', '离座', 'leave', venue='restaurant')], None),
    ('games', '桌游室', 'loc_05', [op('browse', '浏览桌游与玩法', items=GAMES), op('play', '开始单人数字拼图', 'puzzle')], None),
    ('volleyball', '排球室', 'loc_05', [op('rules', '查看场地与规则', items=[entry('court', '场地与练习', '场地中间是球网，地面标有边线。可以独自练习垫球和发球；多人传接球需要至少2人，小场对打需要4人。')]), op('bump', '垫球练习', 'volley'), op('serve', '发球练习', 'volley')], None),
    ('common_room', '公共活动室', 'loc_05', [op('schedule', '查看活动安排', 'schedule'), op('rest', '坐下休息', 'rest')], None),
    ('welcome_table', '欢迎派对专用桌', 'loc_05', [op('card', '查看欢迎卡', items=[entry('welcome', '欢迎来到潮栖岛', '10月1日 18:30，公共活动室欢迎派对。先认识邻居，再挑几处想去的地方。')]), op('snack', '取一份点心', 'snack', result='你拿起一块海盐薄饼，咸味过后是淡淡的麦香。'), op('sign', '在签到册留言', 'write')], 1),
    ('cafe_menu', '饮品菜单', 'loc_06', [op('order', '浏览并点单', 'order', venue='cafe', items=MENUS['cafe'])], None),
    ('books', '读书角', 'loc_06', [op('browse', '浏览书架', items=[entry(b['id'], b['name'], '岛上日常短篇，共三页。') for b in BOOKS]), op('read', '阅读', 'book', items=BOOKS)], None),
    ('postcards', '明信片墙', 'loc_06', [op('browse', '浏览明信片', 'wall', items=[entry('sea', '海岸明信片', '海风吹过码头，希望下次还能赶上这样的晴天。——往日游客'), entry('square', '广场明信片', '在广场坐了一下午，最先记住的是路过的人。——往日游客')]), op('write', '写一张明信片', 'write')], None),
    ('cafe_table', '桌位', 'loc_06', [op('sit', '入座', 'seat', venue='cafe'), op('drink', '享用饮品', 'consume', venue='cafe'), op('leave', '离座', 'leave', venue='cafe')], None),
    ('guidebook', '客房床头度假册', 'guest_room', [op('map', '翻开度假册', 'map')], None),
]
CATALOGUE = {key: {'id': key, 'name': name, 'location_id': lid, 'actions': actions, 'day': day} for key, name, lid, actions, day in OBJECTS}


def action_id(oid, action):
    return 'v4_' + oid + '__' + action


def enrich(systems, locations, residents, manifest):
    template = deepcopy(systems['action_definitions'][0])
    systems['action_definitions'] = []
    systems['affordances'] = []
    systems['stage_recipes'] = []
    systems['activity_recipes'] = []
    for loc in locations:
        if loc['location_id'] == 'loc_02':
            loc['name'] = local('花坊')
            loc['description'] = local('花草盆景、插花与木作工作桌组成一间有生活气息的小花坊。小路通向民宿客房。')
        if loc['location_id'] == 'loc_05':
            loc['description'] = local('广场旁有桌游室、排球室和公共活动室，可以独自练习，也可以约邻居一起活动。')
        loc['interaction_points'] = []
        for obj in CATALOGUE.values():
            if obj['location_id'] != loc['location_id']:
                continue
            loc['interaction_points'].append({'object_id': obj['id'], 'type': 'display', 'name': local(obj['name']), 'description': local('、'.join(a['name'] for a in obj['actions'])), 'renderer_key': 'display'})
            for a in obj['actions']:
                aid = action_id(obj['id'], a['id'])
                d = deepcopy(template)
                d.update(action_id=aid, label=local(a['name']), actor_types=['participant','resident'] if obj['id'] != 'guidebook' else ['participant'],
                         target_types=['object'], min_participants=1, max_participants=20, duration_minutes=0, preconditions={},
                         inputs=[{'input_id':'payload','value_type':'object_command','required':False,'max_length':2000}],
                         consequences=[{'effect_type':'set_object_state','state_key':'result','value':a['name']}])
                d.pop('text_record', None)
                systems['action_definitions'].append(d)
                systems['affordances'].append({'affordance_id':aid+'_here','action_id':aid,'location_ids':[loc['location_id']], 'object_ids':[obj['id']], 'enabled':True,'conditions':{},'permission_keys':[],'capability_keys':[]})
    recipes = [
        ('seaside','一起观海','bench',2,4), ('beach_walk','沿沙滩走走','beach',2,4), ('harbor_sketch','一起画港口','sketch',2,4),
        ('rope_practice','一起练习绳结','rope',2,4), ('flower_arranging','做一份桌花','flowers',2,4), ('woodcraft','拼一件木作','wood_work',2,4),
        ('browse_plants','看看花草与木作','plants',2,4), ('shop_visit','一起逛便利店','shelf',2,4), ('photo_visit','看看摄影作品','photos',2,4),
        ('meal','一起吃顿饭','restaurant_menu',2,4), ('table_game','一起玩颜色接龙','games',2,4),
        ('volley_pass','一起传接排球','volleyball',2,4), ('volley_match','四人排球小场对打','volleyball',4,4),
        ('common_chat','活动室小聚','common_room',2,4), ('coffee','一起喝杯咖啡','cafe_menu',2,4),
        ('reading','一起读一会儿书','books',2,4), ('postcard','一起写明信片','postcards',2,4),
        ('welcome','欢迎派对','welcome_table',1,9), ('bonfire','篝火晚会','bonfire_table',1,9),
    ]
    for rid, name, oid, low, high in recipes:
        obj=CATALOGUE[oid]; aids=[action_id(oid,a['id']) for a in obj['actions']]
        cond={'participant_mode':'required','organizer_agent_ids':list(range(1,9)), 'required_resident_ids':[], 'invitee_role_ids':['guest'],
              'participant_stage_control':True,'auto_emergence':True,'emergence_enabled':True,'experience_scene':True,'fixed_stage_timeline':False,
              'stage_recipe_id':rid+'_stages','start_delay_minutes':15,'expires_after_minutes':30}
        if rid in ('welcome','bonfire'):
            cond.update(fixed_day=obj['day'],fixed_start_minute=1110,organizer_agent_ids=[7],invite_all_residents=True,participant_mode='optional',open_admission_until_end=True,expires_after_minutes=240)
        systems['activity_recipes'].append({'recipe_id':rid,'label':local(name),'location_ids':[obj['location_id']], 'object_ids':[oid], 'action_ids':aids,
            'role_slots':['organizer','guest'],'variant_recipe_ids':[],'min_participants':low,'max_participants':high,'duration_minutes':60 if obj['day'] else 30,
            'complexity':'major' if obj['day'] else 'coordinated','player_facing':True,'conditions':cond})
        systems['stage_recipes'].append({'stage_recipe_id':rid+'_stages','label':local(name),'allowed_action_ids':aids,'terminal_outcomes':['completed','partial','timed_out','not_completed'],
            'max_stages':1,'max_player_choices_per_stage':3,'initial_stage_id':'scene','stages':[{'stage_id':'scene','label':local(name),'kind':'action','confirm_in_place':True,
            'role_goals':{'organizer':'商量接下来做什么','guest':'选择自己的参与方式'},'authority_roles':['organizer','guest'],'authority_actor_types':['participant'],
            'duration_minutes':30,'timeout_outcome':'timed_out','absence_outcome':'not_completed','enter_conditions':{},
            'choices':[{'choice_id':a['id'],'label':local(a['name']),'action_id':action_id(oid,a['id']),'object_id':oid,'inputs':{},'next_stage_id':None,'outcome':'completed'} for a in obj['actions']]}]})
    replacements={'邻里巷与花坊':'花坊','软球':'排球','唱片':'休闲座位','花艺工作桌':'插花工作桌'}
    def clean(value):
        if isinstance(value,str):
            for old,new in replacements.items(): value=value.replace(old,new)
            return value
        if isinstance(value,list): return [clean(x) for x in value]
        if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
        return value
    residents[:]=clean(residents)
