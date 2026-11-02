"""Local language coding and experimental assessment package."""
import asyncio
from collections import defaultdict
from dataclasses import replace
import hashlib
import json
import re
from study.assessment_interfaces import FeatureExtractionResult
from study.assessment_packages import FIXTURE_PACKAGE, canonical_json
from study.contracts import AssessmentPackageStatus
from study import draft_assessment as draft

METHOD='holiday-coded-experimental-v5.1'
SCHEMA='holiday-coded-features-v5'
OBSERVATION_SCHEMA='holiday-observation-features-v1'
OBSERVATION_METHOD='holiday-observation-only-v1'


def local_feature_schema():
    import os
    return OBSERVATION_SCHEMA if os.getenv('STUDY_OBSERVATION_ONLY', '').lower() == 'true' else SCHEMA
LABELS={'extraversion':'外向性','agreeableness':'宜人性','conscientiousness':'尽责性','negative_emotionality':'负性情绪','open_mindedness':'开放性'}
OBSERVATIONS={
    'sociability':('表达交流偏好','表达独处偏好'), 'assertiveness':('提出由自己组织活动','表达让别人主持的偏好'),
    'energy_level':('自述当前有精力','自述当前精力不足'), 'compassion':('表达帮助别人的意愿',''),
    'respectfulness':('表达听取他人意见的意愿',''), 'trust':('表达对这位居民的信任','表达暂时不愿信任这位居民'),
    'organization':('表达提前计划的习惯','自述通常不做计划'), 'productiveness':('表达完成一件事的打算','自述经常拖延'),
    'responsibility':('表达遵守约定的意愿','自述经常忘记约定'), 'anxiety':('自述当时感到紧张或担心','自述当时感到平静'),
    'depression':('自述当时感到低落','自述当时感到快乐'), 'emotional_volatility':('自述近期情绪有起伏','自述近期情绪稳定'),
    'intellectual_curiosity':('提出了解原因或原理的愿望',''), 'aesthetic_sensitivity':('表达审美偏好',''),
    'creative_imagination':('提出创作或尝试新做法的愿望','')}
PATTERNS={
    'sociability':r'我(?:很|比较|一直)?(?:喜欢|愿意)(?:和人|跟人|与人|和大家)(?:交流|聊天|相处)',
    'assertiveness':r'我(?:想|建议|希望)(?:由我|自己)(?:组织|主持|安排)',
    'energy_level':r'我(?:今天|现在|最近)?(?:很有精力|精力充沛)',
    'compassion':r'我(?:想|愿意)(?:帮助|帮忙|照顾)',
    'respectfulness':r'我(?:会|愿意)(?:尊重|听听)(?:你的|大家的|别人的)(?:意见|想法|选择)',
    'trust':r'我(?:愿意|选择)(?:信任|相信)你',
    'organization':r'我(?:喜欢|习惯)(?:提前计划|提前安排|列计划)',
    'productiveness':r'我(?:想|会|打算)(?:把|将).{1,12}(?:做完|完成)',
    'responsibility':r'我(?:会|一定会)(?:按时赴约|遵守约定|履行承诺)',
    'anxiety':r'我(?:现在|最近|今天)?(?:感到|觉得|有些|很)?(?:焦虑|担心|紧张)',
    'depression':r'我(?:现在|最近|今天)?(?:感到|觉得|有些|很)?(?:难过|低落|沮丧)',
    'emotional_volatility':r'我(?:最近|今天)?(?:情绪起伏很大|情绪变化很快)',
    'intellectual_curiosity':r'我(?:想|希望)(?:了解|弄清|知道)(?:为什么|原理|原因)',
    'aesthetic_sensitivity':r'我(?:很|特别)?(?:喜欢|欣赏)(?:这些|这个|这幅|这种)?(?:木作|配色|画|色彩|花艺|风景)',
    'creative_imagination':r'我(?:想|打算)(?:设计|创作|尝试一种新的|做一个不同的)',
}
COUNTER_PATTERNS={
    'sociability':r'我(?:更|比较)?喜欢独处',
    'assertiveness':r'我(?:通常|更)?愿意让别人主持',
    'energy_level':r'我(?:今天|现在|最近)?(?:没有精力|精力不足)',
    'trust':r'我(?:暂时|现在)?不愿意信任你',
    'organization':r'我(?:通常|习惯)?不做计划',
    'productiveness':r'我经常把事情拖到最后',
    'responsibility':r'我经常忘记约定',
    'anxiety':r'我(?:现在|最近|今天)?(?:感到|觉得)?平静',
    'depression':r'我(?:现在|最近|今天)?(?:感到|觉得)?快乐',
    'emotional_volatility':r'我(?:最近|今天)?情绪(?:一直)?稳定',
}


