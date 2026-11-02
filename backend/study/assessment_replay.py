"""Offline review of gameplay evidence; excluded from production assessment."""
from collections import Counter, defaultdict
import json
import re
import sqlite3

VERSION = 'offline-evidence-audit-v0.2'
CODE_LABELS = {
    'offer_help': '提出帮助意愿（尚不代表实际帮助）',
    'request_learning_or_instructions': '请求学习或操作说明',
    'express_trying_intent': '表达尝试意愿',
    'express_participation_intent': '表达参与或邀约意愿',
    'express_contextual_preference': '表达当下选择偏好',
    'greeting': '问候（不作为人格评分证据）',
}
READ_TABLES = frozenset({
    'sessions', 'world_states', 'world_actions', 'world_atomic_action_executions',
    'world_player_records', 'user_posts', 'interactions',
    'world_commitments', 'world_plan_members',
    'world_emergent_event_runtimes',
    'world_conversation_turns',
})
IGNORED = frozenset({'end_day', 'wait', 'simulation_pause', 'simulation_resume',
                     'holiday_phone_open', 'player_appearance', 'opportunity_seen',
                     'object_narration', 'interaction_focus', 'end_conversation'})


def restrict_reads(connection):
    """Deny all writes and reads outside the gameplay allowlist, including BFI."""
    def authorize(action, table, column, database, trigger):
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if table in READ_TABLES else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and table == 'read_uncommitted' and column is None:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_TRANSACTION and table in ('BEGIN', 'ROLLBACK'):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)


