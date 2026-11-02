"""Offline narrative revision with verified count metadata."""
from copy import deepcopy
from . import sentence_report_v062 as base
from .sentence_report_v063 import WRITER_PROMPT,REVIEWER_PROMPT
from .sentence_report_v062 import review_schema,digest,review_input,render,flatten,check_review

VERSION='sentence-grounded-reflection-v0.6.4'
WRITER_PROMPT+='''\n末段回应感谢本身即可，不写“我也谢谢你”或虚构报告作者与玩家共同相处。范围限定的解释要具体，避免两次都求意见的歧义。私人留言不能写当众说出。不要按第几天排列。只输出规定的JSON字段，不添加计数。'''
REVIEWER_PROMPT+='''\n“动手尝试”在这个游戏指玩家实际操作创作界面；插花的手动布置、自由木作的移动旋转均是直接依据，不要求现实里做实物。多来源一句话可以各自支持不同命题，不要求每个来源都支持每个命题；例如E03支持木作探索，E01支持插花后征求意见，只要句子没有说两次都求意见，就不应据此拒判。'''

TASK_REMINDER='''请现在写正文，输出JSON。全部资料在source_packet中，它与上次使用的数据完全相同。
不要复述游玩顺序。用三段连贯短文，第一段把本次动手探索和插花后愿意听看法自然连在一起，第二段讲两次主动约人玩牌所表现的情境主动性，第三段简短回应私人感谢。至少两句是有依据的理解，不只是行为罗列。
不列日期、花材、所有小游戏，不写“你是一个XX的人”。一段约两三句，每句分别给来源。只写paragraphs → sentences → text、evidence_ids四个键，不写sentences_count或任何额外键。
注意：插花后求建议有证据，木作后求建议无证据；可以一起谈自己尝试和愿意听意见，但不得写两次都向他人求评。最后直接回应私人感谢，不替自己感谢玩家。
'''

def schema():
    s=deepcopy(base.schema())
    s['properties']['paragraphs']['minItems']=1
    s['properties']['sentences_count']={'type':'integer','minimum':1}
    s['properties']['paragraphs']['items']['properties']['sentences_count']={'type':'integer','minimum':1}
    return s

def check_writer(report,packet):
    if not isinstance(report,dict):return base.check_writer(report,packet)
    clean=deepcopy(report);errors=[]
    total=clean.pop('sentences_count',None)
    if 'sentences_count'in report and type(total) is not int:errors.append('sentence_count_metadata')
    if isinstance(clean.get('paragraphs'),list):
        actual=0
        for i,p in enumerate(clean['paragraphs'],1):
            if not isinstance(p,dict):continue
            sentences=p.get('sentences');count=p.pop('sentences_count',None)
            if isinstance(sentences,list):
                actual+=len(sentences)
                if 'sentences_count'in report['paragraphs'][i-1] and (type(count)is not int or count!=len(sentences)):errors.append(f'P{i}:sentence_count_metadata')
        if total is not None and total!=actual:errors.append('sentence_count_metadata')
    result=base.check_writer(clean,packet)
    result['errors']=errors+result['errors']
    if not result['errors']:result['body_sha256']=digest(report)
    return result

def gate(report,packet,envelope):
    structural=check_writer(report,packet)
    if structural['errors']:return {'accepted':False,'errors':structural['errors']}
    if not isinstance(envelope,dict) or envelope.get('report_sha256')!=digest(report):return {'accepted':False,'errors':['review_missing_or_stale']}
    return check_review(envelope.get('output'),report,packet)
