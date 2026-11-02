"""Extract observations and attributed quotations from gameplay records."""
from collections import Counter
import re

VERSION = 'everyday-observations-v1'
BOOKS = {'walden': '《瓦尔登湖》', 'meditations': '《沉思录》', 'stray_birds': '《飞鸟集》'}


def extend_facts(rows, cards, coverage):
    from study.controlled_report import obj, _language_safe
    actions = {a['id']: a for a in rows['world_actions']}
    executions = {x.get('source_action_id'): x for x in rows['world_atomic_action_executions']}
    ledger = {prefix + str(r['id']): 'context_only'
              for table, prefix in (('world_conversation_turns', 'T'), ('user_posts', 'P'),
                                    ('interactions', 'I'), ('world_player_records', 'R'))
              for r in rows[table]}
    seen = {}
    existing_refs = {r for c in cards for r in c['source_refs']}

    def add(kind, refs, **fields):
        c = dict(id=kind + ':' + refs[0], kind=kind, source_refs=refs, **fields)
        cards.append(c)
        for ref in refs:
            ledger[ref] = 'literal_observation'
            if ref in coverage:
                coverage[ref]['disposition'] = 'literal_observation'
        return c

    def quote(text, refs, channel, day, minute):
        # Filter complete utterances to preserve qualifiers.
        if (not _language_safe(text) or len(text.strip()) < 8
                or (len(text.strip()) < 16 and re.match(r'^(好的|好啊|嗯|行|知道了)[ ，,.。]', text))
                or re.search(r'(?:\d[ -]?){7,}|忽略.{0,12}(?:指令|规则)|system\s*prompt|assistant:|API.?key|'
                             r'身份证|住址|病史|诊断|抑郁|自杀|自残|服药|减脂', text, re.I)):
            return
        if any(r in existing_refs for r in refs):
            ledger.update({r: 'already_in_specific_fact' for r in refs})
            return
        # A post and its interaction mirror must not count as two expressions.
        key = text.strip()
        if key in seen:
            prior = seen[key]
            prior['source_refs'].extend(r for r in refs if r not in prior['source_refs'])
            ledger.update({r: 'duplicate_expression' for r in refs})
            return
        appreciation = bool(re.fullmatch(
            r'(?:味道(?:很|挺|真)?不错[哦噢呀呢！，,。\s]*)?'
            r'(?:你的|你做的)(?:手艺|咖啡|插花|木工|作品)(?:真|很|挺)?'
            r'(?:不错|好看|好喝|好吃)[哦噢呀呢！，。\s]*', text))
        seen[key] = add('expression', refs, quote=text, channel=channel,
                        day=day, minute=minute, state='expressed', inference='none',
                        speech_act='explicit_appreciation' if appreciation else 'literal_only')

    for a in rows['world_actions']:
        ref = 'A' + str(a['id'])
        if a.get('actor_type') != 'participant':
            continue
        meta = obj(a.get('metadata_json'))
        request = obj(meta.get('request'))
        if a.get('action_type') in ('conversation_message', 'private_message'):
            if coverage[ref]['disposition'] == 'conflicting_language':
                continue
            refs = [ref] + ['T' + str(t['id']) for t in rows['world_conversation_turns']
                           if t.get('source_action_id') == a['id']
                           and t.get('speaker_type') == 'participant'
                           and t.get('content') == a.get('response_text')]
            quote(a.get('response_text'), refs,
                  'private_message' if a['action_type'] == 'private_message' else 'dialogue',
                  a.get('world_day'), a.get('world_time_minutes'))
        elif a.get('action_type') == 'activity_experience' and request.get('operation') == 'chat':
            if request.get('actor_agent_id') is None:
                quote(request.get('message'), [ref], 'activity_chat',
                      a.get('world_day'), a.get('world_time_minutes'))
        elif a.get('action_type') == 'atomic_action':
            # Reuse execution validation performed by the main extractor.
            if coverage[ref]['disposition'] != 'verified_routine_context':
                continue
            ex = executions[a['id']]
            p = obj(obj(ex.get('inputs_json')).get('payload'))
            aid = ex.get('action_id'); command = p.get('command')
            description = None; topic = None
            if aid == 'v4_books__read' and p.get('item') in BOOKS:
                description = '翻看了' + BOOKS[p['item']] + '的节选'; topic = 'reading'
            elif aid == 'v4_games__play' and command in ('move', 'batch'):
                description = '尝试移动华容道里的滑块'; topic = 'puzzle'
            elif aid == 'v4_beach__shell' and command == 'find':
                description = '在沙滩寻物中寻找贝壳'; topic = 'search'
            elif aid == 'v4_cafe_menu__order' and command == 'confirm':
                description = '在咖啡店点了单'; topic = 'cafe'
            elif aid == 'v4_postcards__browse' and p.get('item'):
                description = '浏览了明信片墙上的留言'; topic = 'postcards'
            elif aid == 'v4_photos__browse' and p.get('item'):
                description = '浏览了摄影作品'; topic = 'photos'
            if description:
                prior = next((c for c in cards if c['kind'] == 'everyday_action'
                              and c['description'] == description), None)
                refs = [ref, 'X' + str(ex['id'])]
                if prior:
                    prior['source_refs'].extend(refs)
                    coverage[ref]['disposition'] = 'same_observation_merged'
                else:
                    add('everyday_action', refs, description=description, topic=topic,
                        day=a.get('world_day'), minute=a.get('world_time_minutes'), state='observed')

    for p in rows['user_posts']:
        ref = 'P' + str(p['id']); ledger.setdefault(ref, 'nonparticipant_or_unusable')
        if p.get('author_type') == 'participant':
            quote(p.get('content'), [ref], 'post', p.get('day'), p.get('world_time_minutes'))
    for i in rows['interactions']:
        ref = 'I' + str(i['id']); ledger.setdefault(ref, 'context_only')
        # agent_reply is the NPC's speech. user_post is already read above.
        if i.get('event_type') == 'comment':
            quote(i.get('content'), [ref], 'comment', i.get('world_day'), i.get('world_time_minutes'))
    for r in rows['world_player_records']:
        ref = 'R' + str(r['id']); ledger.setdefault(ref, 'unverified_authorship')
        a = actions.get(r.get('source_action_id'))
        if not a or a.get('actor_type') != 'participant':
            continue
        ex = executions.get(a['id'])
        if not ex or ex.get('status') != 'completed' or ex.get('actor_type') != 'participant':
            continue
        inputs = obj(ex.get('inputs_json'))
        key = 'private_note' if r.get('visibility') == 'private' else 'public_note'
        if inputs != obj(obj(obj(a.get('metadata_json')).get('atomic_action')).get('inputs')):
            continue
        if not isinstance(inputs.get(key), str) or inputs[key].strip() != r.get('body'):
            continue
        if r.get('visibility') not in ('private', 'island_public'):
            continue
        quote(r.get('body'), [ref, 'A' + str(a['id'])],
              'private_note' if r['visibility'] == 'private' else 'public_note',
              r.get('world_day'), r.get('world_time_minutes'))
    return {'version': VERSION, 'source_dispositions': dict(Counter(ledger.values())),
            'ledger': ledger}


