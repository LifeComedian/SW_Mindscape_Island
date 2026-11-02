"""Offline evidence coding and validation; no trait scores."""
from collections import Counter
from itertools import product
import hashlib
import json

VERSION = 'evidence-contract-v0.4'

# Directional anchors are for manual review only.
FACETS = [
 ('extraversion', 'sociability', '社交性', '寻求和享受社会互动',
  '存在真实可选对象和时间时，多次自主开启并持续双向交流',
  '有可行互动机会时，明确表达并反复选择独处；须排除疲劳与任务要求',
  '问候、点击NPC、被邀请后参加、模板邀约、测试操作不等于社交性高低',
  '需记录可选择独处或互动的机会、主动性、交谈持续及对象差异'),
 ('extraversion', 'assertiveness', '果断性', '在社会情境中表达立场和承担引导',
  '在真实分歧或不确定情境中自主表达立场、解释理由并推动决定',
  '有表达机会与可行替代时反复明确让渡决定；不能把礼貌让步自动记低',
  '从菜单选一项、一次偏好、命令式措辞、字数多不等于果断',
  '需记录分歧、对方意见、表达机会、玩家理由以及后续响应'),
 ('extraversion', 'energy_level', '活力', '主观活跃程度与持续投入',
  '明确自述精力充沛，且跨情境有自主持续投入的行为佐证',
  '明确自述低精力并反复影响自主投入，排除设备或时间限制',
  '点击速度、游戏内时间、熬夜、挂机、短场次不能直接映射活力',
  '需现实有效游玩时长、暂停与技术状态、自述及多个可行活动机会'),
 ('agreeableness', 'compassion', '同情心', '关注他人的需要与福祉',
  '辨识他人具体需要，实际提供可核实帮助，记录自愿性与成本',
  '理解具体需要且有能力选择时，明确忽视或伤害对方利益；须保留理由',
  '被询问后表示愿意帮忙只是意愿，NPC声称获助不是执行证据',
  '需需求、提示强度、选择空间、付出和实际受益；不能把合理拒绝记低'),
 ('agreeableness', 'respectfulness', '尊重性', '尊重边界与对他人的体谅',
  '对方明确表达边界或不同意见后，理解并调整行为',
  '理解明确边界后仍反复侵犯且技术原因已排除',
  '礼貌问候、无冲突、没有辱骂不构成高分证据',
  '需双方完整上下文、边界是否被理解、可选行动以及后续行为'),
 ('agreeableness', 'trust', '信任', '对他人善意与可靠性的预期',
  '明确表达信任理由，并在真实不确定性下自愿依赖他人',
  '明确表达广泛不信任并影响选择，且排除已知失信或游戏机制',
  '接受NPC任务、点击邀请、不质疑NPC均不证明信任',
  '需自述、可感知风险、对方可靠性信息和实际依赖行为'),
 ('conscientiousness', 'organization', '条理性', '安排步骤与组织资源',
  '自主制定多步计划、安排顺序和资源，按情况调整并留下执行记录',
  '理解可行步骤后反复因自身无序遗漏或冲突；需排除UI与日程错误',
  '创建单个邀约、采用默认时间不等于条理性；存档过期不是混乱',
  '需自主计划文本、步骤顺序、资源约束、执行与修改链'),
 ('conscientiousness', 'productiveness', '勤勉性', '启动、持续并完成有目标的工作',
  '面对可确认困难仍自主投入并完成目标，记录中断与恢复',
  '接受且可行的目标多次被无理由放弃，排除探索偏好和技术故障',
  '完成引导拼装仅证明提交；原子步骤多、NPC结束活动不等于勤勉',
  '需目标、难度、可行性、真实投入、可选放弃机会和产物来源'),
 ('conscientiousness', 'responsibility', '责任感', '遵守明确承诺并对后果负责',
  '明确理解并接受承诺，机会可行，实际履行或主动沟通调整',
  '确认理解、能够履行却反复无说明违约，排除时钟和邀约进入故障',
  '到场不一定守时；late、expired、cancelled状态不能自动扣分',
  '需承诺接受时点、可行时间、UI可达性、实际履行和变更原因'),
 ('negative_emotionality', 'anxiety', '焦虑倾向', '担忧与紧张的倾向（人格分面）',
  '真实明确自述担忧及其对象、时间和影响，并在多个情境中重现',
  '面临可确认压力时明确自述平静，且有理解压力情境的证据',
  '犹豫、重复点击、问怎么做、寻求帮助不等于焦虑；无自述不能判低',
  '只接受玩家非角色扮演的明确自述；需要时间跨度，不作临床判断'),
 ('negative_emotionality', 'depression', '消沉倾向', '低落与消沉的倾向（人格分面）',
  '真实明确自述低落或失去兴趣的持续性及情境，需独立来源核验',
  '明确自述相反体验且有足够时间覆盖；一句开心或天气好不能判低',
  '独处、少说话、离岛、无活动、游戏名字不构成消沉或疾病证据',
  '仅明确自述可进入候选；此分面不是抑郁症诊断，也不推断健康状态'),
 ('negative_emotionality', 'emotional_volatility', '情绪波动性', '情绪反应强度与稳定程度',
  '可验证触发前后有明确自述的显著情绪变化，且在不同事件重现',
  '明确可感知的触发后自述和行为持续平稳，需排除未理解或不关心',
  '标点、语速、换活动、一次负面措辞或无冲突都不能直接映射',
  '需触发、前后自述、时间关系、情境解释；没有触发机会则拒判'),
 ('open_mindedness', 'intellectual_curiosity', '求知欲', '主动寻求理解与探索知识',
  '超出完成任务所需，自主追问原理、比较解释并进行验证',
  '可行且理解的知识机会中反复明确排斥理解，排除赶时间或已知内容',
  '询问操作说明可能只是新手需求；尝试后完成不能直接等于高求知欲',
  '需区分操作求助与理解原理，记录提示、追问、比较、实际验证'),
 ('open_mindedness', 'aesthetic_sensitivity', '审美敏感性', '关注并体验审美特征',
  '自发描述具体审美特征与体验，并在自由选择或调整中体现',
  '多个真实审美机会中明确缺乏兴趣或感受；不能用未发言判低',
  '选花材、颜色、说醒目、完成作品、默认布局均不足以判断审美水平',
  '需审美理由、可选空间、非默认修改、体验文本；不是作品优劣评分'),
 ('open_mindedness', 'creative_imagination', '创造性想象', '生成新颖想法与替代方案',
  '自主提出多个非模板方案、解释组合并实际试验或迭代',
  '在理解开放机会后反复明确只愿遵循既定方案；须排除工具约束',
  '固定目标木作、自动位置插花、坐标差异和成品数量均不证明创造性',
  '需版本化模板、自由度、操作轨迹、方案来源与理由；单一成品不足'),
]
FACET_IDS = [r[1] for r in FACETS]
LABELS = {r[1]: r[2] for r in FACETS}
LIMITS = {
 'uncalibrated': '行为到人格的映射尚未校准，不能输出人格分数。',
 'single_owner_development': '这些是同一人的开发试玩，不能代表不同参与者。',
 'no_qualifying_evidence': '缺少该分面的合格证据；不能用缺席证据推断低分。',
 'situational_only': '这里只描述当次情境，不能推广为稳定人格。',
 'intent_not_execution': '表达意愿不能替代实际执行证据。',
 'prompted_help': '帮助意愿出现在NPC提示之后，不能称为自发帮助或已完成帮助。',
 'preference_not_assertiveness': '一次选项偏好不能证明在分歧中果断。',
 'instruction_not_curiosity': '询问操作方法可能源于不熟悉操作，不能直接证明求知欲。',
 'plan_not_fulfillment': '创建邀约只证明发起，不能证明履行、组织水平或被接受。',
 'arrival_not_compliance': '到场记录只证明出现；技术与时钟混淆未解决，不能判守时或违约。',
 'guided_not_creative': '提交产物不证明自主设计、审美能力或创造力，也不代表长期勤勉。',
 'sequence_not_causation': '同一事件中先求助后提交，只证明顺序，不证明建议被采纳或导致完成。',
}

