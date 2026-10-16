"""Mind-map renderer (refactor of /workspace/x/mindmap_pilot/gen_v2.py, Oct 16).

Editorial paper style: flat #F4EFE6, serif headings, ONE brick accent (#9C3D2E) plus a muted green / grey for the deeper
levels, hand-drawn-feeling underline + curve connectors, no gradient / icon / pill. Dense 3-4 level tree, 35-60 nodes.

Data (JSON-safe dict, also what mindmap/gen.py produces):
    {"title": str, "subtitle": str, "lang": "zh"|"en", "footer": str,
     "branches": [{"t": str, "c": [{"t": str, "c": [{"t": str, "c": [{"t": str}]}]}]}]}
Root = title; branches = level 1; at most 4 levels below the root. `validate()` is the shape / size gate; `to_html()` is
pure; `render_png()` shells out to a Python with playwright (FD_MINDMAP_PYTHON, default /usr/bin/python3) + chrome.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PAPER = '#F4EFE6'
BRICK = '#9C3D2E'
GREEN = '#3F5348'
GREY = '#6b625a'
INK = '#222'
PAGE_W = 1700
MAX_DEPTH = 4            # levels below the root
MIN_NODES, MAX_NODES = 36, 64
MAX_BRANCHES = 8
LABEL_MAX = {'zh': {1: 14, 2: 22, 3: 40, 4: 40}, 'en': {1: 34, 2: 56, 3: 100, 4: 100}}
# glyph guard: Latin / digits / punctuation / CJK / full-width forms only (no emoji or symbol that could render as tofu)
SAFE_CHAR = re.compile(r'^[\u0020-\u007e\u00a0-\u024f\u2010-\u2027\u2030-\u205e\u20a0-\u20bf\u2190-\u2194\u2212\u00d7'
                       r'\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef\u00b7\u2022\u2026]*$')


def walk(branches, level=1):
    for n in branches or ():
        yield n, level
        yield from walk(n.get('c'), level + 1)


def count_nodes(data):
    return sum(1 for _ in walk(data.get('branches')))


def validate(data, *, strict_counts=True):
    """[problem strings]; empty = renderable. Shape, depth, label length, glyph safety, node count."""
    errs = []
    if not isinstance(data, dict):
        return ['not an object']
    lang = 'zh' if str(data.get('lang') or 'zh').startswith('zh') else 'en'
    if not str(data.get('title') or '').strip():
        errs.append('title missing')
    br = data.get('branches')
    if not isinstance(br, list) or not br:
        return errs + ['branches missing']
    if len(br) > MAX_BRANCHES:
        errs.append(f'{len(br)} branches > {MAX_BRANCHES}')
    n = 0
    for node, lvl in walk(br):
        n += 1
        t = node.get('t') if isinstance(node, dict) else None
        if not isinstance(t, str) or not t.strip():
            errs.append(f'empty label at level {lvl}')
            continue
        if lvl > MAX_DEPTH:
            errs.append(f'depth {lvl} > {MAX_DEPTH}')
        lim = LABEL_MAX[lang].get(min(lvl, 4), 40)
        if len(t) > lim:
            errs.append(f'label too long ({len(t)} > {lim}) L{lvl}: {t[:24]}')
        if not SAFE_CHAR.match(t):
            bad = ''.join(sorted({c for c in t if not SAFE_CHAR.match(c)}))
            errs.append(f'unsafe glyph {bad!r}: {t[:20]}')
    if strict_counts and not (MIN_NODES <= n <= MAX_NODES):
        errs.append(f'{n} nodes not in {MIN_NODES}-{MAX_NODES}')
    for k in ('title', 'subtitle', 'footer'):
        if data.get(k) and not SAFE_CHAR.match(str(data[k]).replace('\n', ' ')):
            errs.append(f'unsafe glyph in {k}')
    return errs


def _esc(s):
    return html.escape(str(s), quote=False)


def _widths(branches):
    """Label box width per (level, has_children). Leaves take the width left to the right edge (capped)."""
    col = {1: 215, 2: 225, 3: 205, 4: 230}
    gap = {1: 56, 2: 44, 3: 40, 4: 40}
    tree_w = PAGE_W - 120 - 250 - 70
    used, out = 0, {}
    for lvl in (1, 2, 3, 4):
        left = max(250, tree_w - used)
        out[(lvl, True)] = col[lvl]
        out[(lvl, False)] = min(left, 470)
        used += col[lvl] + gap[lvl]
    return out


def _nodes_html(nodes, level, parent, counter, widths):
    out = []
    for n in nodes:
        counter[0] += 1
        nid = f'n{counter[0]}'
        kids = n.get('c') or []
        w = widths[(min(level, 4), bool(kids))]
        has = ' has' if kids else ''
        out.append(f'<div class="n"><div class="node l{level}{has}" id="{nid}" data-p="{parent}" data-lvl="{level}" '
                   f'style="width:{w}px"><span>{_esc(n["t"])}</span></div>')
        if kids:
            out.append('<div class="kids">' + _nodes_html(kids, level + 1, nid, counter, widths) + '</div>')
        out.append('</div>')
    return ''.join(out)


def to_html(data):
    lang = 'zh' if str(data.get('lang') or 'zh').startswith('zh') else 'en'
    widths = _widths(data['branches'])
    tree = ''.join(
        f'<div class="branch">{_nodes_html([b], 1, "root", [i * 1000], widths)}</div>'
        for i, b in enumerate(data['branches']))
    zh = lang == 'zh'
    serif = '"Noto Serif CJK SC","Noto Serif",serif' if zh else '"Noto Serif","Noto Serif CJK SC",serif'
    sans = '"Noto Sans CJK SC","Noto Sans",sans-serif' if zh else '"Noto Sans","Noto Sans CJK SC",sans-serif'
    fs3 = 16 if zh else 15
    lh3 = 1.6 if zh else 1.45
    sub = f'<span class="sub">{_esc(data["subtitle"]).replace(chr(10), "<br>")}</span>' if data.get('subtitle') else ''
    footer = _esc(data.get('footer') or '')
    css = f'''*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{PAPER};width:{PAGE_W}px;color:{INK};font-family:{sans};font-weight:300}}
#wrap{{position:relative;padding:70px 60px 40px 60px;display:flex;align-items:center;gap:70px}}
#svg{{position:absolute;left:0;top:0;pointer-events:none}}
.root{{width:250px;flex:none;position:relative;z-index:1}}
.root span.t{{display:inline-block;padding-bottom:5px;font-family:{serif};font-weight:700;font-size:{26 if zh else 24}px;line-height:1.3;color:{INK}}}
.root span.sub{{display:block;font-family:{sans};font-weight:300;font-size:{16 if zh else 15}px;line-height:1.6;margin-top:8px}}
#tree{{display:flex;flex-direction:column;gap:34px;flex:1}}
.branch{{display:flex}}
.n{{display:flex;align-items:center;gap:44px}}
.kids{{display:flex;flex-direction:column;gap:12px}}
.branch>.n{{gap:56px}}.branch>.n>.kids{{gap:20px}}
.node{{position:relative;z-index:1;flex:none}}
.node span{{display:inline-block;padding-bottom:5px}}
.l1 span{{font-family:{serif};font-weight:700;font-size:{21 if zh else 19}px;line-height:1.35;color:{BRICK}}}
.l2 span{{font-family:{serif};font-weight:700;font-size:{17 if zh else 16}px;line-height:1.4;color:{INK}}}
.l3 span{{font-size:{fs3}px;line-height:{lh3};color:{INK}}}
.l4 span{{font-size:{fs3}px;line-height:{lh3};color:{INK}}}
.l3.has span{{font-style:italic;font-family:{serif};font-weight:400;color:{GREEN}}}
.foot{{margin:10px 0 0 0;font-family:{serif};font-size:15px;color:{INK};padding:0 60px 30px;display:flex;justify-content:flex-end}}
.foot b{{color:{BRICK}}}'''
    js = f'''
const wrap=document.getElementById('wrap'),W=wrap.getBoundingClientRect();
const svg=document.getElementById('svg');svg.setAttribute('width',W.width);svg.setAttribute('height',W.height);
let out='',seed=1;
function wob(x1,y1,x2,y2,s){{const dx=x2-x1;const r=(k)=>(Math.sin(s*12.9898+k*78.233)*43758.5453)%1;const j=(k)=>r(k)*3;
 return `M${{x1}},${{y1}} C${{x1+dx*.5+j(1)}},${{y1+j(2)}} ${{x1+dx*.5+j(3)}},${{y2+j(4)}} ${{x2}},${{y2+j(5)*0.3}}`;}}
const nodes=[...document.querySelectorAll('.node')];
const U=new Map();
function ul(n){{const sp=n.querySelector('span').getBoundingClientRect(),bx=n.getBoundingClientRect();
 const lvl=+n.dataset.lvl;const c=lvl<=2?'{BRICK}':'{GREY}';
 const x1=bx.left-W.left,xr=n.id==='root'?sp.right-W.left:bx.right-W.left,y=sp.bottom-W.top;
 out+=`<path d="M${{x1}},${{y}} L${{xr}},${{y+0.6}}" stroke="${{c}}" stroke-width="1.5" fill="none"/>`;U.set(n.id,[x1,xr,y]);}}
ul(document.getElementById('root'));nodes.forEach(ul);
const colr=l=>l<=2?'{BRICK}':(l==3?'{GREEN}':'{GREY}');
nodes.forEach(n=>{{const P=U.get(n.dataset.p),C=U.get(n.id);if(!P||!C)return;
 const lvl=+n.dataset.lvl,col=colr(lvl<=2?1:lvl);
 out+=`<path d="${{wob(P[1],P[2],C[0],C[2],seed++)}}" stroke="${{col}}" stroke-width="1.5" fill="none"/>`;
 out+=`<circle cx="${{P[1]}}" cy="${{P[2]}}" r="3" fill="{PAPER}" stroke="${{col}}" stroke-width="1.2"/>`;
 out+=`<circle cx="${{C[0]}}" cy="${{C[2]}}" r="3" fill="{PAPER}" stroke="${{col}}" stroke-width="1.2"/>`;}});
svg.innerHTML=out;document.body.dataset.ready='1';'''
    return (f'<!doctype html><html lang="{"zh-CN" if zh else "en"}"><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body><div id="wrap"><svg id="svg"></svg><div class="root"><div class="node" id="root" data-lvl="0">'
            f'<span class="t">{_esc(data["title"])}</span>{sub}</div></div><div id="tree">{tree}</div></div>'
            f'<div class="foot"><span>{footer}</span></div><script>{js}</script></body></html>')


def python_exe():
    return os.environ.get('FD_MINDMAP_PYTHON') or '/usr/bin/python3'


SHOT = Path(__file__).with_name('shot.py')


def render_png(data, png_path, html_path=None, timeout=90):
    """Render `data` to png_path (2x device scale, 1700 css px wide). Returns {'path','w','h','html'}."""
    errs = validate(data, strict_counts=False)
    if errs:
        raise ValueError('mindmap data invalid: ' + '; '.join(errs[:5]))
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    html_path = Path(html_path) if html_path else png_path.with_suffix('.html')
    html_path.write_text(to_html(data), encoding='utf-8')
    r = subprocess.run([python_exe(), str(SHOT), str(html_path), str(png_path)], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0 or not png_path.exists():
        raise RuntimeError('mindmap screenshot failed: ' + (r.stderr or r.stdout)[-300:])
    info = json.loads(r.stdout.strip().splitlines()[-1])
    return {'path': str(png_path), 'html': str(html_path), **info}
