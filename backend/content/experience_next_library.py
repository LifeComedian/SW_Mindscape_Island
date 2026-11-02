"""Object libraries for rotating daily displays."""
from copy import deepcopy

def exhibit(key,name,text,owner,tags):
    return dict(id=key,name=name,text=text,art_id='next.library.'+key,
                author='resident:'+str(owner),source_type='authored_exhibit',tags=tags)

WOOD=[exhibit(*row,1,tags) for row,tags in [
    (('wood_whale','木雕小鲸','圆鼓鼓的胡桃木身体，浅色腹部和向上翘起的尾巴。'),['鲸','鲸鱼','海洋']),
    (('wood_bird','枝头麻雀','深浅两色木料拼出翅膀，小雀站在树枝形底座上。'),['鸟','麻雀']),
    (('wood_house','海边小屋','枫木墙面嵌着两扇小窗，深色人字屋顶压在上面。'),['屋','房子','建筑']),
    (('wood_cat','蜷睡的小猫','小猫弯成一圈，尾巴贴着身体，眼睛刻成两道浅线。'),['猫','动物']),
    (('wood_lamp','木格小灯','橡木框架围着浅色纸灯罩，顶部装着可以提起的木柄。'),['灯','实用']),
    (('wood_music','帆船音乐盒','胡桃木盒上立着一艘小帆船，盒侧露出金属发条钥匙。'),['音乐盒','帆船','音乐'])]]
FLOWER_MATERIALS={
 'flower_daisy':['daisy','dandelion','leaf'], 'flower_jasmine':['jasmine','mint','leaf'],
 'flower_lavender':['lavender','leaf','jasmine'], 'flower_marigold':['warm','rosemary','dandelion'],
 'flower_cosmos':['cosmos','mint','daisy']}
FLOWERS=[exhibit(*row,2,tags) for row,tags in [
    (('flower_daisy','雏菊与蒲公英','浅口花器里，白色小雏菊与黄色蒲公英高低相间。'),['雏菊','蒲公英','黄色']),
    (('flower_jasmine','茉莉与薄荷','蓝陶壶口散开白色茉莉，薄荷叶从花间伸出。'),['茉莉','薄荷','白花']),
    (('flower_lavender','薰衣草与尤加利','细长的紫色花穗搭着灰绿色圆叶，插在素色陶瓶里。'),['薰衣草','尤加利','紫']),
    (('flower_marigold','金盏花与迷迭香','暖橙色花头聚在深陶碗边，迷迭香枝条向外舒展。'),['金盏花','迷迭香','橙','暖色']),
    (('flower_cosmos','波斯菊与薄荷','粉白波斯菊插在透明玻璃瓶中，细叶间可以看见水面。'),['波斯菊','粉','薄荷'])]]
PLANTS=[exhibit('plant_mint','薄荷盆栽','叶缘有细锯齿，新叶挤在枝条顶端，长在红陶盆里。',2,['薄荷']),
        exhibit('plant_jasmine','茉莉盆栽','小小的白色星形花开在深绿叶片之间。',2,['茉莉']),
        exhibit('plant_rosemary','迷迭香盆栽','灰绿色细叶向上伸展，枝间有浅蓝色小花。',2,['迷迭香'])]
PHOTOS=[exhibit('photo_nets','晒网','码头木栏上的渔网垂下来，绿色绳索和木纹交错。',5,['渔网','码头']),
        exhibit('photo_rain','雨后的窗','蓝窗和花盆倒映在巷子里的积水中，石缝分开了倒影。',5,['雨','倒影']),
        exhibit('photo_chairs','两把椅子','窗边空着两把木椅，傍晚的光把椅腿影子拉得很长。',5,['椅','傍晚'])]

import json
from pathlib import Path
STOCK=json.loads(Path(__file__).with_name('experience_next_stock.json').read_text(encoding='utf-8'))
WOOD += [exhibit(*r[:3],1,r[3].split(',')) for r in STOCK['wood']]
FLOWERS += [exhibit(*r[:3],2,r[3].split(',')) for r in STOCK['flowers']]
FLOWER_MATERIALS.update({r[0]:r[4] for r in STOCK['flowers']})
PHOTOS += [exhibit(*r[:3],5,r[3].split(',')) for r in STOCK['photos']]

def pool(key,base):
    if key=='wood_display':return deepcopy(base[key]['actions'][0]['items'])+deepcopy(WOOD)
    if key=='flowers':return deepcopy(FLOWERS)
    if key=='plants':return deepcopy(base[key]['actions'][0]['items'])+deepcopy(PLANTS)
    if key=='photos':return deepcopy(base[key]['actions'][0]['items'])+deepcopy(PHOTOS)
    return []

def daily(items,day,count):
    return [deepcopy(items[(day-1+i)%len(items)]) for i in range(min(count,len(items)))]
