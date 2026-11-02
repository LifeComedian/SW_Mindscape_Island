"""Validate and store vector drawing data."""
import math
import re


def validate_drawing(strokes,styles,version,fail):
    modern=version=='chaoxi-holiday-v6'
    if not isinstance(strokes,list) or not 1<=len(strokes)<=(256 if modern else 40):
        fail('请画下内容后再保存，最多保留256笔。')
    if sum(len(s) if isinstance(s,list) else 12001 for s in strokes)>12000:
        fail('这张画的线条太多，请先删去一些笔画。')
    for line in strokes:
        if not isinstance(line,list) or not 1<=len(line)<=(2048 if modern else 20):
            fail('笔画格式不正确。')
        for point in line:
            if not isinstance(point,list) or len(point)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=100 for n in point):
                fail('笔画超出了画纸。')
    if styles is None:styles=[{'color':'#355f59','width':.75,'erase':False} for _ in strokes]
    if not isinstance(styles,list) or len(styles)!=len(strokes):fail('画笔样式与笔画不一致。')
    for style in styles:
        if not isinstance(style,dict) or not isinstance(style.get('color'),str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',style['color']):
            fail('画笔颜色不正确。')
        width=style.get('width')
        if type(width) not in (int,float) or not math.isfinite(width) or not .1<=width<=8 or type(style.get('erase'))!=bool:
            fail('画笔样式不正确。')
    if all(s['erase'] for s in styles):fail('请先用画笔画下内容。')
    return strokes,[{k:s[k] for k in ('color','width','erase')} for s in styles]
