"""Versioned consent materials and experience-study workflow."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

VERSION = 'experience-workflow-20261021-v1'
LEGACY_CONSENT_VERSION = 'experience-consent-20261021-v1'
CONSENT_VERSION = 'experience-consent-20261023-v2'
LEGACY_DEBRIEF_VERSION = 'appendix-a7-debrief-20261018-v2'
DEBRIEF_VERSION = 'appendix-a7-debrief-20261023-v3'

REPORT_DATA_FLOW = (
    '岛屿观察报告会先在研究服务器上根据游戏记录整理候选段落。'
    '系统可能另向Qwen发送这些段落，请它选择适合展示的段落及顺序；'
    '段落中可能包含您做过的活动、制作的虚拟物品、与AI居民的互动，以及您在游戏中输入的部分原话。'
    '这项请求不发送完整游戏日志、研究编号、报名邮箱、支付信息、问卷答案或研究反馈。'
    '游戏中的原话仍可能含有您主动透露的个人信息，筛查不能保证消除全部识别风险。'
    '模型只返回候选段落的编号，不能另写评价；系统核对编号、段落与记录的对应关系后生成回信。'
    '如果请求失败、超时或选择不符合要求，系统使用本地预先核对的备用回信。'
    '回信不提供人格数值分数，只描述本次有记录支持的经历和情境中的表现。'
)
REPORT_DATA_FLOW_BRIEF = (
    '岛屿回信根据游戏记录整理。系统可能把含有活动片段及部分游戏原话的候选段落发给Qwen，'
    '由它选择段落编号，再由研究服务器核对并生成回信；模型失败或选择无效时使用本地备用回信。'
    '这项请求不发送完整游戏日志、研究编号、报名邮箱、支付信息、问卷答案或研究反馈。'
    '原话仍可能包含您主动透露的信息。回信只供回看本次经历，不代表稳定人格，也不提供人格分数。'
)

def enabled(session):
    return session.workflow_version == VERSION

def configured_workflow():
    value = os.getenv('STUDY_PROTOCOL_VERSION', 'study-workflow-v1')
    if value not in ('study-workflow-v1', VERSION):
        raise ValueError('Unknown STUDY_PROTOCOL_VERSION')
    return value

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def _legacy_materials():
    # Preserve the source document. This separately versioned implementation
    # copy describes the experience-only configuration chosen on 21 October.
    value = json.loads(Path(__file__).with_name('protocol_20261018.json').read_text(encoding='utf8'))
    replacements={
      '并探索资料充分时实验性岛屿估计与问卷得分的关系':'重点收集体验、报告反馈与流程可行性信息，不以人格分数的一致性作为本次分析目标',
      '并探索资料充分时两类结果之间的关系':'重点收集体验、报告反馈与流程可行性信息',
      '另一项评估请求只包含研究编号和本地提取的预定义语言编码特征，不包含原始对话、联系信息、问卷或反馈。':'本次体验版的岛屿观察报告在服务器上按固定规则生成，不向模型发送独立评估请求，不输出人格数值分数。',
      '岛屿结果是尚未完成效度验证和校准的实验性研究估计，可能不准确或不完整，不是诊断。':'岛屿结果是本次旅程的观察摘要，不是经过效度验证和校准的人格测量，可能遗漏或误解情境，不是诊断。',
      '岛屿结果是实验性研究估计，尚未完成测量效度验证或校准。':'岛屿结果是本次旅程的观察摘要，不提供人格数值分数，尚未完成测量效度验证或校准。',
      '问卷、反馈及联系信息不进入AI对话或人格估计请求。':'问卷、反馈及联系信息不进入AI居民对话；岛屿观察报告不发送独立模型请求。',
    }
    def revised(text):
        for old,new in replacements.items():text=text.replace(old,new)
        return text
    for section in value['consent']:section['paragraphs']=[revised(p) for p in section['paragraphs']]
    value['debrief']=[revised(p) for p in value['debrief']]
    return value

def materials(version=CONSENT_VERSION):
    value = _legacy_materials()
    if version == LEGACY_CONSENT_VERSION:
        return value
    if version != CONSENT_VERSION:
        raise ValueError('Unknown participant material version')
    replacements = {
        '版本2.1，2026年10月18日。': '在线说明版本2026年10月23日。',
        '通过已确认的千问AI平台接口调用；研究者报告在中国大陆使用。':
            '通过本研究配置的模型服务接口调用；服务商及实际处理区域将在正式参加前核实并告知。',
        '本次体验版的岛屿观察报告在服务器上按固定规则生成，不向模型发送独立评估请求，不输出人格数值分数。': REPORT_DATA_FLOW,
        '问卷、反馈及联系信息不进入AI居民对话；岛屿观察报告不发送独立模型请求。':
            '问卷、研究反馈及报名联系信息不进入AI居民对话。' + REPORT_DATA_FLOW_BRIEF,
        '使用平台为千问AI平台，接口为https://maas.qianwenaiapi.com/compatible-mode/v1。根据平台《安全》说明，输入输出不用于模型训练；请求元数据仍会记录。研究拟使用不启用平台持久对话存储的Chat Completions方式。供应商保留／删除限制与准确处理区域将在正式使用前完成核验并补充告知，不把北京ECS位置视为模型所在地证明。官方说明见本申请末尾的平台文档记录。':
            '当前配置的接口为https://maas.qianwenaiapi.com/compatible-mode/v1。请求使用Chat Completions方式。供应商是否保留输入输出、是否用于训练、保存期限、删除方式及实际处理区域仍需核实，正式参加前将明确告知；研究服务器在北京不代表模型也在北京处理数据。',
    }
    def revised(text):
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
    for section in value['consent']:
        section['paragraphs'] = [revised(p) for p in section['paragraphs']]
    value['debrief'] = [revised(p) for p in value['debrief']]
    return value

def consent_payload(version=CONSENT_VERSION):
    m = materials(version)
    return {'version':version, 'source_version':'2.1-2026-10-18', 'document_sha256':digest(m['consent']),
            'sections':m['consent'], 'plain_text':'\n\n'.join(s['title']+'\n'+'\n'.join(s['paragraphs']) for s in m['consent'])}

def evaluation_instrument():
    from study.experience_instruments import post_result_instrument_payload
    p = post_result_instrument_payload()
    p.update(instrument_id='APPENDIX-A5-REPORT-EVALUATION', instrument_version='appendix-a5-report-evaluation-20261018-v2', appendix='A5')
    p.pop('instrument_sha256', None)
    return {**p, 'instrument_sha256':digest(p)}

def comparison_instrument():
    from study.completion_instruments import comparative_instrument_payload
    p = comparative_instrument_payload()
    p.update(instrument_id='APPENDIX-A6-COMPARATIVE-FEEDBACK', instrument_version='appendix-a6-comparative-feedback-20261018-v2', appendix='A6',
             instructions='请回顾并比较刚才的两种方式。所有问题均可跳过；若有报告不可用，结果比较题6–8不适用。')
    p.pop('instrument_sha256', None)
    return {**p, 'instrument_sha256':digest(p)}

def debrief_instrument(version=DEBRIEF_VERSION):
    if version not in (LEGACY_DEBRIEF_VERSION, DEBRIEF_VERSION):
        raise ValueError('Unknown debrief version')
    from study.completion_instruments import debrief_payload
    p = debrief_payload()
    material_version = LEGACY_CONSENT_VERSION if version == LEGACY_DEBRIEF_VERSION else CONSENT_VERSION
    p.update(debrief_version=version, paragraphs=materials(material_version)['debrief'])
    p.pop('debrief_sha256',None)
    return {**p, 'debrief_sha256':digest(p)}

def allows_transition(session, current, requested, source, reason):
    if not enabled(session): return False
    return (current.value, requested.value, source, reason) in {
      ('game_estimate_failed','questionnaire_active','participant','bfi2_questionnaire_started'),
      ('questionnaire_completed','results_ready','system','available_reports_frozen'),
      ('questionnaire_completed','comparative_feedback','system','available_reports_frozen'),
      ('result_one_active','comparative_feedback','participant','available_report_evaluation_frozen'),
      ('result_two_active','comparative_feedback','participant','available_report_evaluation_frozen'),
    }

def progress(db, session):
    from study.models import StudyProtocolProgress
    row=db.get(StudyProtocolProgress,session.id)
    if row is None:
        row=StudyProtocolProgress(study_session_id=session.id,questionnaire_skipped_json='[]')
        db.add(row);db.flush()
    return row