def extract(db,sid,observations,*,feature_schema=SCHEMA):
    from models import WorldAction
    from content.holiday_v6 import catalogue_for
    from world.registry import get_world_spec
    from models import WorldState
    world=db.query(WorldState).filter_by(session_id=sid).one()
    spec=get_world_spec(world.world_version)
    CATALOGUE=catalogue_for(spec)
    rows=db.query(WorldAction).filter_by(session_id=sid,actor_type='participant').order_by(WorldAction.id).all()
    from models import Interaction, WorldEmergentEventRuntime, WorldCommitment, WorldConversation
    runtimes={r.id:r for r in db.query(WorldEmergentEventRuntime).filter_by(session_id=sid)}
    plans={p.id:p for p in db.query(WorldCommitment).filter_by(session_id=sid)}
    conversations={c.id:c for c in db.query(WorldConversation).filter_by(session_id=sid)}
    recipes={r['recipe_id']:r for r in spec.systems.get('activity_recipes',[])}
    from types import SimpleNamespace
    for comment in db.query(Interaction).filter_by(session_id=sid,event_type='comment',safety_flag=False).order_by(Interaction.id):
        if comment.world_day is None or comment.world_time_minutes is None:continue
        rows.append(SimpleNamespace(id='phone'+str(comment.id),action_type='phone_comment',response_text=comment.content,
            metadata_json=json.dumps({'post_id':comment.post_id}),world_day=comment.world_day,world_time_minutes=comment.world_time_minutes,
            target_object_id=None,target_location_id=None))
    coded,sources,seen=[],{},set()
    opportunity_ids=set()
    guided_until=0
    for row in rows:
        meta=json.loads(row.metadata_json or '{}')
        if row.action_type=='opportunity_seen':
            req=meta.get('request',{})
            if req.get('eligible') and req.get('kind') in ('object','mechanism','invitation'):
                opportunity_ids.add(row.id)
            if req.get('guided'):guided_until=max(guided_until,row.id)
            continue
        if row.action_type not in ('conversation_message','private_message','stage_discussion','activity_experience','atomic_action','defined_action','dialogue_plan_confirmation','move','phone_comment'):
            continue
        # Only player utterances, not replies/rewrites, may contribute language.
        req=meta.get('request',{})
        text=row.response_text if row.action_type in ('conversation_message','private_message','phone_comment') else req.get('message','') if row.action_type=='stage_discussion' or row.action_type=='activity_experience' and req.get('operation')=='chat' else ''
        episode='conversation_'+str(meta.get('conversation_id',row.id)) if row.action_type=='conversation_message' else 'activity_'+str(req.get('runtime_id',meta.get('runtime_id',row.id))) if row.action_type in ('activity_experience','stage_discussion') else 'action_'+str(row.id)
        if row.action_type=='phone_comment':
            # World actions keep the post under request; legacy Interaction
            # adapters use a top-level field. Unknown posts stay separate.
            post_id=meta.get('post_id',req.get('post_id'))
            episode='phone_'+str(post_id) if post_id is not None else 'phone_comment_'+str(row.id)
        context='conversation' if row.action_type in ('conversation_message','private_message','phone_comment') else 'cooperation' if row.action_type in ('activity_experience','stage_discussion') else 'invitation' if row.action_type=='dialogue_plan_confirmation' else 'exploration'
        # Closed source descriptions never copy original text or generated prose.
        atomic=meta.get('atomic_action',{})
        aid=atomic.get('action_id',req.get('action_id',req.get('choice_id','')))
        if not aid:aid=meta.get('request',{}).get('metadata',{}).get('action_id','')
        oid=row.target_object_id or aid.removeprefix('v4_').split('__')[0]
        obj=CATALOGUE.get(oid)
        label=next((a['name'] for a in obj['actions'] if aid.endswith('__'+a['id'])),obj['name']) if obj else '与居民交流' if text else '岛屿探索'
        location_id=row.target_location_id or meta.get('location_id')
        if row.action_type=='activity_experience':
            runtime=runtimes.get(meta.get('runtime_id',req.get('runtime_id')))
            if runtime:
                recipe=recipes.get(runtime.recipe_id,{})
                title=recipe.get('label',{}).get('zh-CN','共同活动')
                operation=req.get('operation')
                label=({'begin':'进入','finish':'结束','chat':'在活动中交流：','game':'参与'}.get(operation,'体验'))+title
                oid='activity:'+runtime.recipe_id
                plan=plans.get(runtime.commitment_id)
                if plan:location_id=plan.location_id
        if row.action_type in ('conversation_message','private_message'):
            person=spec.residents.get(row.target_agent_id)
            name=person.name if person else '居民'
            label=('通过手机与' if row.action_type=='private_message' else '与')+name+'交流'
            oid='resident:'+str(row.target_agent_id)
            conversation=conversations.get(meta.get('conversation_id'))
            if conversation:location_id=conversation.location_id
        if row.action_type=='dialogue_plan_confirmation':
            label='确认一次共同活动安排' if req.get('operation')=='confirm' else '调整或关闭邀约安排'
        if row.action_type=='phone_comment':label='在手机动态中发表评论'
        place=spec.locations.get(location_id)
        if row.action_type=='move' and place:label='前往'+place.name.get('zh-CN','岛上地点')
        source={'day':row.world_day,'minute':row.world_time_minutes,'description':label,
                'location':place.name.get('zh-CN','') if place else '', 'actor':'participant',
                'category':context,'object_id':oid,'episode':episode,'action_type':row.action_type}
        if row.action_type in ('move','atomic_action','defined_action','dialogue_plan_confirmation','activity_experience') or text:
            sources['e'+str(row.id)]=source
        if not text or len(text)>1000 or re.search(r'[“”"「」]|假如|假设|比如|他说|她说|他们说|不是|并不|不要|系统提示',text):
            continue
        for facet,pattern in PATTERNS.items():
            directions=[d for d,p in ((1,pattern),(-1,COUNTER_PATTERNS.get(facet,r'(?!)'))) if re.search(r'(?:^|[，。！？；\n])\s*'+p,text)]
            if not directions:continue
            direction=directions[0] if len(directions)==1 else 0
            dedup=(facet,episode)
            if dedup in seen:continue
            seen.add(dedup)
            event_id='e'+str(row.id)+'_'+facet
            sources[event_id]={**source,'description':OBSERVATIONS[facet][0 if direction>=0 else 1] or '自述存在相反线索'}
            coded.append({'event_id':event_id,'episode_id':episode,'facet_id':facet,'channel':'language',
                          'day':row.world_day,'context':context,'direction':direction,'eligible':True,
                          'source_verified':True,'explicit_self_report':True})
    # Describe structured actions without assigning trait scores.
    return FeatureExtractionResult(features={'coded_events':coded,'sources':sources,'guided_action_boundary':guided_until},
        opportunity_denominators={'actual_eligible_views':len(opportunity_ids)},
        missing_reasons={'behavior_mapping':'descriptive_only_no_unvalidated_trait_mapping'},
        sufficient=bool(sources),observation_count=len(observations),feature_schema_version=feature_schema,
        extractor_version=OBSERVATION_METHOD if feature_schema==OBSERVATION_SCHEMA else METHOD)