def obj(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def language_candidates(text):
    """Closed observable speech acts; ambiguous material goes to manual review.

    Deliberately no polarity, trait score or automatic psychological inference.
    Broader syntactic/semantic coverage is a future held-out validation task.
    """
    if not text.strip():
        return [], []
    if len(text) > 1000:
        return [], ['long_text_manual_review']
    if re.search(r'[“”"「」]|假如|假设|比如|他说|她说|他们说|系统提示|忽略.*指令', text):
        return [], ['quotation_hypothesis_or_instruction']
    # Conservative abstention includes negative self-descriptions; these must
    # remain in review rather than being silently treated as positive evidence.
    if re.search(r'不想|不愿|不需要|不用|不要|不能|不可以|没必要|不喜欢|不相信', text):
        return [], ['negation_manual_review']
    codes = []
    if re.search(r'(?:需要|要)(?:我|我们).{0,3}(?:帮忙|帮助)|我(?:想|愿意|可以)(?:帮忙|帮助|帮你)', text):
        codes.append('offer_help')
    if re.search(r'(?:教教我|教我|怎么做|如何做|该怎么|想了解|想知道为什么)', text):
        codes.append('request_learning_or_instructions')
    if re.search(r'(?:我也?想|我打算)(?:尝试|试试|设计|创作)', text):
        codes.append('express_trying_intent')
    if re.search(r'(?:我可以来吗|你.{0,5}有空吗|一起.{0,12}(?:吗|吧)|我要参加|我肯定.*参加)', text):
        codes.append('express_participation_intent')
    if re.search(r'我(?:更|很|特别|比较)?(?:喜欢|偏好)|(?:选|选择).{1,12}(?:因为|更)|(?:吧|，).*(?:因为|不仅|而且)', text):
        codes.append('express_contextual_preference')
    if re.search(r'你好|很高兴认识你', text):
        codes.append('greeting')
    return codes, []


def graphical_observation(object_id, payload):
    """Describe the saved design, not aesthetic quality or unlogged drag actions.

    Reference coordinates are the current Workshop.tsx add()/wood targets;
    historical UI identity is unverified, so this is never an autonomy score.
    """
    pieces = payload.get('pieces', [])
    if not isinstance(pieces, list) or not all(isinstance(p, dict) for p in pieces):
        return {'status': 'invalid_saved_design'}
    result = {'piece_count': len(pieces), 'materials': dict(Counter(str(p.get('kind')) for p in pieces)),
              'autonomous_design': 'unknown', 'reference_version': 'Workshop.tsx-current-20261019'}
    if object_id == 'flowers':
        result['positions_differing_from_add_reference'] = sum(
            (p.get('x'), p.get('y')) != (25 + i * 8, 25 + i % 3 * 15) for i, p in enumerate(pieces))
        result['reference_caveat'] = 'final_array_comparison_not_drag_history_or_creativity'
    elif object_id == 'wood_work':
        result['task_structure'] = 'guided_assembly_with_fixed_target_positions'
        result['polished_edges'] = len(set(payload.get('polished', [])))
    return result


def attach_dialogue_context(normalized, turns):
    """Preserve preceding NPC prompt as context, never as participant language."""
    previous = {}
    evidence = {e['source_ref']: e for e in normalized['evidence']}
    added = set()
    for turn in sorted(turns, key=lambda r: r['id']):
        cid = turn['conversation_id']
        if turn.get('speaker_type') in ('agent', 'resident'):
            previous[cid] = turn
        elif turn.get('speaker_type') == 'participant':
            row = evidence.get(f'world_actions:{turn.get("source_action_id")}')
            if not row or row['kind'] != 'player_language':
                continue
            prompt = previous.get(cid)
            row['prompt_context_status'] = 'preceding_npc_turn_available' if prompt else 'no_preceding_turn_recorded'
            if prompt:
                ref = f'world_conversation_turns:{prompt["id"]}'
                row['preceding_context_ref'] = ref
                if ref not in added:
                    added.add(ref)
                    normalized['evidence'].append({'source_ref': ref, 'kind': 'npc_prompt_context',
                        'episode': f'conversation:{cid}', 'text': prompt['content'],
                        'day': prompt.get('world_day'), 'minute': prompt.get('world_time_minutes'),
                        'created_at': prompt.get('created_at'), 'context_only': True,
                        'trait_score': None, 'attribution': 'npc_generated_not_verified_world_fact'})
    return normalized


def normalize(actions, executions=(), records=(), interactions=(), plans=(), members=(), runtimes=()):
    """Return minimal source-linked evidence, without NPC prose/result history."""
    actions = list({a['id']: a for a in actions if a.get('actor_type') == 'participant'}.values())
    by_id = {a['id']: a for a in actions}
    execution_by_action = {e['source_action_id']: e for e in executions
                           if e.get('source_action_id') is not None and e.get('actor_type') == 'participant'}
    wrappers = {}
    for row in actions:
        meta = obj(row.get('metadata_json')); request = obj(meta.get('request'))
        if row['action_type'] == 'activity_experience' and request.get('operation') == 'action' and request.get('idempotency_key'):
            wrappers['scene:' + request['idempotency_key']] = (row, meta, request)
    runtime_plans = {r['id']: r.get('commitment_id') for r in runtimes}
    out, seen, opportunities = [], set(), []

    def add(source, row, kind, **extra):
        ref = f'{source}:{row["id"]}'
        if ref in seen:
            return
        seen.add(ref)
        out.append({'source_ref': ref, 'day': row.get('world_day', row.get('day')),
                    'minute': row.get('world_time_minutes'), 'created_at': row.get('created_at'),
                    'kind': kind, **extra})

    def language(source, row, text, episode, context):
        if not isinstance(text, str) or not text.strip():
            return
        codes, flags = language_candidates(text)
        add(source, row, 'player_language', text=text.strip(), episode=episode,
            context=context, codes=codes, review_flags=flags,
            target_agent_id=row.get('target_agent_id'),
            scope='situational_observation', trait_score=None)

    for row in actions:
        m = obj(row.get('metadata_json')); q = obj(m.get('request')); kind = row['action_type']
        if kind == 'opportunity_seen':
            opportunities.append({'source_ref': f'world_actions:{row["id"]}', 'day': row.get('world_day'),
                                  'kind': q.get('kind'), 'target': q.get('target'),
                                  'eligible': q.get('eligible') is True, 'guided': q.get('guided') is True})
        elif kind in ('conversation_message', 'private_message'):
            # Private messages have no stable conversation ID in v5; conservatively
            # group by recipient/day instead of counting each turn independently.
            ep = (f'conversation:{m.get("conversation_id", row["id"])}' if kind == 'conversation_message'
                  else f'private:{row.get("target_agent_id")}:{row.get("world_day")}')
            language('world_actions', row, row.get('response_text', ''), ep, kind)
        elif kind == 'stage_discussion' and m.get('status') == 'completed':
            language('world_actions', row, q.get('message', ''),
                     f'activity:{m.get("runtime_id", q.get("runtime_id", row["id"]))}', 'cooperation')
        elif kind == 'activity_experience':
            op = q.get('operation'); runtime = m.get('runtime_id', row['id'])
            if op == 'chat':
                language('world_actions', row, q.get('message', ''), f'activity:{runtime}', 'cooperation')
            elif op in ('begin', 'end', 'game'):
                add('world_actions', row, 'activity_operation', operation=op,
                    episode=f'activity:{runtime}', choice_id=q.get('choice_id', ''),
                    plan_id=runtime_plans.get(runtime), title=obj(m.get('result')).get('title'),
                    completed_game=obj(m.get('result')).get('game', {}).get('finished') is True
                    if isinstance(obj(m.get('result')).get('game'), dict) else False)
            # action wrappers duplicate atomic rows; suggest/speech are canned text.
        elif kind == 'atomic_action':
            execution = execution_by_action.get(row['id'])
            if not execution or execution.get('status') != 'completed':
                add('world_actions', row, 'unverified_action', reason='missing_successful_execution')
                continue
            inputs = obj(execution.get('inputs_json'))
            payload = obj(inputs.get('payload'))
            wrapper = wrappers.get(row.get('idempotency_key'))
            linked = bool(wrapper and wrapper[2].get('actor_agent_id') is None
                          and wrapper[2].get('choice_id') == execution['action_id']
                          and obj(wrapper[2].get('inputs')) == inputs and wrapper[1].get('runtime_id') is not None)
            runtime = wrapper[1]['runtime_id'] if linked else None
            add('world_actions', row, 'executed_step', execution_ref=f'world_atomic_action_executions:{execution["id"]}',
                action_id=execution['action_id'], object_id=row.get('target_object_id'),
                command=payload.get('command'), item=payload.get('item'),
                # Successful request != completed craft/game. Only explicit final commands.
                final_submission=payload.get('command') == 'finish_graphical',
                episode=f'activity:{runtime}' if linked else f'object:{row.get("target_object_id")}:{row.get("world_day")}',
                wrapper_ref=f'world_actions:{wrapper[0]["id"]}' if linked else None,
                plan_id=runtime_plans.get(runtime), episode_link='exact_scene_request' if linked else 'conservative_object_day',
                design=graphical_observation(row.get('target_object_id'), payload) if payload.get('command') == 'finish_graphical' else None,
                attribution='participant', trait_score=None)
        elif kind in ('move', 'approach', 'observe', 'dialogue_plan_confirmation'):
            add('world_actions', row, kind, target_location_id=row.get('target_location_id'),
                target_agent_id=row.get('target_agent_id'), trait_score=None)
    for row in records:
        if row.get('source_action_id') in by_id:
            language('world_player_records', row, row.get('body', ''),
                     f'record:{row["id"]}', 'private_reflection' if row.get('visibility') == 'private' else 'public_note')
    # Canonical interaction rows contain human user posts/comments. Exclude agent
    # replies and generated invitation projections even when author_type=participant.
    for row in interactions:
        if row.get('event_type') in ('user_post', 'comment') and not row.get('generation_mode'):
            language('interactions', row, row.get('content', ''),
                     f'public:{row.get("post_id")}:{row.get("world_day")}', 'public_social')
    for row in plans:
        if row.get('organizer_type') == 'participant':
            add('world_commitments', row, 'player_organized_plan', recipe_id=row.get('recipe_id'),
                plan_id=row['id'],
                scheduled_day=row.get('scheduled_day'), scheduled_minute=row.get('scheduled_time_minutes'),
                plan_status=row.get('status'), snapshot_state_only=True, trait_score=None)
    for row in members:
        if row.get('actor_type') == 'participant':
            add('world_plan_members', row, 'player_plan_membership', plan_id=row.get('commitment_id'),
                response_status=row.get('response_status'), attendance_status=row.get('attendance_status'),
                arrival_day=row.get('arrival_day'), arrival_minute=row.get('arrival_time_minutes'),
                snapshot_state_only=True, technical_confound='not_resolved', trait_score=None)
    return {'evidence': out, 'opportunities': opportunities,
            'rejected_execution_count': sum(e.get('actor_type') == 'participant' and e.get('status') != 'completed' for e in executions)}


def summarize(normalized, actions):
    evidence = normalized['evidence']
    language = [e for e in evidence if e['kind'] == 'player_language']
    codes = defaultdict(set)
    for e in language:
        for code in e['codes']:
            codes[code].add(e['episode'])
    ops = normalized['opportunities']
    keys = {(e['kind'], e['target']) for e in ops if e['eligible'] and not e['guided']}
    return {
        'action_rows': len(actions),
        'action_counts': dict(Counter(a['action_type'] for a in actions)),
        'interaction_days': sorted({a['world_day'] for a in actions if a['action_type'] not in IGNORED}),
        'language_utterances': len(language), 'language_characters': sum(len(e['text']) for e in language),
        'language_episodes': len({e['episode'] for e in language}),
        'language_days': sorted({e['day'] for e in language if e['day'] is not None}),
        'observation_codes_by_episode': {k: len(v) for k, v in sorted(codes.items())},
        'executed_steps': sum(e['kind'] == 'executed_step' for e in evidence),
        'explicit_graphical_final_submissions': sum(e.get('final_submission', False) for e in evidence),
        'graphical_submission_episodes': len({e['episode'] for e in evidence if e.get('final_submission')}),
        'rejected_executions': normalized['rejected_execution_count'],
        'player_organized_plans': sum(e['kind'] == 'player_organized_plan' for e in evidence),
        'recorded_arrivals': sum(e['kind'] == 'player_plan_membership' and e.get('arrival_day') is not None for e in evidence),
        'opportunity_view_rows': len(ops), 'unique_eligible_unguided_targets': len(keys),
        'opportunity_interpretation': 'unique_target_views_not_per_day_available_choice_denominators' if ops else 'not_recorded_in_this_version',
        'trait_scores': None,
        'limitations': ['single_owner_development_play', 'no_validated_behavior_trait_mapping',
                        'opportunity_absence_is_unknown_not_refusal', 'no_cross_session_score_pooling'],
    }
