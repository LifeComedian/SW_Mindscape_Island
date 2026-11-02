"""Volleyball practice using client-reported position and timing."""
import math
import secrets
from copy import deepcopy

VERSION='volley-position-v1'


def command(p,payload,fail):
    op=payload.get('command','open')
    if op=='start':
        difficulty=payload.get('difficulty','easy')
        if difficulty not in ('easy','challenge','fast'):fail('请选择练习难度。')
        archive=deepcopy(p.get('previous_practice',[]))[-2:]
        if p.get('game_version') or p.get('mode'):
            archive.append({k:deepcopy(v) for k,v in p.items() if k!='previous_practice'})
        p.clear()
        p.update(game_version=VERSION,practice_id=secrets.token_hex(8),difficulty=difficulty,
                 targets=[18+secrets.randbelow(65) for _ in range(12)],duration_ms={'easy':1800,'challenge':1100,'fast':800}[difficulty],
                 tolerance=12 if difficulty=='easy' else 8,round=0,score=0,done=False,
                 pacing_version='continuous-v2',return_ms=380,between_ms=120,
                 previous_practice=archive,source_quality='client_reported_position_and_timing')
        return '移动到球的落点附近，在球接近手臂时垫起。'
    if op=='finish':
        if p.get('game_version')!=VERSION or p.get('done') or payload.get('practice_id')!=p.get('practice_id'):
            fail('这一轮练习已变化，请重新打开。')
        attempts=payload.get('attempts')
        if not isinstance(attempts,list) or len(attempts)!=12:fail('需要保留完整12球的练习记录。')
        results=[]
        for i,a in enumerate(attempts):
            if not isinstance(a,dict) or type(a.get('round'))!=int or a['round']!=i:fail('球次顺序不正确。')
            x,t=a.get('position'),a.get('contact_ms')
            if type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=100:fail('接球位置不正确。')
            if t is not None and (type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=p['duration_ms']):fail('击球时间不正确。')
            hit=t is not None and abs(x-p['targets'][i])<=p['tolerance'] and .72<=t/p['duration_ms']<=.98
            results.append(dict(round=i,position=round(x,1),contact_ms=t,target=p['targets'][i],hit=hit))
        p.update(attempts=results,round=12,score=sum(a['hit'] for a in results),done=True)
        return f"这一轮练习结束，接稳了{p['score']}/12球。"
    if op!='open':fail('请选择开始练习或保存本轮结果。')
    return '站到落点附近，看准时机垫球。'
