"""Summarize participant events with source references and deduplication."""
from collections import Counter, defaultdict
import re
from study.controlled_report import obj, digest

VERSION='island-recap-v3'
PLACES={'guest_room':'客房','residential':'居民区','loc_01':'沙滩与码头','loc_02':'花坊与木作','loc_03':'超市','loc_04':'餐馆','loc_05':'公共广场','loc_06':'咖啡馆'}
NAMES=dict(enumerate(['周树成','许玉兰','陈惠芳','梁健成','林予安','沈知夏','陆明远','何雨舟','宋以宁','程越','唐沐'],1))
STOP=set('我们 你们 他们 她们 这个 那个 什么 怎么 可以 就是 还是 但是 然后 觉得 一个 有点 现在 这里 那里 真的 已经 自己 一下 时候 因为 所以 知道 没有 不是 还有 这样 那么 今天 刚才 好的 哈哈 谢谢 你好 好像 一点 不过 比较 其实 能够 可能 东西 进行 需要 一些 那些 这些'.split())
WORDS=['一起','独处','朋友','家人','工作','休息','尝试','好奇','担心','计划','随意','认真','放松','改变','选择','习惯','舒服','安静','热闹','建议','想法','故事','分享','合作','颜色','插花','木工','木船','速写','摄影','咖啡','海边','明信片','读书','再试','不想','不太','愿意','期待','有意思','慢慢','自由']

def describe_source(recap,ref):
    quote=next((q['text'] for q in recap['quotes'] if q['ref']==ref),None)
    if quote:return quote
    row=recap['source_index'][ref]
    if row.get('detail'):return (f'第{row["day"]}天：' if row.get('day') else '')+row['detail']
    label={'move':'前往','player_appearance':'选择本次角色形象','opportunity_seen':'看到玩法或活动提示','atomic_action':'操作场景物品','activity_experience':'参与共同活动','holiday_phone_open':'打开手机','player_profile':'设置本次角色资料'}.get(row.get('kind'),'留下了这次游戏操作的记录')
    minute=row.get('minute');clock=f' {int(minute)//60:02d}:{int(minute)%60:02d}' if isinstance(minute,(int,float)) else ''
    place=PLACES.get(row.get('location'),'')
    return (f'第{row["day"]}天{clock}：' if row.get('day') else '')+label+(f'（{place}）' if place else '')+'。'

