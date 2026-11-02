"""Offline report release checks with separate editorial review."""
from .sentence_report_v064 import check_writer,gate,digest,flatten,check_review

def assess_candidate(report,packet,model_envelope,editorial_envelope=None):
    structural=check_writer(report,packet)
    if structural['errors']:return {'eligible':False,'errors':structural['errors']}
    errors=list(gate(report,packet,model_envelope)['errors'])
    cited={eid for s in flatten(report) for eid in s['evidence_ids']}
    available={code for e in packet['episodes'] if e['id']in cited for code in e['allowed_codes']}
    for code in packet.get('required_themes',[]):
        if code not in available:errors.append('missing_theme_evidence:'+code)
    # Source availability is a necessary condition, not proof a theme is explained.
    if not isinstance(editorial_envelope,dict) or editorial_envelope.get('report_sha256')!=digest(report) or editorial_envelope.get('packet_sha256')!=digest(packet):
        errors.append('editorial_review_missing_or_stale')
    else:
        if not editorial_envelope.get('reviewer'):errors.append('editorial_reviewer_missing')
        reviewed=check_review(editorial_envelope.get('output'),report,packet)
        errors.extend('editorial:'+e for e in reviewed['errors'])
        if editorial_envelope.get('complete') is not True:errors.append('editorial_incomplete')
        if editorial_envelope.get('style_accepted') is not True:errors.append('editorial_style_hold')
    return {'eligible':not errors,'errors':errors,'production_switched':False}
