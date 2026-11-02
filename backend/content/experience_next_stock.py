"""Finite libraries and reproducible daily sampling for the seven-day visit."""
from copy import deepcopy
import hashlib,random
from content.experience_next_library import STOCK,pool,FLOWER_MATERIALS
from content.experience_next_reading import BOOKS

COUNTS={'wood_display':2,'flowers':2,'photos':2,'books':2,'restaurant_menu':3,'cafe_menu':3,'shelf':3}
OWNERS={'wood_display':1,'flowers':2,'photos':5,'books':6,'restaurant_menu':4,'cafe_menu':6,'shelf':3}

def foods(rows,prefix='next.food.'):
    return [dict(id=r[0],name=r[1],text=r[2],price=r[3],tags=r[4].split(','),art_id=prefix+r[0]) for r in rows]

def libraries(base,extras):
    result={key:pool(key,base) for key in ('wood_display','flowers','photos')}
    result['books']=deepcopy(BOOKS)
    for venue in ('restaurant','cafe'):
        key=venue+'_menu'
        result[key]=deepcopy(base[key]['actions'][0]['items'])+deepcopy(extras[key])+foods(STOCK[venue])
        for item in result[key]:item.setdefault('art_id','next.food.'+item['id'])
    result['shelf']=foods(STOCK['snacks'],'next.snack.')
    tags={'walden':['独处','瓦尔登湖'],'meditations':['沉思','内心'],'stray_birds':['飞鸟','泰戈尔'],
          'coffee':['拿铁','牛奶'],'tea':['柠檬茶','茶'],'cocoa':['可可'],'rice':['蔬菜','盖饭'],
          'noodles':['番茄','面'],'soup':['菌菇','汤'],'boat':['船','木船'],'coaster':['杯垫'],
          'harbor':['船','码头'],'street':['巷子','猫'],'tomato_egg':['番茄','鸡蛋'],
          'mushroom_noodles':['菌菇','汤面'],'pumpkin_rice':['南瓜','杂粮'],
          'orange_coffee':['橙','冰咖啡'],'oat_latte':['燕麦']}
    for items in result.values():
        for item in items:item.setdefault('tags',tags.get(item['id'],[]))
    return result

def sample(items,session_id,day,key,count):
    seed=hashlib.sha256(f'finite-stock-v1:{session_id}:{day}:{key}'.encode()).digest()
    return deepcopy(random.Random(seed).sample(items,count))

def flower_materials(obj):
    from services.holiday_play_service import FLOWERS
    displayed=next(a['items'] for a in obj['actions'] if a['id']=='browse')
    materials=list(dict.fromkeys(k for item in displayed for k in FLOWER_MATERIALS[item['id']]))
    for action in obj['actions']:
        if action['kind'] in ('steps','craft'):
            action['daily_materials']=materials
            for item in action['items']:
                item['name']='浅口花器' if item['id']=='white' else '小陶瓶'
                item['text']='从桌上的花材中取用，自己安排位置和高低。'
        elif action['id']=='tools':
            action['items']=[{'id':'kit','name':'桌上的花材','text':'、'.join(FLOWERS[k] for k in materials)+'。选一个花器，就可以开始搭配。'}]
