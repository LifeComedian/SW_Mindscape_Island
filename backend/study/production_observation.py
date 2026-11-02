"""Descriptive observation reports without numerical trait scores."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from study.holiday_assessment_v5 import package as local_package, Provider as LocalProvider, OBSERVATION_SCHEMA, render
from study.protocol_v2 import canonical
from study.service import StudyWorkflowError

PACKAGE_ID='production-observation-v1'
METHOD='production-observation-20261022-v2'

def package(boundary, *, verify_pin=True):
    if boundary.world_version!='chaoxi-holiday-v6' or boundary.feature_schema_version!=OBSERVATION_SCHEMA:
        raise StudyWorkflowError('Observation package requires the V6 frozen observation schema.',409,'observation_package_incompatible')
    base=local_package(boundary)
    sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
             ('holiday_assessment_v5.py','draft_assessment.py','production_observation.py','assessment_service.py','world_bridge_service.py')}
    material={'method':METHOD,'sources':sources,'base_integrity':base.manifest.integrity_sha256,'versions':dict(base.manifest.compatible_versions),'policy':'all_trait_scores_null; local_closed_evidence; no_assessment_model'}
    hashed=hashlib.sha256(canonical(material).encode()).hexdigest()
    configured=os.getenv('STUDY_ASSESSMENT_PACKAGE_SHA256','').strip()
    if verify_pin and configured and configured!=hashed:
        raise StudyWorkflowError('Observation package hash mismatch.',409,'assessment_package_hash_mismatch')
    if verify_pin and os.getenv('STUDY_RUNTIME_ENV')=='production' and not configured:
        raise StudyWorkflowError('Pin the observation package hash before production use.',409,'assessment_package_hash_required')
    return replace(base,manifest=replace(base.manifest,package_id=PACKAGE_ID,package_version='1.0.0',
        model_id='none-deterministic',prompt_version='none',report_template_version=METHOD,
        irb_status='implementation_only_protocol_approval_separate',integrity_sha256=hashed))

class Provider:
    def assess(self,evidence):
        if evidence['behavior_choice_summary'].get('observation_only') is not True:
            raise ValueError('observation_only_required')
        result=LocalProvider().assess(evidence)
        result.update(method_version=METHOD,watermark='岛屿旅程观察 · 不提供人格分数',
            limitations=['这是本次情境的观察记录，不能据此判断稳定人格。','语言按有限的明确表达规则整理，可能遗漏语境或含蓄表达。',
                         '行为只作为经历与情境依据；没有记录、拒绝或跳过都不表示低分。','这份观察报告与BFI-2问卷分数不是等值测量。'])
        events=evidence['language_features']['coded_events'];sources=evidence['behavior_choice_summary']['sources']
        refs=[]
        for facet in result['facets']:
            facet['basis_event_ids']=[e['event_id'] for e in events if e['facet_id']==facet['facet_id']][:3]
            refs.extend(facet['basis_event_ids'])
        # Group repeated operations before sampling activities.
        groups={}
        for ref,source in sources.items():
            if '_' in ref: continue
            key=(source['day'],source.get('category','exploration'),source.get('object_id',''),source['description'])
            groups.setdefault(key,[]).append(ref)
        selected=[]
        # Sample across days and activity categories.
        categories=sorted({(k[0],k[1]) for k in groups})
        buckets={c:[v for k,v in groups.items() if (k[0],k[1])==c] for c in categories}
        while len(selected)<12 and any(buckets.values()):
            for category in categories:
                if buckets[category] and len(selected)<12:selected.append(buckets[category].pop(0))
        sections=[]
        for group in selected:
            ref=group[0];source=sources[ref];refs.append(ref)
            sections.append({'description':source['description'],'day':source['day'],'minute':source['minute'],
                'location':source['location'],'basis':[ref],
                'note':'同类操作合并呈现，不将操作次数解释为人格强弱。' if len(group)>1 else '仅描述这一次情境。'})
        for event in events[:6]:
            ref=event['event_id'];source=sources[ref];refs.append(ref)
            sections.append({'description':source['description'],'day':source['day'],'minute':source['minute'],
                'location':source['location'],'basis':[ref],'note':'这是当时的明确表达，不代表稳定人格。'})
        result['observation_sections']=sections
        result['coverage']={'record_count':sum('_' not in r for r in sources),'episode_groups':len(groups),
            'days':sorted({s['day'] for s in sources.values()}),'language_clues':len(events),
            'trait_scoring':'not_performed','observation_available':bool(sources)}
        result['gentle_summary']=(f"本次旅程有{len(groups)}组可核对的经历，涉及{len(result['coverage']['days'])}个游戏日。以下按不同情境列出观察，并附上来源。" if groups else '本次没有可供整理的有效经历记录。')
        result['evidence']=[{'source_id':ref,**sources[ref]} for ref in dict.fromkeys(refs)]
        return result

if __name__=='__main__':
    from types import SimpleNamespace
    from world.registry import get_world_spec
    world=get_world_spec('chaoxi-holiday-v6')
    bound=SimpleNamespace(world_version=world.world_version,scenario_pack_version=world.scenario_pack_version,feature_schema_version=OBSERVATION_SCHEMA)
    print(package(bound,verify_pin=False).manifest.integrity_sha256)