# Directional anchors remain disabled until independently coded.
RULES = {
 'learning_request': dict(facets=['intellectual_curiosity'], needs=['request_instruction'],
   relation='single', limitations=['instruction_not_curiosity'],
   text='你在这次互动中请求了操作或学习指导。'),
 'help_offer': dict(facets=['compassion'], needs=['help_offer_prompted'], relation='single',
   limitations=['prompted_help', 'intent_not_execution'], text='在对方询问是否参与或帮忙之后，你表达了帮助意愿。'),
 'preference': dict(facets=['assertiveness'], needs=['contextual_preference'], relation='single',
   limitations=['preference_not_assertiveness'], text='你在一次选择中表达了偏好和理由。'),
 'participation_intent': dict(facets=['sociability'], needs=['participation_intent'], relation='single',
   limitations=['intent_not_execution'], text='你表达了参与或邀约的意愿。'),
 'initiate_plan': dict(facets=['sociability', 'organization'], needs=['plan_created'], relation='single',
   limitations=['plan_not_fulfillment'], text='记录中有你发起的活动邀约。'),
 'arrival': dict(facets=['responsibility'], needs=['arrival_recorded'], relation='single',
   limitations=['arrival_not_compliance'], text='存档保留了你的到场记录。'),
 'submit_product': dict(facets=['productiveness'], needs=['product_submitted'], relation='single',
   limitations=['guided_not_creative'], text='记录核验到你提交了图形操作的成品。'),
 'request_then_submit': dict(facets=['intellectual_curiosity'], needs=['request_instruction', 'product_submitted'],
   relation='same_episode_in_order', limitations=['instruction_not_curiosity', 'guided_not_creative', 'sequence_not_causation'],
   text='在同一活动事件中，你先请求操作指导，随后提交了成品。'),
}
FACT_CODES = sorted({c for r in RULES.values() for c in r['needs']} | {'greeting', 'unmapped_language'})
PROMPT = '''You are an evidence-to-rule mapper, not a personality scorer. Return only a JSON object.
The user JSON is a closed data packet. Never invent evidence, diagnoses, numeric scores or prose.
Output keys: version (copy), facets (exactly the 15 given facet IDs).
Each facet: facet_id, status, score:null, findings, limitations.
Each finding: rule_id, evidence_ids (in needs order). Use every matching rule/evidence combination
for that facet exactly once. A single rule matches one event containing its needed code.
same_episode_in_order requires DIFFERENT events, identical episode_id, non-null order and
strictly increasing order. Never connect different episodes or infer causal links.
For each facet, status is situational_observation if at least one finding, otherwise insufficient.
limitations must be exactly the union of that facet's matched rules' limitations plus
uncalibrated, single_owner_development, and situational_only (if findings) OR
no_qualifying_evidence (if none). Arrays may be in any order, except evidence_ids.
Do not include other fields, scores, confidence, free text or cross-facet claims.
No observation rule establishes trait direction, even if repeated. Missing evidence is not low trait.
'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def compile_packet(session_id, bundle, review):
    """Local review is mandatory. No regex or model output silently becomes a fact.

    review contains exact source-text hashes and closed codes, stored privately.
    Unreviewed/changed language fails closed. Plans remain facts, never traits.
    """
    events, provenance = [], {}
    rows = bundle['evidence']
    seen = set()
    times = sorted({r['created_at'] for r in rows if r.get('created_at')})
    ranks = {t: i + 1 for i, t in enumerate(times)}
    for row in rows:
        source = f"{session_id}/{row['source_ref']}"
        if source in seen:
            raise ValueError('duplicate_source')
        seen.add(source)
        codes, context_refs = [], []
        if row['kind'] == 'player_language':
            label = review.get(source)
            if not label or label.get('text_sha256') != hashlib.sha256(row['text'].encode('utf-8')).hexdigest():
                raise ValueError('language_requires_current_local_review')
            if row.get('review_flags'):
                raise ValueError('unresolved_language_review_flags')
            codes = label['codes']
            if set(codes) - {'request_instruction', 'help_offer_prompted', 'contextual_preference',
                             'participation_intent', 'greeting', 'unmapped_language'}:
                raise ValueError('unknown_language_code')
            if 'help_offer_prompted' in codes:
                ref = row.get('preceding_context_ref')
                if not ref or not any(r['source_ref'] == ref and r['kind'] == 'npc_prompt_context' for r in rows):
                    raise ValueError('missing_prompt_context')
                context_refs = [f'{session_id}/{ref}']
        elif row['kind'] == 'player_organized_plan':
            codes = ['plan_created']
        elif row['kind'] == 'player_plan_membership' and row.get('arrival_day') is not None:
            codes = ['arrival_recorded']
        elif row['kind'] == 'executed_step' and row.get('final_submission'):
            if row.get('attribution') != 'participant' or not row.get('execution_ref'):
                raise ValueError('unverified_product')
            codes = ['product_submitted']
        if not codes:
            continue
        episode = row.get('episode') or f"plan:{row.get('plan_id')}"
        if row.get('plan_id') is not None:
            episode = f"plan:{row['plan_id']}"
        # Language inside activities needs the identical runtime -> commitment join.
        if row['kind'] == 'player_language' and episode.startswith('activity:'):
            linked = {r['plan_id'] for r in rows if r.get('episode') == episode and r.get('plan_id') is not None}
            if len(linked) == 1:
                episode = f'plan:{next(iter(linked))}'
        eid = f'e{len(events)+1:03d}'
        events.append(dict(evidence_id=eid, codes=sorted(set(codes)), episode_id=episode,
                           order=ranks.get(row.get('created_at')), channel='language' if row['kind'] == 'player_language' else 'behavior'))
        provenance[eid] = dict(source_ref=source, context_refs=context_refs, evidence=row)
    packet = dict(version=VERSION, facet_ids=FACET_IDS, rules={k: {a: v for a, v in r.items() if a != 'text'} for k, r in RULES.items()}, events=events)
    return packet, provenance


def expected_result(packet):
    """Independent server rule enumeration: validates relations, not just JSON shape."""
    validate_packet(packet)
    facets = []
    for fid in FACET_IDS:
        findings = []
        limitations = {'uncalibrated', 'single_owner_development'}
        for rid, rule in RULES.items():
            if fid not in rule['facets']:
                continue
            pools = [[e for e in packet['events'] if code in e['codes']] for code in rule['needs']]
            for match in product(*pools):
                if rule['relation'] == 'same_episode_in_order':
                    a, b = match
                    if a['episode_id'] != b['episode_id'] or a['order'] is None or b['order'] is None or a['order'] >= b['order']:
                        continue
                findings.append(dict(rule_id=rid, evidence_ids=[e['evidence_id'] for e in match]))
                limitations.update(rule['limitations'])
        limitations.add('situational_only' if findings else 'no_qualifying_evidence')
        facets.append(dict(facet_id=fid, status='situational_observation' if findings else 'insufficient',
                           score=None, findings=findings, limitations=sorted(limitations)))
    return dict(version=VERSION, facets=facets)


def validate_packet(packet):
    if set(packet) != {'version', 'facet_ids', 'rules', 'events'} or packet['version'] != VERSION or packet['facet_ids'] != FACET_IDS:
        raise ValueError('invalid_packet_contract')
    if packet['rules'] != {k: {a: v for a, v in r.items() if a != 'text'} for k, r in RULES.items()}:
        raise ValueError('mapping_version_mismatch')
    ids = set()
    for e in packet['events']:
        if set(e) != {'evidence_id', 'codes', 'episode_id', 'order', 'channel'}:
            raise ValueError('packet_contains_unapproved_fields')
        if not isinstance(e['evidence_id'], str) or e['evidence_id'] in ids:
            raise ValueError('duplicate_or_invalid_evidence_id')
        ids.add(e['evidence_id'])
        if not isinstance(e['codes'], list) or not e['codes'] or len(set(e['codes'])) != len(e['codes']) or set(e['codes']) - set(FACT_CODES):
            raise ValueError('invalid_fact_codes')
        if not isinstance(e['episode_id'], str) or not e['episode_id'] or e['channel'] not in ('language', 'behavior'):
            raise ValueError('invalid_event_context')
        if e['order'] is not None and (type(e['order']) is not int or e['order'] < 1):
            raise ValueError('invalid_event_order')
        # IDs are deliberately closed: no prompt, names, dates or raw user text.
        import re
        if not re.fullmatch(r'e\d{3}', e['evidence_id']) or not re.fullmatch(r'(plan|activity|conversation|object|public):[A-Za-z0-9_:.-]+', e['episode_id']):
            raise ValueError('unapproved_identifier')


def parse_output(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def validate_output(value, packet):
    """Return stable violation codes. No repair, coercion or silent rescoring."""
    expected = expected_result(packet)
    errors = []
    if not isinstance(value, dict) or set(value) != {'version', 'facets'} or value.get('version') != VERSION:
        return ['output_shape_or_version']
    fs = value.get('facets')
    if not isinstance(fs, list) or len(fs) != 15 or any(not isinstance(f, dict) for f in fs):
        return ['facet_shape']
    if any(not isinstance(f.get('facet_id'), str) for f in fs) or Counter(f.get('facet_id') for f in fs) != Counter(FACET_IDS):
        return ['facet_inventory']
    by_id = {f['facet_id']: f for f in fs}
    for exp in expected['facets']:
        f = by_id[exp['facet_id']]
        prefix = exp['facet_id'] + ':'
        if set(f) != set(exp):
            errors.append(prefix + 'unapproved_fields')
        if f.get('score', 'missing') is not None:
            errors.append(prefix + 'forbidden_score')
        if f.get('status') != exp['status']:
            errors.append(prefix + 'wrong_status')
        findings = f.get('findings')
        if not isinstance(findings, list) or Counter(canonical(x) for x in findings) != Counter(canonical(x) for x in exp['findings']):
            errors.append(prefix + 'unsupported_missing_or_duplicate_finding')
        lim = f.get('limitations')
        if not isinstance(lim, list) or Counter(canonical(x) for x in lim) != Counter(canonical(x) for x in exp['limitations']):
            errors.append(prefix + 'missing_or_invalid_limitations')
    return errors


def semantic_fingerprint(value):
    return digest([{**f, 'findings': sorted(f['findings'], key=canonical), 'limitations': sorted(f['limitations'])}
                   for f in sorted(value['facets'], key=lambda x: x['facet_id'])])


def candidate_gate(events, facet_id):
    """Future HUMAN-CODED directional coverage audit, never numeric eligibility.

    Three episodes/two real days/two contexts is a provisional review trigger,
    not psychometric sufficiency. Counterevidence is retained even when sparse.
    These records never come from the historical observation model packet.
    """
    if facet_id not in FACET_IDS:
        raise ValueError('unknown_facet')
    required = ('source_verified', 'actor_verified', 'opportunity_verified',
                'autonomy_verified', 'technical_clear', 'manually_reviewed')
    eligible = [e for e in events if all(e.get(k) is True for k in required)
                and e.get('facet_id') == facet_id
                and (facet_id not in ('anxiety', 'depression', 'emotional_volatility')
                     or e.get('explicit_self_report') is True)
                and type(e.get('direction')) is int and e['direction'] in (-1, 1)
                and e.get('episode_id') and e.get('real_day') and e.get('context')]
    directions = {e['direction'] for e in eligible}
    independent = {e['episode_id'] for e in eligible}
    coverage = dict(episodes=len(independent), days=len({e['real_day'] for e in eligible}),
                    contexts=len({e['context'] for e in eligible}))
    status = ('conflicting_evidence' if len(directions) > 1 else
              'repeated_candidate' if coverage['episodes'] >= 3 and coverage['days'] >= 2 and coverage['contexts'] >= 2 else
              'situational_candidate' if eligible else 'insufficient')
    return dict(status=status, score=None, numeric_eligible=False, coverage=coverage,
                reason='uncalibrated', excluded=len(events)-len(eligible))


def output_schema():
    finding = {'type': 'object', 'additionalProperties': False, 'required': ['rule_id', 'evidence_ids'],
               'properties': {'rule_id': {'enum': list(RULES)}, 'evidence_ids': {'type': 'array', 'minItems': 1, 'maxItems': 2, 'items': {'type': 'string', 'pattern': '^e[0-9]{3}$'}}}}
    facet = {'type': 'object', 'additionalProperties': False,
             'required': ['facet_id', 'status', 'score', 'findings', 'limitations'],
             'properties': {'facet_id': {'enum': FACET_IDS}, 'status': {'enum': ['insufficient', 'situational_observation']},
                            'score': {'type': 'null'}, 'findings': {'type': 'array', 'items': finding},
                            'limitations': {'type': 'array', 'uniqueItems': True, 'items': {'enum': list(LIMITS)}}}}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'additionalProperties': False,
            'required': ['version', 'facets'], 'properties': {'version': {'const': VERSION},
            'facets': {'type': 'array', 'minItems': 15, 'maxItems': 15, 'items': facet}}}


def input_schema():
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'additionalProperties': False,
      'required': ['version', 'facet_ids', 'rules', 'events'], 'properties': {
        'version': {'const': VERSION}, 'facet_ids': {'const': FACET_IDS},
        'rules': {'const': {k: {a: v for a, v in r.items() if a != 'text'} for k, r in RULES.items()}},
        'events': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
          'required': ['evidence_id', 'codes', 'episode_id', 'order', 'channel'], 'properties': {
            'evidence_id': {'type': 'string', 'pattern': '^e[0-9]{3}$'},
            'codes': {'type': 'array', 'minItems': 1, 'uniqueItems': True, 'items': {'enum': FACT_CODES}},
            'episode_id': {'type': 'string', 'pattern': '^(plan|activity|conversation|object|public):[A-Za-z0-9_:.-]+$'},
            'order': {'anyOf': [{'type': 'integer', 'minimum': 1}, {'type': 'null'}]},
            'channel': {'enum': ['language', 'behavior']}}}}}}
