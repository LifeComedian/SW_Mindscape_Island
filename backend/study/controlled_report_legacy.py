"""V1 paragraph catalogue for validating frozen reports."""
from study.controlled_report import VERSION, digest, _sentence

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
        group('making_feedback',[
            [_sentence(f'做完{label}后，你问对方：“{q}”。',w,f),
             _sentence('你在这次创作里，既愿意自己动手尝试，也愿意听听别人怎么看这份作品。',w,f,claim='situational_openness')],
            [_sentence(f'谈到刚完成的{label}，你主动问起了对方的建议：“{q}”。',w,f),
             _sentence('这次，你把自己的尝试带进了交流，也表达了想听听另一种看法的意愿。',w,f,claim='situational_openness')],
            [_sentence(f'你在{label}这件事上，既有自己的尝试，也有向别人请教的意愿。',w,f,claim='situational_openness'),
             _sentence(f'作品做完后，你问：“{q}”。',w,f)]])
    elif feedback:
        f=feedback[0];q=f['quote']
        group('feedback',[[
            _sentence(f'有一次交流中，你说：“{q}”。',f),
            _sentence('在那次对话里，你愿意主动询问别人的看法。',f,claim='situational_openness')]])
    elif works:
        w=works[0];label=w['label']
        line='你跟着步骤完成了这件作品。'if w['guided']else'你亲手做出了这件作品。'
        group('making',[
            [_sentence(f'这次在岛上，你尝试了{label}。',w),_sentence(line,w),
             _sentence('在这段经历里，你用实际的尝试参与了创作。',w,claim='situational_engagement')],
            [_sentence(f'{label}是你这次旅程里的一段动手经历。',w),_sentence(line,w),
             _sentence('这次尝试，让你有了一件自己参与完成的作品。',w)]])
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
            [_sentence('和别人一起活动时，你也有主动的一面。',a,b,claim='situational_initiative'),
             _sentence(f'两次{label}都是你先发起邀请，随后和{people}一起参与。',a,b)],
            [_sentence(f'两次{label}，都是从你发出邀请开始的。',a,b),
             _sentence(f'随后，你也和{people}一起参加了活动。',a,b),
             _sentence('主动联系，再一起参与，是你在这两次相处中实际做出的选择。',a,b,claim='situational_initiative')],
            [_sentence(f'你先后发起了两次{label}，也都参与其中。',a,b),
             _sentence('在这两次活动里，你既是发出邀请的人，也是一起参与的同伴；这也是你在这次旅程中主动联系别人的一面。',a,b,claim='situational_initiative')]])
    elif active:
        c=active[0];label=c['label']
        group('initiative',[[ _sentence(f'那次{label}，是由你先发起邀请的。',c),
            _sentence('随后你也参与了活动，让这次联系有了共同经历。',c),
            _sentence('至少在这一次相处里，你愿意主动联系别人。',c,claim='situational_initiative')]])
    else:
        invited=next((c for c in social if c['organized']),None)
        joined=next((c for c in social if c['participated']),None)
        if invited:
            c=invited;status='这项安排后来取消了。'if c['plan_status']=='cancelled'else'这份邀请是你当时发起的一次联系。'
            group('invitation',[[ _sentence(f'你曾发起一起参加{c["label"]}的邀请。',c),
                _sentence(status,c),_sentence('从这次邀请里，可以看到你当时想和别人一起活动的意愿。',c,claim='situational_intention')]])
        elif joined:
            c=joined
            group('participation',[[ _sentence(f'你参加过一次和同伴一起的{c["label"]}。',c),
                _sentence('在那次活动里，你也有了和别人共同参与的经历。',c)]])
    thanks=next((c for c in cards if c['kind']=='gratitude'),None)
    if thanks:
        c=thanks;q=c['quote'];channel='私人留言'if c['public']is False else'公开留言'
        group('gratitude',[
            [_sentence(f'你在一条{channel}里写下：“{q}”。',c),
             _sentence('这句话表达了你当时的感谢。',c,claim='expressed_appreciation')],
            [_sentence(f'还有一段话，来自你的{channel}：“{q}”。',c),
             _sentence('你把当时的感谢，用自己的话写了下来。',c,claim='expressed_appreciation')],
            [_sentence(f'回看这次旅程，也能读到你在{channel}里写的“{q}”。',c),
             _sentence('这是你在那个时刻表达的感谢。',c,claim='expressed_appreciation')]],role='closing')
    if not groups:
        # Use descriptive fallback text for routine actions.
        if facts['coverage']['player_actions']:
            text='这次岛屿之旅已经留下了一些片段。眼下可以把它们作为这段经历的回看；仅凭这些片段，还不适合概括你的做事或相处方式。你可以按自己的感受理解这次体验。'
        else:
            text='这次还没有留下可供回看的游玩片段。暂时没有可以具体回应你的经历，也就不急着给你一个性格印象。'
        group('short_letter',[[{'text':text,'fact_ids':[],'claim':'scope_notice'}]])
    return {'version':VERSION,'facts_sha256':digest(facts),'groups':groups,'paragraph_count':len(groups)}