def build_recap(rows):
    index={};texts=[];moves=[];people=defaultdict(list);activities=defaultdict(list);days=set();seen=set();episodes={};last_location=None;durations=Counter();works=[];visits=[];current_visit=None;guide=None
    conversations=defaultdict(set)
    for turn in rows.get('world_conversation_turns',[]):
        if turn.get('speaker_type')=='participant' and turn.get('source_action_id'):
            conversations[turn['source_action_id']].add(turn.get('conversation_id'))
    people_sessions=defaultdict(set);channels=defaultdict(Counter)
    executions={x.get('source_action_id'):x for x in rows.get('world_atomic_action_executions',[]) if x.get('status')=='completed' and x.get('actor_type')=='participant'}
    changes=[]
    for a in rows.get('world_actions',[]):
        if a.get('action_type')=='daily_catalogue_published':
            meta=obj(a.get('metadata_json'))
            changes.append({'day':a.get('world_day'),'item':meta.get('item'),'owner':NAMES.get(meta.get('owner_id')),'source_ref':meta.get('source_ref'),'ref':'A'+str(a['id'])})
        if a.get('actor_type')!='participant':continue
        key=a.get('idempotency_key') or ('action',a['id'])
        if key in seen:continue
        seen.add(key);ref='A'+str(a['id']);meta=obj(a.get('metadata_json'));req=obj(meta.get('request'))
        kind=a.get('action_type');day=a.get('world_day');minute=a.get('world_time_minutes');days.add(day) if day else None
        if kind=='foreground_sample':
            result=obj(meta.get('result'));seconds=result.get('seconds',0)
            if isinstance(seconds,(float,int)) and 0<seconds<=25:durations[result.get('location')]+=seconds
            continue
        if kind=='opportunity_seen' and req.get('kind')=='guide_step':guide=None if req.get('target')=='none' else req.get('target')
        if kind=='opportunity_seen' and req.get('kind')=='guide_preferences':guide=None if req.get('target')=='skip' else guide
        guided=meta.get('guided',None)
        if guide and (kind=='move' or (guide=='talk' and kind=='conversation_message') or (guide=='object' and kind=='atomic_action')):guided=True
        index[ref]={'kind':kind,'day':day,'minute':minute,'location':a.get('target_location_id'),'guided':guided}
        episode=meta.get('runtime_id') if kind=='activity_experience' else next(iter(sorted(conversations.get(a['id'],set()),key=str)),None)
        if episode is not None:index[ref]['episode']=str(kind)+':'+str(episode)
        if kind=='move' and a.get('target_location_id') and a.get('target_location_id')!=last_location:
            last_location=a['target_location_id'];current_visit={'location':last_location,'ref':ref,'day':day,'interacted':False,'guided':guided};visits.append(current_visit);moves.append(dict(current_visit))
        if current_visit and kind in ('atomic_action','conversation_message','activity_experience') and (kind!='atomic_action' or a['id'] in executions):current_visit['interacted']=True
        text=None
        if kind in ('conversation_message','private_message'):
            text=a.get('response_text');aid=a.get('target_agent_id')
            if aid:
                people[aid].append(ref);channels[aid][kind]+=1
                people_sessions[aid].update(conversations.get(a['id'],set()))
        elif kind=='activity_experience' and req.get('operation')=='chat' and req.get('actor_agent_id') is None:
            text=req.get('message')
        if isinstance(text,str) and text.strip():
            texts.append({'text':text,'ref':ref,'day':day,'channel':kind,'prompted':'guide' if guided else 'unknown','addressee':NAMES.get(a.get('target_agent_id') or req.get('speaker_id')),'speaker':'player'})
        ex=executions.get(a['id'])
        if kind=='atomic_action' and ex:
            result=obj(ex.get('result_json'))
            details=[e['value'] for e in result.get('effects',[]) if isinstance(e,dict) and e.get('state_key')=='result' and isinstance(e.get('value'),str)]
            if details:index[ref]['detail']=' '.join(details)[:1200]
            aid=ex.get('action_id','');payload=obj(obj(ex.get('inputs_json')).get('payload'));oid=aid.removeprefix('v4_').split('__')[0]
            command=payload.get('command');group=(oid,day)
            if command in ('start','restart'):episodes[group]=ref
            # A batch of puzzle moves stays one attempt, not 40 activities.
            episode=payload.get('trace_draft_id') or episodes.setdefault(group,ref)
            activities[(oid,str(episode))].append(ref)
            if command=='finish_graphical' and payload.get('pieces') and oid in ('flowers','wood_work'):
                works.append({'id':ref,'name':payload.get('title') or ('你的桌花' if oid=='flowers' else '你拼的木船'),'text':'根据这次成功保存时的花材或木片位置展示。','author':'participant','day':day,'source_action_id':a['id'],'design':{'pieces':payload['pieces'],'mode':'freecraft' if aid.endswith('__free') else 'graphical','vessel':payload.get('item')}})
            if oid=='sketch' and command=='save' and payload.get('strokes'):
                works.append({'id':ref,'name':'你保存的速写','text':'这里保留的是你实际画下的线条。','author':'participant','day':day,'source_action_id':a['id'],'strokes':payload['strokes'],'stroke_styles':payload.get('stroke_styles')})
    for table,kind in [('user_posts','post'),('interactions','comment')]:
        for row in rows.get(table,[]):
            if (kind=='post' and row.get('author_type')!='participant') or (kind=='comment' and row.get('event_type')!='comment'):continue
            value=row.get('content');ref=('P' if kind=='post' else 'I')+str(row['id'])
            if isinstance(value,str) and value.strip():
                texts.append({'text':value,'ref':ref,'day':row.get('day') or row.get('world_day'),'channel':kind,'prompted':'unknown','speaker':'player'})
                index[ref]={'kind':kind,'day':row.get('day') or row.get('world_day')}
    freq=Counter();sources=defaultdict(list)
    import jieba
    jieba.setLogLevel(40)
    for quote in texts:
        # Exclude quoted speech from player expression counts; preserve negation.
        plain=re.sub(r'“[^”]*”|「[^」]*」|"[^"]*"','',quote['text'])
        tokens=[w for w in jieba.cut(plain,HMM=False) if w not in STOP and re.fullmatch(r'[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,12}',w)]
        for word,n in Counter(tokens).items():freq[word]+=n;sources[word].append(quote['ref'])
    visits=Counter(m['location'] for m in moves)
    activity_counts=Counter(oid for oid,_ in activities)
    return {'version':VERSION,'source_sha256':digest(rows),'days':sorted(days),'player_action_count':sum(r.startswith('A') for r in index),'works':works,'visits':visits,'changes':changes,
      'places':[{'id':lid,'name':PLACES.get(lid,lid),'count':n,'returns':max(0,n-1),'refs':[m['ref'] for m in moves if m['location']==lid]} for lid,n in visits.most_common()],
      'people':[{'id':aid,'name':NAMES.get(aid,str(aid)),'count':len(refs),'refs':refs,'conversation_sessions':len(people_sessions[aid]),'channels':dict(channels[aid])} for aid,refs in sorted(people.items(),key=lambda x:-len(x[1]))],
      'activities':[{'id':oid,'count':n,'refs':[r for (o,_),refs in activities.items() if o==oid for r in refs]} for oid,n in activity_counts.most_common()],
      'words':[{'word':w,'count':n,'episodes':len(set(sources[w])),'refs':list(dict.fromkeys(sources[w]))} for w,n in freq.most_common(24)],
      'quotes':texts,'route':moves,'source_index':index,
      'metrics':{'places':'成功移动到不同地点的次数；含途经，不直接解释为偏好','people':'直接对话及私信中玩家发送的有效话语条数；活动内和评论不摊给在场每个人，不是关系分数','activities':'同日同类操作按开始/重开或草稿ID聚合；旧记录无开始边界时仅作保守归并','words':'jieba 0.42.1固定词典分词，去常用停用词和引号内转述；原句保留否定和语境，不解释为人格强度'},
      'missing':['旧记录未可靠区分引导与自主行为，不据此推断主动性。','缺少连续前台停留记录时不展示停留排行。'],
      'duration':{'label':'前台浏览采样时长（不等同于专注时间；暂停与等待未计入）','places':[{'id':k,'name':PLACES.get(k,k),'seconds':round(v)} for k,v in durations.most_common()]} if durations else None}
