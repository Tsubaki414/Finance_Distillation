"""Mind-map content generation (Oct 16): source text -> structured tree JSON, faithful to the source (no invention).

One model call (Gemini through the compose stage client, i.e. FD_GEMINI_PROVIDER; subrouter in tests) returns
{skip?, title, branches[{t, c[...], q}], caption}. `q` = a short VERBATIM excerpt of the source that supports a node
(L2+ nodes); it is never rendered. Deterministic gates after the call:
  - support: normalised `q` must occur in the normalised source (substring); > FD_MINDMAP_UNSUPPORTED_MAX (0.2) of the
    nodes that carry one failing, or any L3/L4 leaf without `q`, drops that node; > 25 % dropped -> hard 'mm_unsupported'
  - numbers: every Arabic number in a label must occur in the source text (else the node is dropped, same counters)
  - shape / size / glyph safety: render.validate (30-64 nodes, <= 4 levels, label length, no emoji / tofu glyphs)
  - caption: own voice, no @handle / credit line / hashtag / emoji / return claim / contrast frame, length cap
Credit (author, title, date, host) is added deterministically as the image footer, never by the model.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse

from live.mindmap import render

VERSION = 'mindmap-v1'
MAX_SOURCE_CHARS = 30000

PROMPT = """You turn ONE long-form source (blog post / video transcript / book summary) into a dense, faithful MIND MAP
for the X account described below, plus a one-or-two sentence caption in that account's voice.

HARD RULES
1. FAITHFUL: every node restates something the source actually says. No invention, no outside knowledge, no added
   examples, numbers, names, dates, predictions, advice or opinions. If the source is thin, make a smaller map.
2. If the source is not about investing / markets / crypto / personal finance / money habits / decision making for
   investors, or is mostly promotion, politics, dating or lifestyle fluff, return exactly {{"skip": "<short reason>"}}.
3. Language of every label, title and caption: {lang_name}. If the source is in another language, translate faithfully
   (keep proper names, tickers and numbers as in the source).
4. Structure: root = the source's core thesis (title). 5-7 level-1 branches (themes, a few words each), each with
   2-4 level-2 nodes (claims / steps), their level-3 nodes (reasons, mechanisms, examples) and level-4 nodes (specific
   detail, figure, condition). The map must be DENSE and 4 LEVELS DEEP: 40-60 nodes in total, at least 10 level-4 nodes
   spread over at least 4 branches, depth never more than 4 below the root. If the source is too thin for that, return
   {{"skip": "too thin"}} instead of padding.
5. Label length: level 1 <= {l1} chars; level 2 <= {l2}; level 3-4 <= {l3} (count characters, zh chars count 1). Short
   noun phrases or one short sentence; no trailing full stop; no emoji, no symbols other than ordinary punctuation.
6. Evidence: every node at level 2, 3 and 4 carries "q": a VERBATIM excerpt (8-90 characters, copied exactly, in the
   SOURCE language, no ellipsis) from the source that supports it. Level-1 nodes need no "q".
7. Numbers: only numbers that appear in the source, written the way the source writes them.
8. Do not mention a video, speaker, channel, @handle, or "the author says" inside labels; state the content directly.
9. Caption ({cap_len}): the account's own voice, plain, no hashtags, no emoji, no @, no credit line, no hype, no
   "in this thread"; say what the map lays out or the one idea that matters most, in the account's register. No
   investment advice, no return claims, no "not X but Y" frame.

VOICE / ACCOUNT (JSON): {account}

