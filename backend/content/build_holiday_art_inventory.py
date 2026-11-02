"""Generate an art inventory from the current content."""
import argparse
import json
from collections import Counter
from pathlib import Path
from content.holiday_v4 import CATALOGUE, VERSION, MENUS, SEATS, FLOWERS, BOOKS


def generate(pack: Path, output: Path):
    read=lambda name:json.loads((pack/f'{name}.json').read_text(encoding='utf-8'))
    locations=read('locations')['locations'];residents=read('residents')['residents']
    systems=read('systems')
    if 'systems' in systems:systems=systems['systems']
    rows=[]
    def add(key,group,name,brief,priority='P1',ratio='16:9',reuse=''):
        rows.append(dict(id=key,category=group,name=name,brief=brief,priority=priority,ratio=ratio,reuse=reuse,status='待制作与接入'))
    add('map.island','地图','全岛俯视底图','覆盖港口、花坊、便利店、餐馆、广场与三个室内房间、咖啡馆、民宿和住宅区；道路与当前 map.json 节点一致。地点名称、热区和角色由代码绘制，不烘焙文字。','P0','10:7','客房度假册直接复用缩略图')
    for loc in locations:
        lid=loc['location_id'];name=loc['name']['zh-CN']
        add('location.'+lid,'地点场景',name+'主场景',loc['description']['zh-CN']+'。按互动点清单安排可点击位置，保留人物站位和界面留白。','P0')
        add('map-building.'+lid,'地图标识',name+'建筑剪影/入口','与主场景和俯视地图一致；透明背景，不包含角色、文字或被删除的物品。','P1','1:1')
    for p in residents:
        rid=str(p['agent_id']);name=p['name'];role=p['role']['zh-CN']
        add('resident.'+rid+'.portrait','人物',name+'基础头像',role+'；参考本版公开角色背景确定造型，日常生活气质。','P0','1:1','手机动态、邀约、任务署名及日志')
        add('resident.'+rid+'.closeup','人物',name+'对话半身立绘','同一角色造型，透明背景，中性自然表情，手势不绑定特定活动。','P0','3:4','单独交谈、多人活动、欢迎及告别')
        add('resident.'+rid+'.map','人物',name+'地图小人','与头像服饰一致的全身小人，透明背景，缩小后轮廓仍清晰。','P1','2:3')
        for emotion in ('微笑','认真倾听','思考','惊讶'):
            add('resident.'+rid+'.expression.'+emotion,'人物表情',name+'·'+emotion,'对话半身立绘的表情变化，保持五官、发型和衣服一致。','P2','3:4','复用基础立绘构图')
    add('participant.map','人物','玩家地图小人','中性的度假旅客轮廓，透明背景；不预设玩家真实长相或性别。','P1','2:3')
    for oid,obj in CATALOGUE.items():
        detail='；'.join(a['name'] for a in obj['actions'])
        day=f'仅10月{obj["day"]}日出现。' if obj['day'] else ''
        add('object.'+oid,'互动点背景',obj['name'],day+'二级弹窗中的场景特写，支持：'+detail+'。物品本体清晰，不画死操作选项和按钮。','P0',reuse='可由对应地点大图裁切；若视角不成立则单独绘制')
        add('object-hotspot.'+oid,'互动点标识',obj['name']+'透明物件层',day+'在地点场景中对应同一物体；派对桌必须独立成层，不能永久画进底图。','P1','1:1','与互动点特写保持造型一致')
    extra={
        'rope': [('reef-1','平结第一步','右绳压左绳，清楚画出交叉关系'),('reef-2','平结第二步','左绳压右绳，保持两根绳颜色一致'),('reef-3','平结完成','两端拉紧后的正确平结；与前两帧连续')],
        'sketch':[('boat','小船速写参考','港口小船'),('shore','海岸速写参考','海岸轮廓和远山'),('house','港边建筑速写参考','屋顶、窗户与沿岸道路'),('morning','清晨的码头速写页','小船和系船桩；作者说明使用可读的界面文字')],
        'beach':[('clam','扇形贝壳特写','浅色、放射状纹路'),('spiral','螺旋小壳特写','空壳、细小螺旋')],
        'flowers':[('kit','插花材料俯视','小雏菊、尤加利叶、剪刀、浅口花器与暖色花材'),('white','白绿桌花成品','白雏菊与尤加利叶，浅口花器'),('bright','暖色桌花成品','暖色小花、绿叶、小陶瓶')],
        'wood_work':[('kit','木作材料俯视','预制木片、连接件、砂纸'),('boat','木头小船成品','浅色木纹船身与桅杆'),('coaster','木杯垫成品','排列整齐的木条与磨圆边角')],
        'shelf':[('food','食物货架分区','海盐饼干、果汁、小包装坚果'),('stationery','文具货架分区','铅笔、便笺、素描本'),('daily','生活用品货架分区','纸巾、毛巾、洗漱用品；不出现种子')],
        'photos':[('harbor','摄影作品：第一班船','晨光中的港口渡船；与林予安的配套故事一致'),('street','摄影作品：午后的巷子','花坊门外、花盆投影；故事中猫已走出画面，不把猫作为主角')],
        'games':[('colour','颜色接龙盒面','原创颜色接龙桌游盒，不使用商业游戏商标'),('puzzle','数字拼图盒面','原创数字拼图盒；实际数字块由代码绘制')],
        'postcards':[('sea','海岸明信片正面','潮汐港口与海面'),('square','广场明信片正面','公共广场日常'),('blank','空白明信片纸面','预留正文、日期区域，不烘焙文字')],
        'welcome_table':[('snack','欢迎点心特写','海盐薄饼，置于第一天欢迎桌'),('card','欢迎卡与签到册','空白卡纸和展开的签到册，文字由代码叠加')],
        'bonfire_table':[('tea','告别热茶特写','火光旁一杯热茶'),('card','告别卡纸面','可写字的空白卡纸，与第七天海边夜色一致')],
    }
    for oid,items in extra.items():
        for item,name,brief in items:add(f'detail.{oid}.{item}','交互内容与反馈',name,brief+'。','P1','4:3')
    for f in FLOWERS:add('detail.plants.'+f['id'],'交互内容与反馈',f['name']+'特写',f['text'],'P1','4:3')
    for venue,items in MENUS.items():
        for item in items:add('menu.'+venue+'.'+item['id'],'点单缩略图',item['name'],item['text']+' 不画价格和购买按钮。','P1','1:1','菜单购物车及用餐反馈可复用')
    for venue,seats in SEATS.items():
        for seat in seats:add('seat.'+venue+'.'+seat['id'],'座位视角',('餐馆' if venue=='restaurant' else '咖啡馆')+'·'+seat['name'],seat['text']+' 无固定人物；共餐时按实际参与人叠加立绘。','P1',reuse='点单座位预览、入座以及多人用餐场景')
    for b in BOOKS:add('book.'+b['id'],'阅读素材',b['name']+'封面','日常短篇书籍封面；标题与正文使用前端文字排版，不让图像模型生成长文字。','P1','3:4')
    for key,name,brief in [
        ('welcome-wide','欢迎派对全景','公共活动室傍晚布置，欢迎桌、点心、座椅。'),
        ('welcome-speech','欢迎致辞镜头','社区负责人讲话的位置；人物单独叠加。'),
        ('welcome-chat','欢迎派对围坐镜头','用于选择任意居民交谈，保留立绘位置。'),
        ('bonfire-wide','篝火晚会全景','第七日海边夜景、篝火、座位与专用桌。'),
        ('bonfire-chat','篝火围坐镜头','暖火光与夜海，方便任意居民交谈。'),
        ('bonfire-goodbye','告别收束镜头','晚会结束时的海岸与渐远灯火，保留文案区域。')]:
        add('activity.'+key,'主线活动',name,brief,'P0')
    for key,name,brief in [
        ('object','物品弹窗通用底层','用对应互动点图片做主要背景，纸面承载反馈。'),
        ('phone','手机动态与邀约','共用手机外框与浅色内容底纹；正文区域保留纯净。'),
        ('tasks','任务与安排','手册或日程纸面，状态、数量、日期由代码排版。'),
        ('menu','菜单弹窗','简洁度假手册底纹，沿用现有精简功能。'),
        ('journal','登岛日志','旅行笔记纸面，与速写及作品记录兼容。'),
        ('dialogue','普通对话','复用当前地点背景，叠加半身立绘；对话框单独设计。'),
        ('day-transition','每日过场','客房晨光通用图，10月2—7日的日期动态叠加。'),
        ('ending','七日体验结束','岛屿远景或告别海岸，承接问卷入口，世界不可继续操作。'),
        ('study','研究流程页','中性浅色岛屿装饰，共用同意、问卷、两份结果、反馈与完成页；不把心理结论画入图片。')]:
        add('ui.'+key,'界面背景与装饰',name,brief,'P1',reuse='优先CSS/矢量边框＋已有场景图，不要求每个弹窗独立生成整张图')
    for lid in ('loc_01','loc_02','loc_03','loc_04','loc_05','loc_06','guest_room','residential'):
        name=next(l['name']['zh-CN'] for l in locations if l['location_id']==lid)
        add('evening.'+lid,'后续时间变化',name+'傍晚/夜色版本','优先用基础场景调光派生，保持物件位置和热区不变。','P2')
    ids=[r['id'] for r in rows];assert len(ids)==len(set(ids))
    output.parent.mkdir(parents=True,exist_ok=True)
    payload={'world_version':VERSION,'source':'当前 v4 内容包与交互定义；未读取旧美术提示词','counts':dict(Counter(r['priority'] for r in rows)),'assets':rows,
             'activities':[{'id':r['recipe_id'],'name':r['label']['zh-CN'],'people':[r['min_participants'],r['max_participants']],'background':r['object_ids'][0]} for r in systems['activity_recipes']]}
    output.with_suffix('.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['潮栖岛 v4：新的插画与美术素材清单','日期：2026-10-10；状态：待制作与接入。这里是美术需求，不是已生成的素材。',
        '来源：当前 v4 游戏内容和交互定义；没有沿用旧版美术 prompt。',
        '范围：8个地点、8名居民、22个互动点、42个主要交互动作、17类普通邀约及2场固定主线活动。',
        'P0：第一批，建立整体世界与核心互动场景。P1：第二批，内容特写与反馈。P2：扩展表情和时间变化。',
        '条目数量代表素材用途，不能直接当作生成图片数量：裁切、透明分层、缩略图和共享底纹应优先复用。',
        '所有普通邀约活动均不绑定固定NPC；角色与背景分层。派对桌不永久烘焙在地点背景中。',
        '只有现有界面的部分 data-art-slot 占位已存在；本表中的完整 ID 是下一阶段的资源命名与接入计划。',
        '文字、按钮、角标、数字牌、拼图块、游戏目标区、玩家速写和可点击地图热区由代码绘制，不需要生成含文字的位图。',
        '不需要：海岸观察牌、贝壳观察盘、旧广告桌、公开留言板、配色台、取景框、香气盒、软球圈、品鉴台、留言册、柜台、种子、货币/背包图标、养护卡、制作照片和唱片。',
        '建议母版：场景2560×1440，地图2000×1400，头像1024×1024，半身立绘1536×2048，物品图至少1024像素。背景保留安全裁切区；透明资产导出PNG/WebP。',
        '风格、配色、角色外观仍由下一阶段统一定稿；先做一张地点和一名居民样张，再批量生产。','',
        '一、地点与交互动作（从当前代码生成）']
    for loc in locations:
        lines.append('\n'+loc['name']['zh-CN']+' ['+loc['location_id']+']')
        objs=[o for o in CATALOGUE.values() if o['location_id']==loc['location_id']]
        if not objs:lines.append('  暂无互动点；住宅和居民移动仍需要场景与人物素材。')
        for o in objs:lines.append('  '+o['name']+('（仅第'+str(o['day'])+'天）' if o['day'] else '')+'：'+'；'.join(a['name'] for a in o['actions']))
    lines+=['','二、具体素材清单']
    for category in dict.fromkeys(r['category'] for r in rows):
        lines+=['','【'+category+'】']
        for r in rows:
            if r['category']==category:lines+=['  '+r['priority']+' | '+r['id']+' | '+r['name']+' | '+r['ratio'],'    '+r['brief']+(' 复用：'+r['reuse'] if r['reuse'] else '')]
    lines+=['','三、邀约活动背景复用关系（场景与演员分离）']
    for a in payload['activities']:
        lines.append(f"  {a['name']} [{a['id']}]：{a['people'][0]}—{a['people'][1]}人；复用 {CATALOGUE[a['background']]['name']} 场景；实际到场角色动态叠加。")
    lines+=['','补充：普通邀约无需预画全部剧情分支。NPC可基于现场物品提出建议，对话和可执行动作仍通过游戏状态校验。',
            '多人吃饭与咖啡使用座位视角、餐饮缩略图及角色立绘组合；桌游、排球用场景底图与代码小游戏组合。',
            '木作展示架复用木作成品图；公共广场总览和桌游室/排球室/公共活动室弹窗图应保持空间关系。',
            '统计：'+str(len(rows))+'个素材用途；'+', '.join(f'{k} {v}' for k,v in payload['counts'].items())+'。可复用用途不重复委托绘图。']
    output.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'assets':len(rows),**payload['counts']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('pack',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();print(generate(args.pack,args.output))
