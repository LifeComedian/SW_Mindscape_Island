import json
"""Server-authoritative puzzle/timed practice; performance is not a trait score."""
from collections import deque
from copy import deepcopy
from functools import lru_cache
import secrets
import time

SIZES=((2,2),(2,1),(1,2),(1,2),(1,2),(1,2),(1,1),(1,1),(1,1),(1,1))
NAMES=('曹操','关羽','张飞','赵云','马超','黄忠','兵一','兵二','兵三','兵四')
CLASSIC=(1,9,0,3,8,11,13,14,16,19)
DIRECTIONS={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)}


def key(board):
    return (board[0],board[1],*sorted(board[2:6]),*sorted(board[6:]))


def moves(board):
    occupied=set()
    for pos,(w,h) in zip(board,SIZES):
        occupied.update((pos%4+dx,pos//4+dy) for dx in range(w) for dy in range(h))
    for i,(pos,(w,h)) in enumerate(zip(board,SIZES)):
        x,y=pos%4,pos//4
        own={(x+dx,y+dy) for dx in range(w) for dy in range(h)}
        for name,(dx,dy) in DIRECTIONS.items():
            nx,ny=x+dx,y+dy
            if nx<0 or ny<0 or nx+w>4 or ny+h>5:continue
            cells={(nx+a,ny+b) for a in range(w) for b in range(h)}
            if cells&(occupied-own):continue
            new=list(board);new[i]=ny*4+nx
            yield (i,name),tuple(new)


@lru_cache(maxsize=32)
def solution(board):
    """Breadth-first search merges indistinguishable blocks, retaining legal moves."""
    queue=deque([board]);parents={key(board):None};boards={key(board):board}
    goal=None
    while queue:
        current=queue.popleft();ck=key(current)
        if current[0]==13:goal=ck;break
        for move,next_board in moves(current):
            nk=key(next_board)
            if nk in parents:continue
            parents[nk]=(ck,move);boards[nk]=next_board;queue.append(next_board)
    if goal is None:raise ValueError('unsolvable_huarong')
    path=[]
    while parents[goal] is not None:
        previous,move=parents[goal];path.append((boards[previous],move));goal=previous
    return tuple(reversed(path))


@lru_cache(maxsize=1)
def levels():
    path=solution(CLASSIC)
    distances=(4,10,22,40,70,len(path))
    return tuple({'id':i+1,'name':name,'board':list(path[-min(d,len(path))][0]),'verified_moves':min(d,len(path))}
                 for i,(name,d) in enumerate(zip(('出口在望','让出通道','左右换位','迂回前进','步步为营','横刀立马'),distances)))


def huarong(p,payload,fail):
    command=payload.get('command','open')
    if command=='batch':
        from copy import deepcopy
        commands=payload.get('moves')
        if not isinstance(commands,list) or not 1<=len(commands)<=20:fail('移动批次不正确。')
        signature=json.dumps(payload,sort_keys=True)
        if p.get('last_batch')==signature:return '移动已保存。'
        if payload.get('base_board')!=p.get('board'):fail('棋盘已变化，请先同步存档。')
        next_state=deepcopy(p)
        for item in commands:
            if not isinstance(item,dict) or item.get('command')!='move':fail('批次只允许移动棋子。')
            huarong(next_state,item,fail)
        next_state['last_batch']=signature
        p.clear();p.update(next_state)
        return '本段移动已保存。'
    if command in ('start','restart'):
        level=payload.get('level',p.get('level',1))
        if type(level)!=int or not 1<=level<=6:fail('请选择1—6关。')
        item=levels()[level-1]
        p.clear();p.update(level=level,board=item['board'][:],moves=0,undo=[],hints=0,done=False,game_version='huarong-v6')
    elif command=='undo':
        if p.get('undo'):
            p['board']=p['undo'].pop();p['moves']+=1;p['done']=False;p.pop('hint',None)
    elif command in ('move','hint'):
        if not p.get('board') or p.get('done'):fail('请先开始一关。')
        if command=='hint':
            path=solution(tuple(p['board']))
            i,direction=path[0][1]
            p['hint']={'piece':i,'direction':direction};p['hints']=p.get('hints',0)+1
        else:
            wanted=(payload.get('piece'),payload.get('direction'))
            steps=payload.get('steps',1)
            if type(steps)!=int or not 1<=steps<=4:fail('移动距离不正确。')
            board=tuple(p['board'])
            for _ in range(steps):
                board=next((b for move,b in moves(board) if move==wanted),None)
                if board is None:fail('这个方向没有足够空位。')
            p.setdefault('undo',[]).append(p['board'][:]);p['undo']=p['undo'][-100:]
            p['board']=list(board);p['moves']+=1;p.pop('hint',None)
            p['done']=p['board'][0]==13
            p['interaction_version']='drag-v1'
    elif command!='open':fail('不支持这个棋盘操作。')
    return f"华容道第{p.get('level',1)}关"+(f"完成，用了{p['moves']}次移动或撤销。" if p.get('done') else '：移动棋子，让曹操到达下方出口。')


def timed_volley(p,payload,fail,now=None):
    now=now if now is not None else int(time.time()*1000)
    command=payload.get('command','open')
    if command=='start':
        difficulty=payload.get('difficulty','easy')
        if difficulty not in ('easy','challenge'):fail('请选择练习难度。')
        p.clear();p.update(round=0,score=0,target=secrets.randbelow(3),done=False,difficulty=difficulty,
            deadline_ms=now+(3000 if difficulty=='easy' else 2000),game_version='timed-volley-v6',attempts=[])
        return '练习开始。看清球上的图案，及时选择相同图案。'
    if command=='hit':
        if 'round' not in p or p.get('done'):fail('请先开始练习。')
        if payload.get('round')!=p['round']:fail('这一球已处理，请等待下一球。')
        zone=payload.get('zone')
        if zone is not None and (type(zone)!=int or zone not in (0,1,2)):fail('请选择一个图案。')
        duration=3000 if p['difficulty']=='easy' else 2000
        elapsed=max(0,now-(p['deadline_ms']-duration))
        if zone is None and now<p['deadline_ms']:fail('这一球还没超时。')
        hit=zone==p['target'] and now<=p['deadline_ms']
        p['attempts'].append({'round':p['round'],'target':p['target'],'choice':zone,'elapsed_ms':elapsed,'hit':hit})
        p['score']+=int(hit);p['round']+=1;p['done']=p['round']>=12
        p['target']=secrets.randbelow(3);p['deadline_ms']=now+duration
        return f"本轮结束，接住{p['score']}/12球。" if p['done'] else '接住了。' if hit else '这一球没接住，准备下一球。'
    if command!='open':fail('不支持这个练习操作。')
    return '共12球，选择相同图案，轻松3秒、挑战2秒。'


def search(p,payload,fail):
    from content.holiday_search_v6 import SCENES
    command=payload.get('command','open')
    if command=='start':
        scene=payload.get('scene',1)
        if type(scene)!=int or not 1<=scene<=3:fail('请选择一个海滩画面。')
        saved=deepcopy(p.get('scenes',{}))
        if p.get('scene'):
            saved[str(p['scene'])]={k:deepcopy(v) for k,v in p.items() if k!='scenes'}
        current=saved.get(str(scene),dict(scene=scene,found=[],marks=[],hints=0,attempts=0,done=False,game_version='beach-search-v6'))
        p.clear();p.update(current,scenes=saved)
    scene=SCENES[p.get('scene',1)-1]
    if command=='find':
        if not p.get('scene') or p.get('done'):fail('请先打开一幅寻物画面。')
        from services.holiday_play_service import point
        pos=point(payload);p['attempts']+=1
        hit=next((t for t in scene['targets'] if t[0] not in p['found']
                  and ((pos['x']-t[2])/t[4])**2+((pos['y']-t[3])/t[5])**2<=1),None)
        if hit:
            p['found'].append(hit[0]);p['marks'].append({'id':hit[0],'x':hit[2],'y':hit[3]})
            p.pop('hint',None);p['done']=len(p['found'])==6
        return '六样都找到了。你把它们留在原处，记住了这片潮间带。' if p['done'] else '找到了：'+hit[1] if hit else '这里还没有找到，换个角落看看。'
    if command=='hint':
        left=next((t for t in scene['targets'] if t[0] not in p.get('found',[])),None)
        if left:
            p['hint']={'x':left[2],'y':left[3],'name':left[1],'radius':12}
            p['hints']=p.get('hints',0)+1
    elif command not in ('open','start'):fail('不支持这个寻物操作。')
    return '慢慢观察画面，寻找清单上的六样小物。可以放大，也可以请求提示。'
