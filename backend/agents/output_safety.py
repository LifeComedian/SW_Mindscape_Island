"""Check model output and return fixed notices on rejection."""
import json
import re
from fastapi import HTTPException

TECHNICAL_NOTICE = '系统提示：回复暂时不可用。你可以稍后重试、换个话题或结束对话。'
SAFETY_NOTICE = '系统提示：这条回复已被安全检查拦截，本次交流已停止。你可以离开对话、休息或退出研究，无需说明原因。'
RULES = {
    'identifiers': r'(?:告诉我|提供|发送|报出|给我|填写).{0,18}(?:身份证|真实姓名|手机号码|电话号码|家庭住址|银行卡|学号|邮箱)|(?:send|give|tell|provide).{0,35}(?:real name|phone number|home address|student id|email address)',
    'clinical_claim': r'(?:你|您).{0,10}(?:患有|得了|确诊|诊断为).{0,12}(?:症|障碍|疾病)|(?:我给你|我能|我可以).{0,8}(?:诊断|治疗|开药)|(?:你应该|你必须|建议你).{0,12}(?:服药|停药|吃药|加药|服用)|you (?:definitely )?(?:have|suffer from).{0,15}(?:depression|disorder)|(?:i diagnose|i can treat|i prescribe)|(?:take|increase|stop).{0,20}(?:medication|dosage|antidepressant)',
    'threat_or_pressure': r'(?:不许|不能|不得)(?:退出|拒绝|不回答)|(?:你必须|你一定要).{0,12}(?:回答|参加|参与|继续研究)|(?:不回答|不参加|退出).{0,15}(?:扣钱|不给报酬|惩罚|后果自负)|(?:杀了你|伤害你|威胁你)|you (?:must|have to).{0,15}(?:answer|participate)|(?:cannot|must not) (?:withdraw|refuse)|(?:hurt|kill) you',
    'impersonation': r'我是.{0,8}(?:真人|研究人员|研究员|研究助理|实验人员|心理医生|治疗师)|i am (?:a |the )?(?:real person|researcher|research assistant|therapist|clinician)',
}

class ModelStop(HTTPException):
    def __init__(self, reason='technical_failure', *, safety=False):
        self.reason = reason
        self.safety = safety
        super().__init__(422 if safety else 503, SAFETY_NOTICE if safety else TECHNICAL_NOTICE)

def check_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ModelStop('empty_response')
    for reason, pattern in RULES.items():
        if re.search(pattern, text, re.I):
            raise ModelStop(reason, safety=True)
    return text

def check_payload(value):
    if isinstance(value, str):
        check_text(value) if value.strip() else None
    elif isinstance(value, dict):
        for child in value.values(): check_payload(child)
    elif isinstance(value, list):
        for child in value: check_payload(child)

async def guarded_generate(transport, *args, **kwargs):
    # Apply the same instructions to injected providers.
    from agents.chinese_style import style_messages
    if args:
        args = (style_messages(args[0]), *args[1:])
    elif 'messages' in kwargs:
        kwargs['messages'] = style_messages(kwargs['messages'])
    # Participant exchanges are never automatically retried.
    kwargs['retry'] = False
    try:
        raw = await transport.generate(*args, **kwargs)
        check_text(raw)
        if kwargs.get('schema'):
            value = json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
            if not isinstance(value, dict): raise ValueError('object_required')
            check_payload(value)
        return raw
    except ModelStop:
        raise
    except Exception as exc:
        # Log only allowed reason codes; exceptions may contain secrets.
        from agents.llm_transport import TransportError
        known = {'provider_queue_full', 'total_deadline', 'network_or_tls_failure',
                 'authentication_or_region', 'endpoint_model_or_parameters',
                 'rate_or_quota_limit', 'provider_http_failure', 'response_size_limit',
                 'invalid_provider_response', 'truncated_provider_response',
                 'unexpected_finish_reason', 'empty_provider_response', 'output_size_limit',
                 'provider_not_configured', 'input_or_output_limit'}
        if isinstance(exc, TransportError) and str(exc) in known:
            raise ModelStop(str(exc)) from None
        if isinstance(exc, json.JSONDecodeError):
            raise ModelStop('invalid_response_json') from None
        raise ModelStop() from None

def preserve_stop(exc):
    if isinstance(exc, ModelStop): raise exc


def record_stop(db, sid, request_key, exc, channel, agent_id=None):
    """Record only a reason code; never persist the rejected model prose."""
    if not isinstance(exc, ModelStop):return
    import hashlib
    from datetime import datetime
    from models import WorldState, WorldAction, WorldConversation
    from services.world_service import session_write_lock
    with session_write_lock(sid):
        db.rollback()
        world=db.query(WorldState).filter_by(session_id=sid).first()
        if not world:return
        key='model-stop:'+hashlib.sha256((channel+str(request_key)).encode()).hexdigest()
        if not db.query(WorldAction.id).filter_by(session_id=sid,idempotency_key=key).first():
            db.add(WorldAction(session_id=sid,idempotency_key=key,actor_type='system',action_type='model_exchange_stopped',
                target_agent_id=agent_id,world_day=world.current_day,world_time_minutes=world.current_time_minutes,
                metadata_json=json.dumps({'reason':exc.reason,'safety_blocked':exc.safety,'channel':channel,'policy':'irb-3.1-20261022'})))
        if exc.safety and channel=='in_person':
            for conversation in db.query(WorldConversation).filter_by(session_id=sid,agent_id=agent_id,status='active',conversation_kind='participant_resident'):
                conversation.status='ended';conversation.ended_reason_code='model_safety_stop';conversation.updated_at=datetime.utcnow()
                for member in conversation.participants:
                    member.left_at=conversation.updated_at;member.leave_reason_code='model_safety_stop'
        db.commit()