def packet(events,channel='combined'):
    # Reuse the strict closed-code validator; the public packet is experimental.
    draft.build_request(events,channel=channel,synthetic=True)
    grouped=defaultdict(list)
    for e in events:
        if set(e)!=draft.FIELDS or e['facet_id'] not in draft.FACETS or e['channel'] not in ('language','behavior'):
            raise ValueError('invalid_coded_source')
        if e['eligible'] and e['source_verified'] and (channel=='combined' or e['channel']==channel):
            grouped[(e['facet_id'],e['episode_id'],e['channel'])].append(e)
    coded=[]
    for rows in grouped.values():
        first=dict(rows[0]);first['direction']=first['direction'] if len({e['direction'] for e in rows})==1 else 0
        coded.append(first)
    eligibility={}
    for facet in draft.FACETS:
        es=[e for e in coded if e['facet_id']==facet]
        enough=len({e['episode_id'] for e in es})>=3 and len({e['day'] for e in es})>=2 and len({e['context'] for e in es})>=2
        if facet in draft.DOMAINS['negative_emotionality']:
            enough=enough and len({e['episode_id'] for e in es if e['explicit_self_report'] and e['channel']=='language'})>=3
        eligibility[facet]='eligible' if enough else 'insufficient'
    return {'schema_version':draft.VERSION,'method_version':METHOD,'synthetic_only':False,
            'channel':channel,'facet_eligibility':eligibility,'coded_events':coded}


