"""Offline observation reports from reviewed evidence."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import json

DOMAINS = ('extraversion', 'agreeableness', 'conscientiousness', 'negative_emotionality', 'open_mindedness')
VERSION = 'reviewed-observation-report-v0.3'


def evidence_index(bundles):
    result = {}
    for session, bundle in bundles.items():
        for row in bundle['evidence']:
            ref = f'{session}/{row["source_ref"]}'
            if ref in result:
                raise ValueError('Duplicate evidence identity')
            result[ref] = {**row, 'session': session}
    return result


def episode_chains(bundles):
    """Group only within sessions; exact scene joins come from normalization."""
    chains = []
    for session, bundle in bundles.items():
        groups = defaultdict(list)
        for e in bundle['evidence']:
            if e.get('episode'):
                groups[e['episode']].append(e)
        for episode, rows in groups.items():
            ordered = sorted(rows, key=lambda r: (r.get('created_at') or '', r['source_ref']))
            langs = [r for r in ordered if r['kind'] == 'player_language']
            finals = [r for r in ordered if r.get('final_submission')]
            if not langs and not finals:
                continue
            chains.append({'session': session, 'episode': episode,
                           'language_refs': [f'{session}/{r["source_ref"]}' for r in langs],
                           'final_refs': [f'{session}/{r["source_ref"]}' for r in finals],
                           'ordered_refs': [f'{session}/{r["source_ref"]}' for r in ordered],
                           'interpretation': 'co_occurrence_and_order_only_not_causality'})
    return chains


def validate_report(spec, index):
    if tuple(d['id'] for d in spec['domains']) != DOMAINS:
        raise ValueError('Exactly five ordered domains required')
    if any(d.get('score') is not None for d in spec['domains']):
        raise ValueError('Uncalibrated report must not assign numeric trait scores')
    for domain in spec['domains']:
        if len(domain['facets']) != 3 or not domain['limitations']:
            raise ValueError('Each domain needs three facet dispositions and limitations')
    for block in spec['highlights'] + spec['chains'] + [c for d in spec['domains'] for c in d['claims']]:
        if not block.get('refs'):
            raise ValueError('An observation/interpretation requires source references')
        if any(ref not in index for ref in block['refs']):
            raise ValueError('Unknown or cross-session evidence reference')
        for quote in block.get('quotes', []):
            if quote['ref'] not in block['refs'] or quote['text'] not in index[quote['ref']].get('text', ''):
                raise ValueError('Quote not present in cited player text')
        for check in block.get('checks', []):
            if check['ref'] not in block['refs']:
                raise ValueError('Fact check must cite its source')
            value = index[check['ref']]
            for key in check['path'].split('.'):
                value = value[key]
            if value != check['equals']:
                raise ValueError('Narrative fact does not match source field')
        if block.get('chronological_refs'):
            rows = [index[r] for r in block['chronological_refs']]
            if any(r not in block['refs'] for r in block['chronological_refs']) or len({r['session'] for r in rows}) != 1:
                raise ValueError('Chronology must be sourced within one session')
            times = [r.get('created_at') for r in rows]
            if any(t is None for t in times) or times != sorted(times):
                raise ValueError('Chronological claim reverses recorded order')
    return True


def local_time(value):
    if not value:
        return '未记录'
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime('%m月%d日 %H:%M:%S')


def evidence_description(row):
    if row['kind'] == 'player_language':
        return '本人原文：' + row['text']
    fields = {k: v for k, v in row.items() if k not in {
        'source_ref', 'session', 'created_at', 'day', 'minute', 'trait_score'} and v is not None}
    return json.dumps(fields, ensure_ascii=False, sort_keys=True)


def render(spec, bundles, summaries):
    index = evidence_index(bundles)
    validate_report(spec, index)
    def anchor(ref):
        return 'e-' + ref.replace('/', '-').replace(':', '-')
    def refs(block):
        return ' '.join(f'<a class="ref" href="#{anchor(r)}">{escape(r)}</a>' for r in block['refs'])
    def paragraph(block):
        return f'<p>{escape(block["text"])}<span class="refs">{refs(block)}</span></p>'
    body = [f'<header><p class="eyebrow">潮栖岛 · 个人试玩观察 / 2026.10.19</p><h1>{escape(spec["title"])}</h1><p class="lead">{escape(spec["intro"])}</p><div class="notice">{escape(spec["scope"])}</div></header>',
            '<nav><a href="#overview">五维总览</a><a href="#chains">关键经历</a><a href="#dimensions">逐维分析</a><a href="#evidence">原始证据</a></nav>',
            '<section id="overview"><h2>这次记录能说明什么</h2>']
    body += [paragraph(b) for b in spec['highlights']]
    body += ['<div class="table-wrap"><table><thead><tr><th>维度</th><th>当前观察</th><th>评分</th></tr></thead><tbody>']
    for d in spec['domains']:
        body.append(f'<tr><td><a href="#{d["id"]}">{escape(d["name"])}</a></td><td>{escape(d["summary"])}</td><td class="unrated">暂不评分</td></tr>')
    body += ['</tbody></table></div></section><section id="chains"><h2>把对话与行为放回同一段经历</h2>']
    for b in spec['chains']:
        body += [f'<article class="chain"><h3>{escape(b["title"])}</h3>', paragraph(b), '</article>']
    body += ['</section><section id="dimensions"><h2>五个维度的完整分析</h2>']
    for i, d in enumerate(spec['domains'], 1):
        body += [f'<article class="domain" id="{d["id"]}"><div class="domain-head"><h3>{i:02d} · {escape(d["name"])}</h3><span class="badge">{escape(d["status"])}</span></div>']
        body += [paragraph(c) for c in d['claims']]
        body += ['<div class="facets">']
        for f in d['facets']:
            body.append(f'<div><strong>{escape(f["name"])}</strong><span>{escape(f["assessment"])}</span></div>')
        body += ['</div><div class="limit"><strong>解释边界</strong><p>' + escape(d['limitations']) + '</p></div></article>']
    body += ['</section><section><h2>材料与方法</h2>', '<p>' + escape(spec['method']) + '</p>',
             '<div class="table-wrap"><table><thead><tr><th>场次 / 开始时间</th><th>版本</th><th>操作记录</th><th>本人文本</th><th>有互动的游戏日</th></tr></thead><tbody>']
    for s in summaries:
        body.append(f'<tr><td>{escape(s["label"])} · {local_time(s["started_at_china"])}</td><td>{escape(s["world_version"])}</td><td>{s["action_rows"]}</td><td>{s["language_utterances"]}</td><td>{escape(str(s["interaction_days"]))}</td></tr>')
    body += ['</tbody></table></div><p>' + escape(spec['next_evidence']) + '</p>',
             '<p class="small">概念框架参考：<a href="https://pubmed.ncbi.nlm.nih.gov/27055049/">Soto &amp; John，BFI-2 五维与十五分面研究</a>。该研究未验证本游戏的观察编码和评分方法。</p></section>',
             '<section id="evidence"><h2>可核对的证据附录</h2><p>点击正文来源编号可跳转。原文为你的输入；结构化记录描述系统实际存储的状态。所有编号都带场次，避免不同存档的同号记录混淆。</p>']
    used = {r for b in spec['highlights'] + spec['chains'] + [c for d in spec['domains'] for c in d['claims']] for r in b['refs']}
    used.update(r for r, e in index.items() if e['kind'] == 'player_language')
    for ref in sorted(used):
        e = index[ref]
        stamp = f'游戏第{e["day"]}天 ' if e.get('day') else '状态快照 '
        if e.get('minute') is not None:
            stamp += f'{e["minute"] // 60:02}:{e["minute"] % 60:02} · '
        stamp += '北京时间 ' + local_time(e.get('created_at'))
        body += [f'<article class="evidence" id="{anchor(ref)}"><h3>{escape(ref)}</h3><p class="small">{escape(stamp)}</p><pre>{escape(evidence_description(e))}</pre></article>']
    body += ['</section><footer>离线方法开发版 v0.3 · 人工审阅证据与文案，程序校验引用和顺序 · 未读取BFI答案 · 未改写旧存档/报告 · 不作诊断或人群排名</footer>']
    css = '''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f2ea;color:#233c39;font:16px/1.85 "Microsoft YaHei",sans-serif}main{max-width:1040px;margin:auto;padding:54px 32px}header{padding:16px 0 32px}h1{font-size:40px;line-height:1.3;margin:14px 0 24px}h2{font-size:26px;margin-top:0}h3{font-size:19px;line-height:1.5}.eyebrow{letter-spacing:2px;font-size:12px;color:#687973}.lead{font-size:20px;max-width:850px}.notice,.limit{background:#eeede2;padding:18px 22px;border-left:3px solid #b3a16e}.notice{margin-top:24px}nav{display:flex;flex-wrap:wrap;gap:24px;border-top:1px solid #ccd1c6;border-bottom:1px solid #ccd1c6;padding:12px 0;margin-bottom:36px}a{color:#1f6b62;text-underline-offset:4px}section{margin:32px 0;padding:30px;background:#fffefa;border-radius:12px}p{margin:12px 0}.refs{display:block;font-size:11px;line-height:1.7;margin-top:6px;color:#667}.ref{display:inline-block;margin-right:9px;overflow-wrap:anywhere}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:14px 12px;border-bottom:1px solid #e3e7df}th{background:#edf2ed}.unrated{white-space:nowrap;color:#7a6a40}.domain,.chain{padding:20px 0;border-bottom:1px solid #dce2d8}.domain:last-child{border:0}.domain-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.badge{background:#edf2ed;padding:4px 12px;font-size:12px;border-radius:18px;white-space:nowrap}.facets{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.facets div{background:#f3f5ef;padding:16px;font-size:13px}.facets strong,.facets span{display:block}.limit{font-size:14px}.small,footer{font-size:12px;color:#65736d}.evidence{padding:14px 0;border-bottom:1px solid #e1e6dc;scroll-margin-top:20px}.evidence:target{background:#fff4c9}.evidence h3{font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.8 "Microsoft YaHei",sans-serif;background:#f5f6f1;padding:16px}footer{padding:24px 0}@media(max-width:650px){main{padding:22px 12px}section{padding:20px 16px}h1{font-size:30px}.lead{font-size:17px}.facets{grid-template-columns:1fr}.domain-head{display:block}}@media print{body{background:white;font-size:11pt}main{padding:0;max-width:none}section{padding:10px 0;margin:14px 0}nav{display:none}h1{font-size:26pt}.domain,.chain{break-inside:avoid}.evidence{break-inside:avoid}a{color:inherit}footer{border-top:1px solid #ccc}}'''
    html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(spec['title']) + '</title><style>' + css + '</style></head><body><main>' + ''.join(body) + '</main></body></html>'
    text = [spec['title'], '2026-10-19 · 离线方法开发版 v0.3', '', spec['intro'], spec['scope'], '', '一、主要观察']
    def plain(block):
        return block['text'] + '\n来源：' + '；'.join(block['refs'])
    text += [plain(b) for b in spec['highlights']]
    text += ['', '二、关键经历'] + [b['title'] + '\n' + plain(b) for b in spec['chains']]
    text += ['', '三、五维分析（所有维度暂不评分）']
    for d in spec['domains']:
        text += ['', d['name'] + '：' + d['status']] + [plain(c) for c in d['claims']]
        text += [f'{f["name"]}：{f["assessment"]}' for f in d['facets']]
        text += ['解释边界：' + d['limitations']]
    text += ['', '四、材料与方法', spec['method'], spec['next_evidence'], '', '五、证据附录']
    for ref in sorted(used):
        text += ['', ref + ' · ' + local_time(index[ref].get('created_at')), evidence_description(index[ref])]
    return html, '\n\n'.join(text), {'method': VERSION, 'domains': spec['domains'], 'chains': episode_chains(bundles), 'cited_sources': sorted(used)}
