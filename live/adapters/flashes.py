"""7x24 news flashes (Oct 6 v10, Fiona approved): 华尔街见闻 / 东方财富 / 新浪财经.

Public JSON list endpoints the outlets' own 7x24 pages use (no login, no key, honest UA). Each flash
becomes one small EXTRACT-ready source (licence tier B, facts only, no reproduction, the original
outlet credited when the flash names one). Flashes are short, so they go through the batched cheap
extraction path (live/flash_extract.py) under their own ring-fenced budget, not the per-source opus
EXTRACT.

Cross-outlet dedupe: the same event reported by several outlets within N hours keeps one
representative (the longest text) and records the others in `also_reported_by`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from live.adapters import common
from live.distillation_source import digest

CST = timezone(timedelta(hours=8))
OUTLETS = {
    'ch141_wscn_flash': {'publisher': '华尔街见闻7x24',
                         'url': 'https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit={n}'},
    'ch143_eastmoney_flash': {'publisher': '东方财富7x24',
                              'url': 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_{n}_1_.html'},
    'ch144_sina_flash': {'publisher': '新浪财经7x24',
                         'url': 'https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size={n}&zhibo_id=152'},
}
MIN_CHARS = 20
_CJK_GAP = re.compile(r'(?<=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef])\s+(?=[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef])')


def _clean(text):
    """html_text puts a space where inline tags were (<b>英伟达</b>盘后 -> '英伟达 盘后'); drop CJK-CJK gaps."""
    return _CJK_GAP.sub('', str(text or '')).strip()
_OUTLET_WORD = re.compile(r'新浪|东方财富|华尔街见闻|财联社|每经|21世纪|财经|社|网|报|新闻|日报|时报|电视|证券|彭博|路透|央视|新华|彭博社|Bloomberg|Reuters|CNBC|WSJ|FT|金十|格隆汇|界面|澎湃|第一财经|智通|券商中国')
_TRAILING = re.compile(r'[（(]([^（）()]{2,14})[）)]\s*$')
_CITED = re.compile(r'(?:^|[，。；\s])(?:据|援引|来自)([^，,。；：:]{2,12}?)(?:报道|消息|援引|获悉|称)')
_WIRE = re.compile(r'^【[^】]*】?\s*([\u4e00-\u9fff]{2,6}社)\d{1,2}月\d{1,2}日电')
_PROMO = re.compile(r'APP|下载|扫码|点击查看|开户|直播间|广告|会员|VIP|付费')


def original_outlet(text, own):
    """The outlet a flash credits (trailing （新浪财经）, 据XX报道, XX社10月6日电), else None."""
    text = str(text or '').strip()
    for rx in (_WIRE, _TRAILING, _CITED):
        m = rx.search(text)
        if m:
            name = m.group(1).strip()
            if _OUTLET_WORD.search(name) and name not in own:
                return name
    return None


def _iso(ts):
    return ts.astimezone(timezone.utc).isoformat()


def _parse_wscn(body):
    for item in (json.loads(body).get('data') or {}).get('items') or []:
        if item.get('is_priced'):
            continue
        text = _clean(item.get('content_text') or common.html_text(item.get('content') or ''))
        ts = item.get('display_time')
        yield {'id': f"wscn-flash-{item['id']}", 'text': text, 'title': (item.get('title') or '').strip(),
               'published': datetime.fromtimestamp(int(ts), timezone.utc) if ts else None,
               'url': item.get('uri') or f"https://wallstreetcn.com/livenews/{item['id']}",
               'score': int(item.get('score') or 1)}


def _parse_eastmoney(body):
    body = body[body.index('{'):].rstrip().rstrip(';')
    for item in json.loads(body).get('LivesList') or []:
        text = (item.get('digest') or item.get('title') or '').strip()
        try:
            published = datetime.strptime(item.get('showtime') or '', '%Y-%m-%d %H:%M:%S').replace(tzinfo=CST)
        except ValueError:
            published = None
        yield {'id': f"em-flash-{item.get('newsid') or item.get('id')}", 'text': text,
               'title': (item.get('title') or '').strip(), 'published': published,
               'url': (item.get('url_unique') or item.get('url_w') or '').replace('http://', 'https://', 1), 'score': 1}


def _parse_sina(body):
    feed = (((json.loads(body).get('result') or {}).get('data') or {}).get('feed') or {}).get('list') or []
    for item in feed:
        text = _clean(common.html_text(item.get('rich_text') or ''))
        try:
            published = datetime.strptime(item.get('create_time') or '', '%Y-%m-%d %H:%M:%S').replace(tzinfo=CST)
        except ValueError:
            published = None
        yield {'id': f"sina-flash-{item.get('id')}", 'text': text, 'title': '', 'published': published,
               'url': item.get('docurl') or '', 'score': 2 if item.get('is_focus') else 1}


PARSERS = {'ch141_wscn_flash': _parse_wscn, 'ch143_eastmoney_flash': _parse_eastmoney, 'ch144_sina_flash': _parse_sina}


def to_source(channel_id, flash):
    """EXTRACT-ready source for one flash (tier B facts only; original outlet credited)."""
    spec = OUTLETS[channel_id]
    text = flash['text']
    outlet = original_outlet(text, spec['publisher'])
    title = flash.get('title') or (re.match(r'^【([^】]{4,80})】', text).group(1) if re.match(r'^【([^】]{4,80})】', text) else text[:40])
    return {'id': flash['id'], 'source_id': channel_id, 'source_hash': digest(text), 'original_text': text,
            'author_name': spec['publisher'], 'publisher': spec['publisher'], 'title': title, 'url': flash.get('url') or '',
            'published_at': _iso(flash['published']) if flash.get('published') else None, 'source_language': 'zh',
            'source_version': 'flash-v1', 'adapter': 'flash:' + channel_id, 'truncated': False,
            'no_reproduction': True, 'original_outlet': outlet, 'flash_score': flash.get('score', 1),
            'also_reported_by': []}


def fetch(channel_id, *, n=50, since=None, transport=None, now=None):
    """{'status', 'sources'} for one outlet: flashes newer than `since` (datetime), promo/short ones dropped."""
    spec = OUTLETS[channel_id]
    status, body = common.http_get(spec['url'].format(n=n), transport=transport)
    if status != 200:
        return {'status': f'http_{status}', 'sources': []}
    now = now or datetime.now(timezone.utc)
    out = []
    for flash in PARSERS[channel_id](body):
        text = flash['text']
        if len(text) < MIN_CHARS or _PROMO.search(text) or flash['published'] is None:
            continue
        if flash['published'] > now + timedelta(hours=1) or (since and flash['published'] < since):
            continue
        out.append(to_source(channel_id, flash))
    return {'status': 'ok' if out else 'no_new_flashes', 'sources': out}


# ---------- dedupe ----------

_NORM = re.compile(r'[\s\W_]+', re.U)


def _bigrams(text):
    t = _NORM.sub('', re.sub(r'^【[^】]*】', '', str(text or '')).lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


_NUM = re.compile(r'\d+(?:\.\d+)?')


def _numbers(text):
    """Distinctive numbers only: a decimal, >= 3 digits, or a number with a unit (%/亿/万/美元/点/基点).
    Bare 9 (9月) / 6 (6日) / 2026 are dates, not evidence of the same event."""
    out = set()
    for m in _NUM.finditer(str(text or '')):
        v, tail = m.group(), str(text)[m.end():m.end() + 2]
        if re.match(r'\d{4}$', v) and v.startswith(('19', '20')) and not tail.startswith(('亿', '万', '点', '美', '%')):
            continue
        if '.' in v or len(v) >= 3 or re.match(r'%|亿|万|美元|欧元|港元|日元|英镑|元|点|基点|bp|倍|桶|盎司|吨', tail):
            if not re.match(r'(?:月|日|年|时|分|季|周)', tail):
                out.add(v)
    return out


def similar(a, b, *, threshold=0.5):
    """Same event? Char-bigram Jaccard j and containment c (overlap / smaller set), plus distinctive
    numbers (see _numbers). Both sides carrying distinctive numbers with none in common is a conflict
    (泰国 2.82% vs 土耳其 29.8%; 印度综合 PMI 55.9 vs 服务业 55.2; WTI 90 vs 布油 100) and vetoes a
    merge unless the texts are near-identical (j >= 0.7). Otherwise: j >= threshold, or j >= 0.3 with
    >= 2 shared numbers, or c >= 0.4 with a shared number or j >= 0.2 (re-worded copies across outlets:
    月之暗面 / 可灵AI / 苏姿丰 in the live 10/6 pool sat at c 0.43-0.48)."""
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return False
    inter = len(x & y)
    j = inter / len(x | y)
    na, nb = _numbers(a), _numbers(b)
    shared = na & nb
    if na and nb and not shared:
        return j >= 0.7
    if j >= threshold or (j >= 0.3 and len(shared) >= 2):
        return True
    return inter / min(len(x), len(y)) >= 0.4 and (bool(shared) or j >= 0.2)


def _ts(source):
    try:
        return datetime.fromisoformat(str(source.get('published_at')).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def dedupe(sources, *, hours=6, recent=()):
    """(kept, dropped). One representative per event within `hours`; the longest text wins and lists the
    others in also_reported_by. `recent` = [{'text','published_at','id'}] already extracted in an earlier
    run: a flash matching one of them is dropped (reason 'seen_earlier')."""
    window = timedelta(hours=hours)
    kept, dropped = [], []
    for s in sorted(sources, key=lambda s: -len(s['original_text'])):
        ts = _ts(s)
        earlier = next((r for r in recent if similar(s['original_text'], r.get('text'))
                        and (ts is None or _ts(r) is None or abs(ts - _ts(r)) <= window)), None)
        if earlier:
            dropped.append({'id': s['id'], 'source_id': s['source_id'], 'reason': 'seen_earlier', 'match': earlier.get('id')})
            continue
        rep = next((k for k in kept if similar(s['original_text'], k['original_text'])
                    and (ts is None or _ts(k) is None or abs(ts - _ts(k)) <= window)), None)
        if rep:
            rep['also_reported_by'].append({'source_id': s['source_id'], 'id': s['id'], 'url': s.get('url'),
                                            'publisher': s.get('publisher')})
            dropped.append({'id': s['id'], 'source_id': s['source_id'], 'reason': 'duplicate', 'match': rep['id']})
            continue
        kept.append(s)
    kept.sort(key=lambda s: _ts(s) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return kept, dropped


# ---------- ordering ----------

TOPIC = re.compile(
    r'美联储|联储|央行|利率|降息|加息|通胀|CPI|PPI|PMI|GDP|非农|就业|失业|国债|美债|收益率|汇率|人民币|美元|关税|财政|'
    r'社融|信贷|降准|LPR|逆回购|芯片|半导体|AI|人工智能|算力|英伟达|台积电|存储|HBM|DRAM|数据中心|资本开支|光模块|'
    r'比特币|加密|稳定币|以太坊|ETF|期权|VIX|美股|纳指|标普|道指|A股|港股|恒指|原油|黄金|OPEC|欧洲央行|日本央行|英国央行|'
    r'财报|营收|指引|并购|融资|IPO|特朗普|白宫|国务院|证监会|发改委', re.I)


def relevance(source):
    text = source['original_text']
    return len(set(m.group().lower() for m in TOPIC.finditer(text))) + (1 if re.search(r'\d', text) else 0) \
        + int(source.get('flash_score') or 1) - 1 + len(source.get('also_reported_by') or [])


def order(sources):
    """Most relevant first (topic hits, numbers, outlet score, cross-outlet echo), then newest."""
    return sorted(sources, key=lambda s: (-relevance(s), -(_ts(s) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()))
