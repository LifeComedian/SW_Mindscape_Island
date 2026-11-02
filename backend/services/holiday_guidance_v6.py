"""Object instructions and resident opinion prompts."""
import re

HOW_TO=re.compile(r'怎么(?:做|拼|插|打|玩|操作)|如何|怎样|教我|教一下|教教|步骤')
GUIDES={
    'wood_work':'拼装木船用的是三块预制件：船身、桅杆和帆片。把它们拖到对应轮廓，对齐后即可保存。如果想自己设计，就选“自由拼搭木作”，可以移动、旋转、复制木片，调整叠放顺序，最后给作品起名。',
    'flowers':'先选浅口花器或小陶瓶，再从桌上列出的花材中选3—8枝，拖动花头调整位置和高度，至少保留一枝花，最后点击“完成并保存作品”。这里不需要剪枝。',
    'rope':'岛上现在没有绳结练习台了。海滩可以寻物，也可以去木工台拼搭木片。',
}
KINDS=[('wood_work',r'木船|木工|木作|木片|小桥'),('flowers',r'插花|桌花|花材'),('rope',r'绳结|打结|平结')]
DETAILS=re.compile(r'枝|木片|桅杆|船身|帆|花材|雏菊|尤加利|方块|长条|木条|圆片|三角片|龙骨|船舷|花器|陶瓶|红色|白色|蓝色|黄色|绿色|橙色|左边|右边|底下|上面|高度|间距|稳|晃|承重|结实|手摸|手感|尖|厚|薄|[0-9一二三四五六七八九十两]+(?:块|个|片|处|厘米)')

def topic(message):
    return next((oid for oid,pattern in KINDS if re.search(pattern,message)),None)

def instructions(message):
    oid=topic(message)
    return GUIDES.get(oid) if HOW_TO.search(message) else None

def opinion(reply,allowed=True):
    if allowed and not DETAILS.search(reply):
        return reply,False
    return '你想让我看看哪一处？',True
