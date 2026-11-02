"""Single-round UNO with server-side hands and deck."""
import random
from collections import Counter

COLORS=('红','黄','绿','蓝')
SYMBOLS=('0','1','2','3','4','5','6','7','8','9','跳过','反转','+2')


def face(card):return card.split('#')[0]


def cards():
    values=[c+s for c in COLORS for s in SYMBOLS for _ in range(1 if s=='0' else 2)]
    values+=['变色']*4+['+4']*4
    return [f'{value}#{i}' for i,value in enumerate(values)]


def draw(game,who,n):
    result=[]
    for _ in range(n):
        if not game['deck'] and len(game['discard'])>1:
            game['deck']=game['discard'][:-1];game['discard']=game['discard'][-1:]
            random.SystemRandom().shuffle(game['deck'])
        if not game['deck']:break
        card=game['deck'].pop();game['hands'][who].append(card);result.append(card)
    return result


def legal(game,card,who):
    f=face(card);top=face(game['discard'][-1])
    if f=='+4':return not any(face(c).startswith(game['color']) for c in game['hands'][who])
    return f=='变色' or f[0]==game['color'] or f[1:]==top[1:]


def next_turn(game,steps=1):
    game['current']=(game['current']+game['direction']*steps)%len(game['players'])
    game['drawn']=None;game['uno_declared']=False


def play(game,card,color,declared,log):
    who=game['players'][game['current']];hand=game['hands'][who];name=game['names'][who]
    f=face(card);hand.remove(card);game['discard'].append(card);game['color']=color if f in ('变色','+4') else f[0]
    log(name,'打出'+f+('，改为'+color+'色。' if f in ('变色','+4') else '。'))
    if len(hand)==1:
        if declared or game.get('rules_version')=='uno-easy-v1':log(name,'UNO！只剩一张牌了。')
        else:
            draw(game,who,2);log('同桌','发现'+name+'忘记喊UNO，补摸两张牌。')
    skip=1
    if f.endswith('反转'):
        game['direction']*=-1
        if len(game['players'])==2:skip=2
    elif f.endswith('跳过'):skip=2
    elif f.endswith('+2') or f=='+4':
        victim=game['players'][(game['current']+game['direction'])%len(game['players'])]
        n=4 if f=='+4' else 2;draw(game,victim,n)
        log(game['names'][victim],f'摸{n}张牌，跳过本回合。');skip=2
    if not hand:
        game['finished']=True;game['winner']=who;log('UNO',name+'先出完手牌，本局结束。')
    next_turn(game,skip);game['turn']+=1


def advance_residents(game,log):
    # Stop after a bounded number of NPC turns; a continuation can resume safely.
    for _ in range(100):
        who=game['players'][game['current']]
        if game['finished'] or who=='participant':return
        playable=next((c for c in game['hands'][who] if legal(game,c,who)),None)
        if not playable:
            new=draw(game,who,1);log(game['names'][who],'摸了一张牌。' if new else '牌堆暂时无牌，跳过。')
            playable=new[0] if new and legal(game,new[0],who) else None
        if playable:
            color=Counter(face(c)[0] for c in game['hands'][who] if face(c)[0] in COLORS).most_common(1)
            play(game,playable,color[0][0] if color else COLORS[0],True,log)
        else:next_turn(game);game['turn']+=1


def command(value,choice,residents,log,fail,rng=None,easy=False):
    game=value.get('game')
    if choice=='start':
        if game and not game.get('finished'):fail('请先完成当前一局。','invalid_choice')
        deck=[c for c in cards() if not easy or face(c)=='变色' or face(c)[1:].isdigit()];(rng or random.SystemRandom()).shuffle(deck)
        players=['participant',*[f"resident:{r['id']}" for r in residents]]
        game={'mode':'uno','players':players,'names':{'participant':'你',**{f"resident:{r['id']}":r['name'] for r in residents}},
            'hands':{k:[] for k in players},'deck':deck,'discard':[],'color':'红','direction':1,'current':0,
            'turn':0,'finished':False,'drawn':None,'uno_declared':False,'rules_version':'uno-easy-v1' if easy else 'uno-single-round-v6'}
        for who in players:draw(game,who,5 if easy else 7)
        # Authored island setup: a number card starts every round.
        index=next(i for i,c in enumerate(game['deck']) if face(c)[1:].isdigit())
        first=game['deck'].pop(index);game['discard']=[first];game['color']=face(first)[0]
        value['game']=game
        log('UNO','轻松规则：每人五张牌，同色或同数字可出，也有变色牌；摸牌后自动处理，没有罚牌。' if easy else '每人七张牌，数字牌开局。按颜色、数字或符号出牌；不叠加罚牌。先出完者赢下本局。')
        return
    if not game or game.get('finished'):fail('请先开始一局UNO。','invalid_choice')
    if set(game['players'][1:])!={f"resident:{r['id']}" for r in residents}:
        fail('本局参与者已变化，请重新开局。','participants_missing')
    if choice=='continue':
        advance_residents(game,log);return
    if game['players'][game['current']]!='participant':fail('请等待同桌出牌。','invalid_choice')
    if choice=='uno':
        if len(game['hands']['participant'])!=2:fail('手上两张牌、准备出倒数第二张时喊UNO。','invalid_choice')
        game['uno_declared']=True;return
    if choice=='draw':
        if game['drawn']:fail('已经摸过牌，可以出这张牌或保留它。','invalid_choice')
        new=draw(game,'participant',1)
        log('你','摸了一张牌。')
        if new and legal(game,new[0],'participant'):
            if game.get('rules_version')=='uno-easy-v1':
                colors=Counter(face(c)[0] for c in game['hands']['participant'] if face(c)[0] in COLORS).most_common(1)
                play(game,new[0],colors[0][0] if colors else game['color'],True,log)
            else:game['drawn']=new[0]
        else:next_turn(game);game['turn']+=1
    elif choice=='pass':
        if not game['drawn']:fail('先摸一张牌，才能选择保留。','invalid_choice')
        log('你','保留刚摸到的牌。');next_turn(game);game['turn']+=1
    elif choice.startswith('play:'):
        parts=choice[5:].split('|');card=parts[0];color=parts[1] if len(parts)>1 else game['color']
        if card not in game['hands']['participant'] or not legal(game,card,'participant'):
            fail('这张牌不能接在当前牌面上。+4仅在没有同色牌时可用。','invalid_choice')
        if game['drawn'] and game['drawn']!=card:fail('摸牌后，这一回合只能出刚摸到的牌。','invalid_choice')
        if color not in COLORS:fail('请为万能牌选择颜色。','invalid_choice')
        play(game,card,color,game['uno_declared'],log)
    else:fail('请选择手牌、摸牌或UNO。','invalid_choice')
    value['cost']+=1
    if not game['drawn']:advance_residents(game,log)


def public(game):
    hand=game['hands']['participant']
    playable=[c for c in hand if legal(game,c,'participant') and (not game['drawn'] or c==game['drawn'])]
    return {'mode':'uno','top':face(game['discard'][-1]),'hand':hand[:],'color':game['color'],'direction':game['direction'],
        'turn':game['turn'],'finished':game['finished'],'winner':game['names'].get(game.get('winner')),
        'others':[{'name':game['names'][p],'count':len(game['hands'][p])} for p in game['players'] if p!='participant'],
        'current_name':game['names'][game['players'][game['current']]],'your_turn':game['players'][game['current']]=='participant',
        'playable':playable,'drawn':game['drawn'],'uno_declared':game['uno_declared'],'rules_version':game['rules_version']}