def package(boundary):
    versions={'world_version':boundary.world_version,'scenario_pack_version':boundary.scenario_pack_version,
              'content_pack_version':boundary.world_version+'-content','event_pack_version':boundary.world_version+'-events',
              'system_contract_version':'study-runtime-m6'}
    material={'method':METHOD,'versions':versions,'patterns':PATTERNS,'counter_patterns':COUNTER_PATTERNS,'sufficiency':'3 episodes,2 contexts,2 days;explicit negative-emotion self-report',
              'feature_schema':SCHEMA,'model':'qwen3.8-max','status':'experimental_not_approved',
              'observation_codes':OBSERVATIONS,'language_clause_policy':'first_person_clause_boundary_v1','thinking':'off'}
    manifest=replace(FIXTURE_PACKAGE.manifest,package_id='holiday-coded-v5',package_version='5.1.0-experimental',
        status=AssessmentPackageStatus.DRAFT,compatible_versions=versions,feature_schema_version=SCHEMA,
        extractor_version=METHOD,evidence_mapping_version=METHOD,sufficiency_policy_version='3-2-2-v5',
        prompt_version=METHOD,model_id='qwen3.8-max',report_template_version='evidence-report-v5',
        irb_status='local_method_validation_not_approved',integrity_sha256=hashlib.sha256(canonical_json(material).encode()).hexdigest())
    if boundary.feature_schema_version==OBSERVATION_SCHEMA:
        material.update(method=OBSERVATION_METHOD,feature_schema=OBSERVATION_SCHEMA,
                        scoring_policy='all_scores_null',model='deterministic_observations')
        manifest=replace(manifest,package_id=OBSERVATION_METHOD,package_version='1.0.0-local',
            feature_schema_version=OBSERVATION_SCHEMA,extractor_version=OBSERVATION_METHOD,
            evidence_mapping_version=OBSERVATION_METHOD,sufficiency_policy_version='no_trait_scoring',
            prompt_version=OBSERVATION_METHOD,model_id='deterministic_observations',
            integrity_sha256=hashlib.sha256(canonical_json(material).encode()).hexdigest())
    return replace(FIXTURE_PACKAGE,manifest=manifest,fixture_only=False)


