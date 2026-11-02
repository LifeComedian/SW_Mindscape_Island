"""Assemble the island letter from frozen facts and recap insights."""
import asyncio
from dataclasses import replace
import hashlib
import os
from pathlib import Path

from study.controlled_report import CATALOG_VERSION, generate, validate_report, text_report
from study.controlled_report_view import fact_description
from study.protocol_v2 import canonical
from study.service import StudyWorkflowError

PACKAGE_ID = 'production-island-letter-v2'
FACT_KEY = 'controlled_letter_facts'


def package(boundary, *, verify_pin=True):
    from study.production_observation import package as base_package
    base = base_package(boundary, verify_pin=False)
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ('production_letter.py', 'controlled_report.py', 'controlled_report_service.py',
                            'controlled_report_view.py', 'assessment_service.py', 'world_bridge_service.py', 'results_service.py',
                             'everyday_observations.py', 'controlled_report_v2.py', 'controlled_report_legacy.py', 'island_recap.py', 'recap_insights.py')}
    hashed = hashlib.sha256(canonical({'method':PACKAGE_ID,'catalog':CATALOG_VERSION,
        'base':base.manifest.integrity_sha256,'sources':sources}).encode()).hexdigest()
    pin = os.getenv('STUDY_ASSESSMENT_PACKAGE_SHA256','').strip()
    if verify_pin and pin and pin != hashed:
        raise StudyWorkflowError('Island letter package hash mismatch.',409,'assessment_package_hash_mismatch')
    if verify_pin and os.getenv('STUDY_RUNTIME_ENV') == 'production' and not pin:
        raise StudyWorkflowError('Pin the island letter package before production use.',409,'assessment_package_hash_required')
    return replace(base, manifest=replace(base.manifest, package_id=PACKAGE_ID, package_version='2.0.0',
        model_id='qwen-selector-or-local-fallback', prompt_version=CATALOG_VERSION,
        report_template_version=CATALOG_VERSION, integrity_sha256=hashed))


def payload(report, facts, insights=None):
    if validate_report(report, facts):
        raise ValueError('invalid_controlled_letter')
    cards = {c['id']:c for c in facts['cards']}
    paragraphs = []
    for paragraph in report['paragraphs']:
        refs = list(dict.fromkeys(i for s in paragraph['sentences'] for i in s['fact_ids']))
        paragraphs.append({'text':paragraph['text'],'evidence':[
            {'source_id':i,'description':fact_description(cards[i])} for i in refs]})
    if insights and 'recap' in facts:
        from study.recap_insights import validate
        validate(insights,facts['recap'])
        if insights.get('source_sha256')!=facts['recap']['source_sha256']:raise ValueError('insight_source_changed')
        if insights['paragraphs']:
            from study.island_recap import describe_source
            paragraphs=[{'text':p['text'],'evidence':[{'source_id':r,'description':describe_source(facts['recap'],r)} for r in p['source_refs']]} for p in insights['paragraphs']]
    # A short letter is still readable; do not mislabel absent evidence as sufficient.
    sufficient = any(s['fact_ids'] for p in report['paragraphs'] for s in p['sentences'])
    # Older frozen payloads used card presence, including unaccepted invitations.
    if report.get('version') in ('controlled-island-letter-natural-zh-v2', 'controlled-island-letter-v1'):
        sufficient = bool(facts['cards'])
    return {'schema_version':'game-estimate-result-v1','result_kind':'observational_estimate' if sufficient else 'data_insufficient',
        'fixture_only':False,'watermark':'岛屿回信 · 本次经历的观察', 'domains':[],
        'data_sufficiency':'sufficient' if sufficient else 'insufficient','uncertainty_note':report['scope_note'],
        'limitations':['这份回信只讨论有记录支持的片段，不代表稳定人格，也不提供人格分数。',
                        '没有提到的方面，不表示你缺少某种特点。'],
        'gentle_summary':report['paragraphs'][0]['text'], 'method_version':PACKAGE_ID,
        'island_letter':{'report':report,'paragraphs':paragraphs,**({'recap':facts['recap']} if 'recap' in facts else {}),**({'insights':insights} if insights else {})},
        'coverage':{'player_actions':facts['coverage']['player_actions'],'fact_count':len(facts['cards']),
                    'trait_scoring':'not_performed'}}


class Provider:
    def __init__(self, selector=None, *, use_config=True):
        self.selector=selector
        self.use_config=use_config

    def assess(self, evidence):
        facts=evidence['behavior_choice_summary'][FACT_KEY]
        selector=self.selector
        if selector is None and self.use_config:
            from config import settings
            from study.controlled_report_service import qwen_selector
            if settings.agent_mode == 'llm':
                try: selector,_,_=qwen_selector(settings)
                except (ValueError,TypeError,AttributeError): pass
        result=asyncio.run(generate(facts,selector))
        insights=None
        if 'recap' in facts and self.use_config:
            from config import settings
            if settings.agent_mode=='llm':
                from study.recap_insights import generate as synthesize
                insights=asyncio.run(synthesize(facts['recap'],settings))
        return payload(result['report'],facts,insights)


def verify(result, evidence):
    facts=evidence['behavior_choice_summary'][FACT_KEY]
    if result != payload(result['island_letter']['report'], facts,result['island_letter'].get('insights')):
        raise ValueError('letter_output_does_not_match_frozen_facts')


def render(result):
    if result['island_letter'].get('insights',{}).get('paragraphs'):
        return '\n\n'.join(p['text'] for p in result['island_letter']['paragraphs'])+'\n\n'+result['uncertainty_note']
    return text_report(result['island_letter']['report'])


if __name__ == '__main__':
    from types import SimpleNamespace
    from world.registry import get_world_spec
    world=get_world_spec('chaoxi-holiday-v6')
    bound=SimpleNamespace(world_version=world.world_version,scenario_pack_version=world.scenario_pack_version,
                          feature_schema_version='holiday-observation-features-v1')
    print(package(bound,verify_pin=False).manifest.integrity_sha256)
