"""Generate report previews without replacing frozen results."""
from dataclasses import replace
import json
from sqlalchemy import text
from study.controlled_report import TABLES,SELECTOR_PROMPT,extract_facts,generate

def read_session_records(db,session_id):
    if type(session_id)is not int or session_id<1:raise ValueError('invalid_session')
    return {table:[dict(row)for row in db.execute(text(f'SELECT * FROM {table} WHERE session_id=:sid ORDER BY id'),{'sid':session_id}).mappings()]for table in TABLES}

def qwen_selector(config):
    from agents.llm_transport import ChatTransport
    cfg=replace(config,llm_max_output_tokens=256,llm_max_input_bytes=60000,
                llm_timeout_seconds=25,llm_total_deadline_seconds=30,llm_transport_retries=0,
                llm_thinking='off',llm_reasoning_effort='',llm_structured_mode='json_object')
    if cfg.llm_provider not in ('qwen','dashscope'):raise ValueError('qwen_required')
    transport=ChatTransport(cfg)
    async def select(payload,schema):
        return await transport.generate([{'role':'system','content':SELECTOR_PROMPT},
            {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],schema=schema,retry=False,max_output_tokens=256)
    return select,transport,cfg

async def generate_session_report(db,session_id,config=None):
    """Fresh report preview from a caller-authorized session, never silently persisted.

The caller must enforce study/session ownership. Database faults propagate rather
than being presented as a participant having no data. Model/config faults fall
back to the same factual local renderer.
"""
    facts=extract_facts(read_session_records(db,session_id),session_id)
    selector=None
    if config is not None:
        try:selector,_,_=qwen_selector(config)
        except (ValueError,TypeError,AttributeError):pass
    return {**await generate(facts,selector),'facts':facts}
