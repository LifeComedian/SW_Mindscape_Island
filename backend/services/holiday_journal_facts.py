"""Journal text from witnessed actions and encounter dialogue."""
import re

VERSION='shared-journal-v2'

def quoted_fragments(texts,limit=2):
    picked=[]
    for value in reversed(texts):
        text=str(value or '').strip()
        if len(text)<10 or re.search(r'按钮|点哪里|怎么操作|无法|报错|测试一下',text):continue
        if text in picked:continue
        picked.append(text)
        if len(picked)==limit:break
    return list(reversed(picked))

def speech_sentence(name,text):
    # An excerpt remains a quotation, never a claim the described action occurred.
    excerpt=text[:140]+('……' if len(text)>140 else '')
    return name+'提起：“'+excerpt+'”'

def render_details(details,name):
    result='';previous_subject=False
    for detail in details:
        detail=detail.rstrip('。');same=detail.startswith(name)
        if result and same and previous_subject:
            result+='，'+detail[len(name):]
        else:result+=('。' if result else '')+detail
        previous_subject=same and not detail.endswith('”')
    return result+('' if not result or result.endswith(('。','！','？','”')) else '。')

def completed_details(history,confirmed,name):
    details=[]
    for h in history:
        if h.get('kind')!='action' or h.get('source_action_id') not in confirmed:continue
        ex=confirmed[h['source_action_id']]
        if ex.actor_type!='participant':continue
        text=h.get('text','')
        if ex.action_id.endswith(('__sit','__seat')):
            match=re.match(r'你在(.+?)坐下。',text)
            if match:details.append(name+'选了'+match[1])
        elif ex.action_id.endswith('__order') and text.startswith('已点单：'):
            details.append(name+'点了'+text.split('。',1)[0].removeprefix('已点单：'))
        elif ex.action_id.endswith(('__eat','__drink','__consume')):
            match=re.match(r'你享用了(.+?)。',text)
            if match:details.append(name+'吃了'+match[1])
    # Prefer completed meals over orders when deduplicating dishes.
    if any(name+'吃了' in s for s in details):details=[s for s in details if not s.startswith(name+'点了')]
    return list(dict.fromkeys(details))[-3:]