Return ONE JSON object only:
{{"title": "...", "branches": [{{"t": "...", "c": [{{"t": "...", "q": "...", "c": [{{"t": "...", "q": "...", "c": [{{"t": "...", "q": "..."}}]}}]}}]}}], "caption": "..."}}
"""

CAPTION_MAX = {'zh': 110, 'en': 260}
HASHTAG = re.compile(r'(?<!\w)#\w')
EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]')
CONTRAST_EN = re.compile(r"\b(?:it'?s|this is|that'?s) not\b[^.!?\n]{1,60}[,;]?\s*(?:it'?s|but)\b|\bnot (?:just|merely|only)\b[^.!?\n]{1,50}\bbut\b", re.I)


def norm(s):
    """Match-form: NFKC, casefold, keep only letters / digits / CJK (so punctuation and spacing differences vanish)."""
    s = unicodedata.normalize('NFKC', str(s or '')).casefold()
    return re.sub(r'[^0-9a-z\u3400-\u9fff\u00c0-\u024f]+', '', s)


def lang_name(lang):
    return 'Chinese (简体中文)' if str(lang).startswith('zh') else 'English'


def build_messages(account_cfg, voice, text, item):
    lang = 'zh' if str(account_cfg.get('lang', 'zh')).startswith('zh') else 'en'
    lim = render.LABEL_MAX[lang]
    acct = {k: account_cfg.get(k) for k in ('id', 'name', 'lang', 'beat', 'focus')}
    acct['voice'] = voice or {}
    system = PROMPT.format(lang_name=lang_name(lang), l1=lim[1], l2=lim[2], l3=lim[3], account=json.dumps(acct, ensure_ascii=False),
                           cap_len=f'<= {CAPTION_MAX[lang]} ' + ('Chinese characters' if lang == 'zh' else 'characters'))
    user = json.dumps({'source_language': item.get('lang'), 'source_title': item.get('title'), 'source_kind': item.get('kind'),
                       'source_text': text[:MAX_SOURCE_CHARS]}, ensure_ascii=False)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def _numbers(s):
    return [m.replace(',', '') for m in re.findall(r'\d[\d,]*(?:\.\d+)?', unicodedata.normalize('NFKC', str(s)))]


def prune(tree, source):
    """Drop nodes whose evidence / numbers do not hold against `source`. Returns (branches, stats). Children of a dropped
    node go with it; a level-1 branch left with < 2 children is dropped."""
    nsrc = norm(source)
    nsrc_digits = norm(re.sub(r'[,，]', '', source))
    src_nums = set(_numbers(source))
    stats = {'nodes_in': 0, 'dropped_support': 0, 'dropped_number': 0, 'dropped_shape': 0}

    def ok_node(n, lvl):
        t = n.get('t')
        if not isinstance(t, str) or not t.strip():
            stats['dropped_shape'] += 1
            return False
        if lvl >= 2:
            q = norm(n.get('q'))
            if len(q) < 6 or q not in nsrc:
                stats['dropped_support'] += 1
                return False
        for num in _numbers(t):
            if num not in src_nums and norm(num) not in nsrc_digits:
                stats['dropped_number'] += 1
                return False
        return True

    def rec(nodes, lvl):
        out = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            stats['nodes_in'] += 1
            if lvl > render.MAX_DEPTH or not ok_node(n, lvl):
                continue
            kids = rec(n.get('c'), lvl + 1)
            node = {'t': n['t'].strip().rstrip('。.；;'), 'c': kids} if kids else {'t': n['t'].strip().rstrip('。.；;')}
            if n.get('q'):
                node['q'] = n['q']
            out.append(node)
        return out

    branches = [b for b in rec(tree.get('branches'), 1) if len(b.get('c') or []) >= 2]
    stats['dropped'] = stats['dropped_support'] + stats['dropped_number'] + stats['dropped_shape']
    stats['nodes_out'] = sum(1 for _ in render.walk(branches))
    return branches, stats


def strip_q(branches):
    def rec(ns):
        return [({'t': n['t'], 'c': rec(n['c'])} if n.get('c') else {'t': n['t']}) for n in ns]
    return rec(branches)


def caption_findings(text, lang, source=None):
    out = []
    t = (text or '').strip()
    if not t:
        return [('mm_caption_empty', 'empty caption')]
    if len(t) > CAPTION_MAX[lang]:
        out.append(('mm_caption_long', f'{len(t)} > {CAPTION_MAX[lang]}'))
    if HASHTAG.search(t) or EMOJI.search(t):
        out.append(('mm_caption_hashtag_emoji', t[:40]))
    from live import own_voice_strip, video_src
    for f in own_voice_strip.findings(t):
        out.append(('mm_caption_' + f['code'], f['detail']))
    if video_src.RETURN_CLAIM.search(t):
        out.append(('mm_caption_return_claim', t[:40]))
    if lang == 'zh' and video_src.CONTRAST.search(t) or lang == 'en' and CONTRAST_EN.search(t):
        out.append(('mm_caption_contrast', t[:40]))
    if source is not None:   # every number in the caption must be in the source (translation / unit conversions fail closed)
        src_nums = set(_numbers(source))
        nsrc = norm(re.sub(r'[,，]', '', source))
        miss = [n for n in _numbers(t) if n not in src_nums and norm(n) not in nsrc]
        if miss:
            out.append(('mm_caption_number', 'not in source: ' + ','.join(miss[:4])))
    return out


def credit_footer(item, lang):
    host = urlparse(item.get('url') or '').netloc.replace('www.', '')
    when = str(item.get('published_at') or '')[:10]
    author = item.get('author') or item.get('name') or ''
    title = (item.get('title') or '').strip().replace('\n', ' ')
    title = title[:70] + ('…' if len(title) > 70 else '')
    kind = item.get('kind')
    if lang == 'zh':
        what = {'youtube': '视频', 'x_video': '视频', 'book': '书', 'blog': '文章'}.get(kind, '内容')
        bits = [f'整理自{what}《{title}》' if title else f'整理自{what}', author if author and author not in title else '', when, host]
        return ' · '.join(b for b in bits if b) + ' · 要点为转述,非原文'
    what = {'youtube': 'video', 'x_video': 'video', 'book': 'book', 'blog': 'article'}.get(kind, 'source')
    bits = [f'Summary of the {what} "{title}"' if title else f'Summary of a {what}', f'by {author}' if author and author not in title else '', when, host]
    return ' · '.join(b for b in bits if b) + ' · paraphrased, not a quote'


def thin(branches):
    levels = [l for _n, l in render.walk(branches)]
    return len(levels) < render.MIN_NODES or levels.count(4) < 6


def make_tree(ask, account_cfg, voice, text, item, *, max_unsupported=0.25):
    """ask(messages) -> (parsed dict, raw response dict). Returns {'status','data','caption','stats','findings','raw'}."""
    lang = 'zh' if str(account_cfg.get('lang', 'zh')).startswith('zh') else 'en'
    msgs = build_messages(account_cfg, voice, text, item)
    parsed, raw = ask(msgs)
    if parsed.get('skip'):
        return {'status': 'skip', 'why': str(parsed['skip'])[:160], 'findings': []}
    branches, stats = prune(parsed, text)
    if thin(branches):   # one repair round: ask for the missing depth / density (still source-only)
        stats['repair_round'] = True
        msgs2 = msgs + [{'role': 'assistant', 'content': json.dumps(parsed, ensure_ascii=False)},
                        {'role': 'user', 'content': 'Too thin or too shallow after checking. Return the FULL JSON again with 40-60 nodes and at '
                                                    'least 10 level-4 nodes (each with its verbatim "q"), using only the source. Same rules.'}]
        parsed2, raw2 = ask(msgs2)
        if parsed2.get('skip'):
            return {'status': 'skip', 'why': str(parsed2['skip'])[:160], 'findings': []}
        b2, s2 = prune(parsed2, text)
        if len(list(render.walk(b2))) >= len(list(render.walk(branches))):
            parsed, raw, branches, stats = parsed2, raw2, b2, {**s2, 'repair_round': True}
    findings = []
    n_in = max(1, stats['nodes_in'])
    if stats['dropped'] / n_in > max_unsupported:
        findings.append({'code': 'mm_unsupported', 'level': 'hard',
                         'detail': f"{stats['dropped']}/{stats['nodes_in']} nodes not supported by the source"})
    title = str(parsed.get('title') or item.get('title') or '').strip()
    sub_bits = [item.get('author') or item.get('name') or '']
    if item.get('lang') and str(item['lang'])[:2] != lang and item.get('title'):
        sub_bits.append(str(item['title'])[:80])
    data = {'title': title, 'subtitle': '\n'.join(b for b in sub_bits if b), 'lang': lang,
            'footer': credit_footer(item, lang), 'branches': strip_q(branches)}
    # subtitle must be glyph-safe too (foreign titles): fall back to author only
    if not render.SAFE_CHAR.match(data['subtitle'].replace('\n', ' ')):
        data['subtitle'] = sub_bits[0] if render.SAFE_CHAR.match(sub_bits[0]) else ''
    if not render.SAFE_CHAR.match(data['footer']):
        data['footer'] = re.sub(r'[^\u0020-\u007e\u00a0-\u024f\u2010-\u2027\u3000-\u303f\u3400-\u9fff\uff00-\uffef\u00b7\u2022\u2026]', '', data['footer'])
    for e in render.validate(data):
        findings.append({'code': 'mm_shape', 'level': 'hard', 'detail': e[:160]})
    caption = re.sub(r'\s+', ' ', str(parsed.get('caption') or '')).strip()
    cap_f = caption_findings(caption, lang, text)
    if cap_f and not any(f['code'] in ('mm_unsupported', 'mm_shape') for f in findings):
        # one small repair call for the caption only (the tree is fine): rewrite without the flagged patterns
        try:
            fix, _raw = ask([{'role': 'system', 'content': 'Rewrite the caption for the X account. Language: %s. At most %d characters, '
                              'plain own voice, no hashtag / emoji / @ / credit line / return claim, and NO contrast frame (zh: 不是X而是Y, '
                              '并非…而是; en: not X but Y). Keep only what the mind map says; every number must be one that appears in the source_numbers list (else drop it). Return {"caption": "..."}.' % (
                                  lang_name(lang), CAPTION_MAX[lang])},
                             {'role': 'user', 'content': json.dumps({'title': title, 'map_branches': [b['t'] for b in branches],
                                                                     'bad_caption': caption, 'problems': [f'{c}: {d}' for c, d in cap_f],
                                                                     'source_numbers': sorted(set(_numbers(text)))[:60]},
                                                                    ensure_ascii=False)}])
            caption = re.sub(r'\s+', ' ', str(fix.get('caption') or '')).strip()
            stats['caption_repaired'] = True
        except Exception:   # noqa: BLE001 - the original findings stand
            pass
    for code, detail in caption_findings(caption, lang, text):
        findings.append({'code': code, 'level': 'hard', 'detail': detail})
    stats['nodes'] = render.count_nodes(data)
    return {'status': 'ok', 'data': data, 'caption': caption, 'stats': stats, 'findings': findings, 'raw': raw}