class Provider:
    def __init__(self,transport=None):
        self.transport=transport
        self.metrics={}

    def assess(self,evidence):
        from agents.llm_transport import ChatTransport
        from config import settings
        p=packet(evidence['language_features']['coded_events'])
        sources=evidence['behavior_choice_summary']['sources']
        observation_only=evidence['behavior_choice_summary'].get('observation_only') is True
        run_model=self.transport is not None or settings.agent_mode in ('llm','auto') and settings.has_llm_config
        if not observation_only and any(v=='eligible' for v in p['facet_eligibility'].values()) and run_model:
            if self.transport is None and (settings.llm_provider not in ('qwen','dashscope') or settings.llm_model!='qwen3.8-max'):
                raise ValueError('experimental_assessment_provider_mismatch')
            config=replace(settings,llm_max_output_tokens=4096,llm_total_deadline_seconds=60,llm_timeout_seconds=60,llm_transport_retries=0,llm_thinking='off',llm_reasoning_effort='')
            transport=self.transport or ChatTransport(config)
            raw=asyncio.run(transport.generate([{'role':'system','content':draft.SYSTEM_PROMPT.replace('SYNTHETIC','EXPERIMENTAL').replace('synthetic','experimental')},
                                               {'role':'user','content':json.dumps(p,ensure_ascii=False)}],schema=draft.response_schema(),max_output_tokens=4096,retry=False))
            self.metrics=getattr(transport,'last_metrics',{})
            assessed=draft.validate_result(raw,p)
        else:
            assessed={'facets':{f:{'facet_id':f,'status':'insufficient','score':None,'basis_event_ids':[], 'counter_event_ids':[],'alternative_codes':['limited_coverage']} for f in draft.FACETS},
                      'domains':{d:{'status':'insufficient','score':None} for d in draft.DOMAINS}}
        domains=[]
        for domain,facets in draft.DOMAINS.items():
            refs=list(dict.fromkeys(e['event_id'] for e in p['coded_events'] if e['facet_id'] in facets))[:6]
            descriptions=[f"10月{sources[r]['day']}日 {sources[r]['minute']//60:02d}:{sources[r]['minute']%60:02d} · {sources[r]['description']}" for r in refs]
            status=assessed['domains'][domain]
            description='；'.join(descriptions) if descriptions else '本次假期没有足够的明确线索覆盖这一维度。'
            if status['score'] is None:description+=(' 本轮仅保留观察，不评人格分数；这些线索不等于稳定特质。' if observation_only else ' 尚不足以给出完整维度数值；没有相关记录不表示低分。')
            domains.append({'domain_id':domain,'status':'observed_range' if status['score'] is not None else 'not_estimated',
                            'value':status['score'],'description':description[:240],'basis':refs})
        journeys=[]
        for ref,source in sources.items():
            if '_' in ref:continue
            journeys.append(f"10月{source['day']}日 {source['minute']//60:02d}:{source['minute']%60:02d} · {source['location']} {source['description']}")
        summary='本次旅程留下了'+str(len(journeys))+'条可核对的行动或交流记录。\n'+'\n'.join(journeys[-6:])
        estimated=bool(sources) if observation_only else any(d['value'] is not None for d in domains)
        return {'schema_version':'game-estimate-result-v1','result_kind':'observational_estimate' if estimated else 'data_insufficient',
                'fixture_only':False,'watermark':'本地试玩观察报告 · 不评人格分数' if observation_only else '实验性岛屿观察报告 · 方法尚未校准', 'domains':domains,
                'data_sufficiency':'sufficient' if estimated else 'insufficient',
                'uncertainty_note':'本轮只核对实际行动和交流线索，十五分面及五个维度均不打分。评估方法仍需更多真实案例验证；没有记录不表示低分。' if observation_only else '数值仅在三个分面均有充分证据时展示；其余维度保留实际观察及不足说明。',
                'limitations':['本方法为本地实验版本，尚未完成正式方法审阅与校准。','行为当前用于旅程证据，未用未经验证的点击计数推断人格。','不与 BFI-2 等值；引导、缺席和资料缺失不作为低分。'],
                'gentle_summary':summary[:500],'method_version':OBSERVATION_METHOD if observation_only else METHOD,'facets':list(assessed['facets'].values()),'provider_metrics':self.metrics}


def render(result):
    if 'observation_sections' in result:
        lines=[result['gentle_summary']]
        for section in result['observation_sections']:
            lines.append(f"10月{section['day']}日 {section['minute']//60:02d}:{section['minute']%60:02d} · {section['location']}：{section['description']}（来源：{', '.join(section['basis'])}）。{section['note']}")
        if not result['coverage']['language_clues']:lines.append('本次自然对话未命中明确表达规则；这可能是表达方式或语境造成的，不能据此判断你缺少某种特质。')
        lines.append(result['uncertainty_note'])
        return '\n\n'.join(lines)
    return result['gentle_summary']+'\n\n'+'\n\n'.join(LABELS[d['domain_id']]+'：'+d['description'] for d in result['domains'])+'\n\n'+result['uncertainty_note']
