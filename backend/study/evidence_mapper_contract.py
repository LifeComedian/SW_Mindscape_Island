"""Offline model-assisted evidence joins with server-side validation."""
from collections import Counter
from copy import deepcopy
from . import evidence_contract as base

VERSION = 'evidence-mapper-v0.4.1'
PROMPT = '''Return only JSON with keys version (copy input), facets (all 15 facet IDs).
You map closed evidence codes to approved rules; never evaluate personality.
Each facet has ONLY facet_id and findings. Each finding has ONLY rule_id and
evidence_ids, in rule.needs order. Include every matching rule/evidence combination
exactly once for its allowed facets. No matching evidence means findings: [].
For a single rule, select each event containing the required code.
For same_episode_in_order, select two DIFFERENT events containing the required
codes in needs order, with identical episode_id and non-null strictly increasing order.
Never join different episodes, reversed time, or unrelated codes. Do not invent references.
Do NOT output status, score, confidence, limitations, personality conclusions or prose.
Those fields belong to the server. Greetings and unmapped_language have no matching rule.
Array order is unimportant except evidence_ids inside a finding.
'''


def compact_packet(packet):
    base.validate_packet(packet)
    return dict(version=VERSION, facet_ids=base.FACET_IDS, events=deepcopy(packet['events']),
        rules={k: {a: deepcopy(v) for a, v in r.items() if a in ('facets', 'needs', 'relation')}
               for k, r in base.RULES.items()})


def expand_packet(packet):
    if not isinstance(packet, dict) or set(packet) != {'version', 'facet_ids', 'rules', 'events'} or packet['version'] != VERSION:
        raise ValueError('mapper_packet_contract')
    rules = {k: {a: v for a, v in r.items() if a in ('facets', 'needs', 'relation')} for k, r in base.RULES.items()}
    if packet['rules'] != rules:
        raise ValueError('mapper_rules_changed')
    expanded = dict(version=base.VERSION, facet_ids=packet['facet_ids'], events=packet['events'],
        rules={k: {a: v for a, v in r.items() if a != 'text'} for k, r in base.RULES.items()})
    base.validate_packet(expanded)
    return expanded


def expected_mapping(packet):
    report = base.expected_result(expand_packet(packet))
    return dict(version=VERSION, facets=[dict(facet_id=f['facet_id'], findings=f['findings']) for f in report['facets']])


def validate_mapping(value, packet):
    expected = expected_mapping(packet)
    if not isinstance(value, dict) or set(value) != {'version', 'facets'} or value.get('version') != VERSION:
        return ['output_shape_or_version']
    fs = value['facets']
    if not isinstance(fs, list) or len(fs) != 15 or any(not isinstance(f, dict) for f in fs):
        return ['facet_shape']
    if any(not isinstance(f.get('facet_id'), str) for f in fs) or Counter(f['facet_id'] for f in fs) != Counter(base.FACET_IDS):
        return ['facet_inventory']
    by_id = {f['facet_id']: f for f in fs}
    errors = []
    for exp in expected['facets']:
        got = by_id[exp['facet_id']]
        prefix = exp['facet_id'] + ':'
        if set(got) != {'facet_id', 'findings'}:
            errors.append(prefix + 'server_owned_or_unapproved_fields')
        if not isinstance(got.get('findings'), list) or Counter(base.canonical(x) for x in got['findings']) != Counter(base.canonical(x) for x in exp['findings']):
            errors.append(prefix + 'unsupported_missing_or_duplicate_finding')
    return errors


def finalize_mapping(value, packet):
    errors = validate_mapping(value, packet)
    if errors:
        raise ValueError('model_mapping_rejected:' + ','.join(errors))
    report = base.expected_result(expand_packet(packet))
    # Model findings are retained after validation. Only derived fields are added.
    findings = {f['facet_id']: deepcopy(f['findings']) for f in value['facets']}
    for f in report['facets']:
        f['findings'] = findings[f['facet_id']]
    report['version'] = VERSION
    return report


def input_schema():
    schema = base.input_schema()
    schema['properties']['version'] = {'const': VERSION}
    schema['properties']['rules'] = {'const': compact_packet(dict(version=base.VERSION, facet_ids=base.FACET_IDS,
        rules={k: {a: v for a, v in r.items() if a != 'text'} for k, r in base.RULES.items()}, events=[]))['rules']}
    return schema


def output_schema():
    schema = base.output_schema()
    schema['properties']['version'] = {'const': VERSION}
    facet = schema['properties']['facets']['items']
    facet['required'] = ['facet_id', 'findings']
    facet['properties'] = {k: v for k, v in facet['properties'].items() if k in ('facet_id', 'findings')}
    return schema
