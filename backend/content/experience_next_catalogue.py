"""Daily catalogue selection with stable object IDs."""
from copy import deepcopy
import hashlib
from content.experience_next import enabled

EXTRAS = {
 'restaurant_menu':[
  {'id':'tomato_egg','name':'番茄炒蛋饭','text':'酸甜番茄、炒蛋配一碗米饭。','price':24,'art_id':'next.food.tomato_egg'},
  {'id':'mushroom_noodles','name':'菌菇汤面','text':'香菇和平菇煮成清汤，配细面和青菜。','price':22,'art_id':'next.food.mushroom_noodles'},
  {'id':'pumpkin_rice','name':'南瓜杂粮饭','text':'蒸南瓜、杂粮饭和时蔬，口味清淡。','price':26,'art_id':'next.food.pumpkin_rice'}],
 'cafe_menu':[
  {'id':'orange_coffee','name':'橙香冰咖啡','text':'冰咖啡加橙片，带一点清爽的果香。','price':24,'art_id':'next.food.orange_coffee'},
  {'id':'oat_latte','name':'燕麦拿铁','text':'咖啡与燕麦饮调成温热的一杯。','price':24,'art_id':'next.food.oat_latte'}],
 'shelf':[
  {'id':'postcard_pack','name':'空白明信片套装','text':'五张米白色空白卡片。','price':10},
  {'id':'tea','name':'茉莉花茶','text':'一小包散装茉莉花茶。','price':15},
  {'id':'sea_salt','name':'海盐','text':'一罐细海盐，带回去做菜。','price':8}]
}

from content.experience_next_library import WOOD,FLOWERS,FLOWER_MATERIALS,daily,pool
EXAMPLES={'wood_display':WOOD,'flowers':FLOWERS}

def catalogue(base, day=1, session_id=0):
    if not enabled(): return base
    from content.experience_next_stock import libraries,COUNTS,sample,flower_materials
    from content.experience_next_postcards import INITIAL
    result=deepcopy(base)
    for key,items in libraries(base,EXTRAS).items():
        selected=sample(items,session_id,day,key,COUNTS[key])
        for action in result[key]['actions']:
            if action['id'] in ('browse','album','read','order'):action['items']=deepcopy(selected)
    result['shelf']['name']='零食货架'
    result['shelf']['actions'][0]['name']='看看今天的零食'
    result['cafe_menu']['name']='咖啡店菜单'
    result['photos']['name']='摄影展示架'
    result['flowers']['name']='插花展架与工作桌'
    result['postcards']['name']='明信片展示架'
    result['postcards']['actions'][0]['items']=deepcopy(INITIAL)
    for action in result['plants']['actions']:
        if action.get('items'):action['items']=daily(pool('plants',base),day,2)
    flower_materials(result['flowers'])
    for obj in result.values():
        obj.pop('daily_note',None)
        for action in obj['actions']:action.pop('daily_hint',None)
    return result