def append_groups(facts, catalog):
    from study.controlled_report import _sentence
    groups = [g for g in catalog['groups'] if g['id'] != 'short_letter']
    used = {i for g in groups for v in g['variants'] for s in v['sentences'] for i in s['fact_ids']}
    byid = {c['id']: c for c in facts['cards']}
    used_refs = {r for i in used for r in byid[i]['source_refs']}
    expressions = [c for c in facts['cards'] if c['kind'] == 'expression'
                   and not set(c['source_refs']) & used_refs]
    additions = []

    def group(key, alternatives):
        additions.append({'id': key, 'role': 'body', 'variants': [
            {'id': key + ':' + str(i), 'sentences': ss, 'text': ''.join(s['text'] for s in ss)}
            for i, ss in enumerate(alternatives)]})

    # Keep channels separate and limit quoted examples.
    channel_labels = {'post': '你在动态里写道', 'comment': '你在评论里说',
                      'dialogue': '和居民聊天时，你说', 'private_message': '你在私信里说',
                      'activity_chat': '一起活动时，你说', 'private_note': '你在私人留言里写道',
                      'public_note': '你在公开留言里写道'}
    posts = [c for c in expressions if c['channel'] in ('post', 'public_note', 'private_note')]
    comments = [c for c in expressions if c['channel'] == 'comment']
    social = posts[:1] + comments[-1:]
    if social:
        group('everyday_social', [[_sentence(f'{channel_labels[c["channel"]]}：“{c["quote"]}”。', c)
                                   for c in social],
                                  [_sentence(f'这次，{channel_labels[c["channel"]]}：“{c["quote"]}”。', c)
                                   if i == 0 else _sentence(f'在评论里，你还说过：“{c["quote"]}”。', c)
                                   for i, c in enumerate(social)]])
    dialogue = [c for c in expressions if c['channel'] in ('dialogue', 'activity_chat', 'private_message')]
    if dialogue:
        selected = [dialogue[0]] + ([dialogue[-1]] if len(dialogue) > 1 else [])
        # Retain the speaker attribution throughout each paragraph.
        sentences = [_sentence(f'{channel_labels[c["channel"]]}：“{c["quote"]}”。', c)
                     if i == 0 else _sentence(f'你也对居民说过：“{c["quote"]}”。', c)
                     for i, c in enumerate(selected)]
        appreciation = next((c for c in selected if c.get('speech_act') == 'explicit_appreciation'), None)
        if appreciation:
            sentences.append(_sentence('在那次交流里，你把自己的肯定直接告诉了对方。',
                                       appreciation, claim='expressed_appreciation'))
        group('everyday_dialogue', [sentences])
    routine = [c for c in facts['cards'] if c['kind'] == 'everyday_action']
    reading = [c for c in routine if c['topic'] == 'reading'][:2]
    if reading:
        if len(reading) == 2:
            a, b = reading
            sentence = '在读书角，你' + a['description'] + '，也' + b['description'] + '。'
        else:
            sentence = '在读书角，你' + reading[0]['description'] + '。'
        group('reading', [[_sentence(sentence, *reading)]])
    elif routine:
        c = routine[0]
        group('everyday', [[_sentence('这次在岛上，你' + c['description'] + '。', c)]])
    # Keep stronger supported interpretations ahead of routine observations.
    closing = [g for g in groups if g['role'] == 'closing']
    body = [g for g in groups if g['role'] != 'closing']
    result = body + additions[:max(0, 5 - len(groups))] + closing
    return result or catalog['groups']
