"""Escaped HTML rendering for observation reports."""
import html
from study.controlled_report import validate_report
def esc(v):return html.escape(str(v))

def fact_description(c):
    if c['kind']=='expression':
        channels={'post':'动态原文','comment':'评论原文','dialogue':'对话原文','activity_chat':'活动对话原文',
                  'private_message':'私信原文','private_note':'私人留言原文','public_note':'公开留言原文'}
        return channels.get(c['channel'],'玩家原话')+'：'+c['quote']
    if c['kind']=='everyday_action':return '你'+c['description']+'。'
    if c['kind']=='work':return f'你完成了{c["label"]}。'
    if c['kind']=='feedback':return '你向对方提出想听听建议：'+c['quote']
    if c['kind']=='gratitude':return ('私人留言：'if c['public']is False else'公开留言：')+c['quote']
    if c['kind']=='joint':return ('你发起了'if c['organized']else'你参与的')+c['label']+'；'+('有实际参与记录。'if c['participated']else'尚无实际参与记录。')
    return '这次经历中的一个片段。'

def report_html(report,facts):
    if validate_report(report,facts):raise ValueError('report_view_validation_failed')
    byid={c['id']:c for c in facts['cards']};blocks=[]
    for p in report['paragraphs']:
        ids=list(dict.fromkeys(x for s in p['sentences']for x in s['fact_ids']))
        basis=''.join('<p>'+esc(fact_description(byid[i]))+'</p>'for i in ids)
        blocks.append('<section><p class="prose">'+esc(p['text'])+'</p>'+('<details><summary>这段观察来自哪里</summary>'+basis+'</details>'if ids else'')+'</section>')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>这次岛屿生活里的你</title><style>
*{box-sizing:border-box}body{margin:0;background:#eeeae1;color:#293d34;font:18px/2 "Microsoft YaHei",sans-serif}main{max-width:900px;margin:48px auto;padding:48px 60px;background:#fffdf7;border-radius:18px;box-shadow:0 10px 45px #334b3820}.eyebrow{font-size:14px;letter-spacing:.13em;color:#6a7b6b}h1{font-size:32px;margin:10px 0 32px;line-height:1.5}section+section{margin-top:26px}.prose{margin:0}details{font-size:14px;color:#667367;margin-top:12px;padding-left:14px;border-left:2px solid #d7e1d5}summary{cursor:pointer}details p{margin:8px 0}.scope{margin-top:36px;padding-top:20px;border-top:1px solid #dde3d6;color:#798176;font-size:14px}@media(max-width:650px){main{margin:14px;padding:26px 22px}h1{font-size:25px}body{font-size:17px}}
</style></head><body><main><div class="eyebrow">岛屿回信</div><h1>'''+esc(report['title'])+'</h1>'+''.join(blocks)+'<p class="scope">'+esc(report['scope_note'])+'</p></main></body></html>'
