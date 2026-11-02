"""V2 paragraph catalogue for validating frozen reports."""
from study.controlled_report import digest, _sentence, _language_safe
CATALOG_VERSION = 'controlled-island-letter-natural-zh-v2'

def build_catalog(facts):
    """Whole paragraph alternatives, conditional on concrete source states."""
    cards=facts['cards'];byid={c['id']:c for c in cards};groups=[]
    def group(key,alternatives,role='body'):
        variants=[]
        for n,sentences in enumerate(alternatives):
            variants.append({'id':key+':'+str(n),'sentences':sentences,'text':''.join(s['text']for s in sentences)})
        groups.append({'id':key,'role':role,'variants':variants})
    works=[c for c in cards if c['kind']=='work'];feedback=[c for c in cards if c['kind']=='feedback']
    linked=[c for c in feedback if c['work_id']in byid]
    if linked:
        f=linked[0];w=byid[f['work_id']];label=w['label'];q=f['quote']
        full=f.get('full_quote',q)
        full=full if _language_safe(full) else q
        group('making_feedback',[
            [_sentence(f'做完{label}，你主动问对方：“{q}”。',w,f),
             _sentence('在这次尝试里，你愿意自己动手，也愿意向别人请教。',w,f,claim='situational_openness')],
            [_sentence(f'做完{label}后，你说：“{full}”。',w,f),
             _sentence('这次，你主动问起了别人的看法。',w,f,claim='situational_openness')],
            [_sentence(f'这次做{label}，你有自己的尝试，也想听听别人的看法。',w,f,claim='situational_openness'),
             _sentence(f'作品做完后，你这样问对方：“{full}”。',w,f)]])
    elif feedback:
        f=feedback[0];q=f['quote']
        group('feedback',[[
            _sentence(f'有一次交流中，你说：“{q}”。',f),
            _sentence('那次，你主动问了别人的意见。',f,claim='situational_openness')]])
    elif works:
        w=works[0];label=w['label']
        line='你跟着步骤完成了这件作品。'if w['guided']else'你亲手做出了这件作品。'
        group('making',[
            [_sentence(f'这次在岛上，你尝试了{label}。',w),_sentence(line,w)],
            [_sentence(f'你在岛上做过{label}，留下了一件自己动手完成的作品。',w)]])
    social=[c for c in cards if c['kind']=='joint']
    active=[c for c in social if c['organized'] and c['participated']]
    # Prefer two comparable activities.
    pair=None
    for first in active:
        other=next((c for c in active if c['plan_id']!=first['plan_id'] and c['recipe']==first['recipe']),None)
        if other:pair=[first,other];break
    if pair:
        a,b=pair;label=a['label'];different=set(a['peers'])!=set(b['peers']);people='不同的同伴'if different else'同伴'
        group('initiative',[
            [_sentence(f'在那两次{label}里，你是主动约人的那个，后来也和{people}一起参加了活动。',a,b,claim='situational_initiative')],
            [_sentence(f'你主动发起了两次{label}，随后也和{people}一起参与了。',a,b),
             _sentence('在这两次相处中，你愿意主动联系别人。',a,b,claim='situational_initiative')],
            [_sentence(f'那两次{label}，都是你先约的人，后来你也参与了。',a,b,claim='situational_initiative')]])
    elif active:
        c=active[0];label=c['label']
        group('initiative',[[ _sentence(f'那次{label}，你主动约了同伴，后来也一起参加了活动。',c,claim='situational_initiative')]])
    else:
        invited=next((c for c in social if c['organized']),None)
        joined=next((c for c in social if c['participated']),None)
        if invited:
            c=invited;status='这项安排后来取消了。'if c['plan_status']=='cancelled'else'这份邀请是你当时发起的一次联系。'
            group('invitation',[[ _sentence(f'你曾发起一起参加{c["label"]}的邀请。',c),
                _sentence(status,c)]])
        elif joined:
            c=joined
            group('participation',[[ _sentence(f'你和同伴一起参加过一次{c["label"]}。',c)]])
    thanks=next((c for c in cards if c['kind']=='gratitude'),None)
    if thanks:
        c=thanks;q=c['quote'];channel='私人留言'if c['public']is False else'公开留言'
        group('gratitude',[
            [_sentence(f'你把感谢写在了一条{channel}里：“{q}”。',c,claim='expressed_appreciation')],
            [_sentence(f'你也用{channel}记下了当时的感谢：“{q}”。',c,claim='expressed_appreciation')],
            [_sentence(f'还有你在{channel}里留下的感谢：“{q}”。',c,claim='expressed_appreciation')]],role='closing')
    if not groups:
        # Use descriptive fallback text for routine actions.
        if facts['coverage']['player_actions']:
            text='你在岛上留下了一些游玩记录。不过，这些记录还不足以说明你习惯怎样做事、怎样与人相处。这次先不作性格判断。'
        else:
            text='这次还没有可供回看的游玩记录，暂时无法写出具体的观察或性格印象。'
        group('short_letter',[[{'text':text,'fact_ids':[],'claim':'scope_notice'}]])
    return {'version':CATALOG_VERSION,'facts_sha256':digest(facts),'groups':groups,'paragraph_count':len(groups)}

