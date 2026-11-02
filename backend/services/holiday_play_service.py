"""Validate workshop results before committing actions."""
from math import isfinite
from services.holiday_object_service import fail

FLOWERS = {'dandelion':'蒲公英','jasmine':'茉莉','mint':'薄荷叶','lavender':'薰衣草','cosmos':'波斯菊','rosemary':'迷迭香','daisy': '小雏菊', 'warm': '暖色小花', 'leaf': '尤加利叶'}
FLOWERS.update(sunflower='向日葵',rose='粉玫瑰',tulip='郁金香',hydrangea='蓝绣球',lily='百合')
WOOD = {'boat': {'hull': (50, 68), 'mast': (50, 40), 'sail': (66, 42)},
        'coaster': {'slat1': (50, 38), 'slat2': (50, 50), 'slat3': (50, 62)}}
WOOD_V6={'boat':{'hull':(50,68),'mast':(50,54),'sail':(54.8,51.5)}}
ROPE = [(70, 38), (30, 55), (85, 72)]
WALK = [(20, 70), (42, 50), (65, 40), (84, 66)]


def point(value):
    if not isinstance(value, dict) or any(type(value.get(k)) not in (int, float)
            or not isfinite(value[k]) or not 0 <= value[k] <= 100 for k in ('x', 'y')):
        fail('位置超出了操作台，请重新放置。')
    return {k: round(value[k], 1) for k in ('x', 'y')}


def near(p, target, distance=8):
    return (p['x']-target[0])**2 + (p['y']-target[1])**2 <= distance**2


def complete(oid, act, payload):
    """No client prose, score or completion flag is trusted; retain normalized input."""
    if oid not in ('flowers', 'wood_work', 'rope', 'beach'):
        fail('这个互动没有制作台。')
    item = next((i for i in act['items'] if i['id'] == payload.get('item')), None)
    if act['kind'] == 'craft' and not item:
        fail('请选择作品样式。')
    if oid == 'flowers':
        pieces = payload.get('pieces')
        if not isinstance(pieces, list) or not 3 <= len(pieces) <= 8:
            fail('请在花器里放入3—8枝花材。')
        normalized = []
        for piece in pieces:
            p = point(piece)
            if not isinstance(piece.get('kind'),str) or piece['kind'] not in act.get('daily_materials',FLOWERS) or not 15 <= p['x'] <= 85 or not 12 <= p['y'] <= 66:
                fail('请把花材放在花器上方的操作区域。')
            normalized.append({**p, 'kind': piece['kind']})
        if not any(p['kind'] not in ('leaf','mint','rosemary') for p in normalized):
            fail('加上至少一枝花，再搭配绿叶吧。')
        counts = '、'.join(f"{name}{sum(p['kind']==key for p in normalized)}枝" for key,name in FLOWERS.items() if any(p['kind']==key for p in normalized))
        spread = max(p['y'] for p in normalized)-min(p['y'] for p in normalized)
        position = '高低错落' if spread >= 12 else '花头高度相近'
        vessel = '浅口花器' if item['id']=='white' else '小陶瓶'
        result = f"你用{counts}在{vessel}里做成一份桌花，{position}。"
        design = {'pieces': normalized, 'vessel': item['id']}
    elif oid == 'wood_work':
        pieces = payload.get('pieces')
        targets = (WOOD_V6 if act.get('geometry_version')=='tight-v6' else WOOD)[item['id']]
        if not isinstance(pieces, list) or len(pieces) != len(targets):
            fail('请把每块木片放入对应轮廓。')
        normalized = []
        for piece in pieces:
            p = point(piece)
            if not isinstance(piece.get('kind'),str) or piece['kind'] not in targets or not near(p, targets[piece['kind']]):
                fail('还有木片没有对齐轮廓。')
            normalized.append({**p, 'kind':piece['kind']})
        if len({p['kind'] for p in normalized}) != len(targets):
            fail('木片不能重复使用。')
        polished = payload.get('polished')
        if act.get('geometry_version')!='tight-v6' and (not isinstance(polished,list) or any(type(n)!=int for n in polished) or sorted(polished) != [0,1,2]):
            fail('请用砂纸打磨作品标出的三个边缘。')
        design = {'pieces':normalized,'polished':polished or [],'construction_version':act.get('geometry_version','legacy') }
        result = f"你逐片拼合并连接了{item['name']}。" + ("" if act.get("geometry_version")=="tight-v6" else "打磨过三个边缘。")
    else:
        targets = ROPE if oid == 'rope' else WALK
        moves = payload.get('moves')
        if not isinstance(moves,list) or len(moves) != len(targets):
            fail('请按画面提示完成路线。')
        normalized = [point(p) for p in moves]
        if not all(near(p,t) for p,t in zip(normalized,targets)):
            fail('还没有完成画面上的路线，请继续操作。')
        design = {'moves':normalized}
        result = act['result']
    return {'item': item['id'] if item else None, 'design':design, 'done':True,
            'step':len(act['steps']), 'interaction':'graphical',
            'title':vessel+'桌花' if oid=='flowers' else item['name'] if item else oid}, result


def freecraft(payload):
    pieces=payload.get('pieces')
    if not isinstance(pieces,list) or not 1<=len(pieces)<=24:fail('请使用1—24块木片。')
    name=payload.get('title','自由木作')
    if not isinstance(name,str) or not 1<=len(name.strip())<=30:fail('作品名称请写1—30字。')
    labels={'plank':'长木条','square':'方块','circle':'圆片','triangle':'三角片','hull':'船身','mast':'桅杆','sail':'帆片'}
    normalized=[]
    for piece in pieces:
        p=point(piece)
        kind=piece.get('kind');angle=piece.get('angle',0)
        if kind not in labels or type(angle) not in (float,int) or not isfinite(angle):fail('木片或旋转角度不正确。')
        normalized.append({**p,'kind':kind,'angle':round(angle%360,1)})
    counts='、'.join(f'{label}{sum(p["kind"]==k for p in normalized)}块' for k,label in labels.items() if any(p['kind']==k for p in normalized))
    return {'title':name.strip(),'design':{'pieces':normalized,'mode':'freecraft'},'done':True,'interaction':'freecraft'},f'你用{counts}完成了《{name.strip()}》。'
