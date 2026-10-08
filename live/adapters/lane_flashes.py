"""Crypto news-flash feeds filtered to the niche lanes (Oct 8 evening, PM_PLAN item 4: 快讯 channel).

Public RSS of crypto flash desks (no login, no key, honest UA; licence tier B, facts only, paraphrase with
attribution, no reproduction). Only items with a niche-lane word (live/lane_fit.py: memecoin / airdrop / prediction
market / stablecoin yield / perp / Solana-Base) are kept; each becomes one short flash source whose source_id is the
lane's routed id (lane_flash_<lane>, live/source_registry.json route_accounts), credited to the outlet. The batched
cheap flash EXTRACT (live/flash_extract.py) turns them into units inside their own ring fence (live/lane_sources.py).
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from live.adapters import common
from live.distillation_source import digest

OUTLETS = {
    'crypto_odaily_flash': {'publisher': 'Odaily 星球日报', 'url': 'https://rss.odaily.news/rss/newsflash', 'lang': 'zh'},
    'crypto_panews_flash': {'publisher': 'PANews', 'url': 'https://www.panewslab.com/rss.xml?lang=zh&type=NEWS', 'lang': 'zh'},
    'crypto_chaincatcher': {'publisher': 'ChainCatcher 链捕手', 'url': 'https://www.chaincatcher.com/rss/clist', 'lang': 'zh'},
    'ch123_www_techflowpost_com': {'publisher': '深潮 TechFlow', 'url': 'https://www.techflowpost.com/rss.aspx', 'lang': 'zh'},
    'crypto_theblock_news': {'publisher': 'The Block', 'url': 'https://www.theblock.co/rss.xml', 'lang': 'en'},
    'crypto_decrypt': {'publisher': 'Decrypt', 'url': 'https://decrypt.co/feed', 'lang': 'en'},
}
# most specific lane first: perp words (liquidation / 合约) are the broadest, so perp is tried last
LANES = ('crypto_prediction', 'crypto_airdrop', 'crypto_meme', 'crypto_stable_yield', 'crypto_ecosystem_sol_base',
         'crypto_perp')
SOURCE_ID = {lane: 'lane_flash_' + lane.replace('crypto_', '').replace('ecosystem_', '') for lane in LANES}
MAX_CHARS = 600
MIN_CHARS = 20
_PROMO = re.compile(r'下载|扫码|开户|直播间|广告|会员|VIP|付费|sponsored|partner content|press release|giveaway|'
                    r'合约地址|\bCA\s*[:：]|0x[0-9a-fA-F]{8,}|[1-9A-HJ-NP-Za-km-z]{32,44}pump\b', re.I)


def _ts(text):
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_rss(body):
    """[{'title', 'text', 'link', 'published'}] from an RSS 2.0 body (bad XML -> [])."""
    try:
        root = ET.fromstring(body.encode('utf-8') if isinstance(body, str) else body)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter('item'):
        title = ' '.join((it.findtext('title') or '').split())
        desc = common.html_text(it.findtext('description') or '')
        out.append({'title': title, 'text': ' '.join(desc.split()), 'link': (it.findtext('link') or '').strip(),
                    'published': _ts(it.findtext('pubDate') or '')})
    return out


# Flash classification is stricter than lane_fit.LANE_RX (智能合约 is not a perp, 押注银行 is not a prediction market,
# a gold / oil tick with 杠杆 in it is not a perp story); lane_fit still re-checks every packet at selection.
STRICT = {
    'crypto_prediction': re.compile(r'polymarket|kalshi|prediction markets?|预测市场', re.I),
    'crypto_airdrop': re.compile(r'airdrops?|空投|\btge\b|代币生成事件|撸毛|测试网|testnets?|女巫|sybil|快照|snapshot|'
                                 r'积分(?:计划|活动|赛季|系统|奖励)|points? (?:program|season|campaign|system)|'
                                 r'season ?[1-9] (?:points|rewards|airdrop)', re.I),
    # lane words only: a single coin name (DOGE in a list of shorted majors) is not a memecoin story
    'crypto_meme': re.compile(r'memecoins?|meme ?coins?|meme ?币|迷因|土狗|金狗|冲狗|pump\.?fun|four\.meme|letsbonk|bonk\.fun|'
                              r'发射台|launchpads?|\bmemes?\b|打狗|内盘|外盘', re.I),
    'crypto_stable_yield': None,   # lane_fit.LANE_RX (stablecoin word next to a yield word)
    'crypto_ecosystem_sol_base': None,   # beat_rules.LANE_REQUIRES (Solana / Base by name)
    'crypto_perp': re.compile(r'永续|\bperps?\b|perpetuals?|资金费率|funding rates?|持仓量|open interest|爆仓|liquidat\w*|'
                              r'hyperliquid|\baster\b|\blighter\b|\bdydx\b|多空比|\d+ ?倍杠杆|杠杆做[多空]|'
                              r'leveraged? (?:longs?|shorts?)|(?:longs?|shorts?) (?:liquidated|squeezed)', re.I),
}
SKIP_TITLE = re.compile(r'^Catcher Predict|胜率暴(?:跌|涨)|\bvs\.? |对阵|比赛胜者|冠军赛', re.I)


def _rx(lane):
    from live import lane_fit
    from live.beat_rules import LANE_REQUIRES
    if STRICT[lane] is not None:
        return STRICT[lane]
    return LANE_REQUIRES[lane] if lane == 'crypto_ecosystem_sol_base' else lane_fit.LANE_RX[lane]


def classify(text):
    """(lane, hits) of the first niche lane the text is on (crypto word required), else (None, [])."""
    from live.beat_rules import CRYPTO_WORDS, LANE_SELF
    if SKIP_TITLE.search(text[:80]):
        return None, []
    for lane in LANES:
        hits = sorted({m.group(0).lower() for m in _rx(lane).finditer(text)})
        if not hits:
            continue
        if CRYPTO_WORDS.search(text) or (lane in LANE_SELF and LANE_SELF[lane].search(text)) or lane == 'crypto_meme':
            return lane, hits
    return None, []


def to_source(cid, item, lane):
    spec = OUTLETS[cid]
    title, text = item['title'], item['text']
    body = title if not text or text.startswith(title[:20]) else f'{title}\n\n{text}'
    body = body[:MAX_CHARS].rsplit(' ', 1)[0] if len(body) > MAX_CHARS and spec['lang'] == 'en' else body[:MAX_CHARS]
    key = hashlib.sha1((item.get('link') or title).encode()).hexdigest()[:16]
    return {'id': f'lf-{cid}-{key}', 'source_id': SOURCE_ID[lane], 'source_hash': digest(body), 'original_text': body,
            'author_name': spec['publisher'], 'publisher': spec['publisher'], 'title': title[:120], 'url': item.get('link') or '',
            'published_at': item['published'].astimezone(timezone.utc).isoformat(), 'source_language': spec['lang'],
            'source_version': 'lane-flash-v1', 'adapter': 'lane_flash:' + cid, 'truncated': len(body) >= MAX_CHARS,
            'no_reproduction': True, 'original_outlet': None, 'flash_score': 1, 'also_reported_by': [],
            'outlet_id': cid, 'lane': lane}


def fetch(cid, *, since=None, now=None, transport=None):
    """{'status', 'sources', 'items', 'off_lane'} for one outlet: in-window, non-promo, on-lane items only."""
    spec = OUTLETS[cid]
    st, body = common.http_get(spec['url'], transport=transport, timeout=30)
    if st != 200:
        return {'status': f'http_{st}', 'sources': [], 'items': 0, 'off_lane': 0}
    now = now or datetime.now(timezone.utc)
    items = parse_rss(body)
    out, off = [], 0
    for it in items:
        ts = it['published']
        if ts is None or ts > now + timedelta(hours=1) or (since and ts < since):
            continue
        full = f"{it['title']} {it['text']}"
        if len(full) < MIN_CHARS or _PROMO.search(full):
            continue
        lane, _ = classify(full)
        if not lane:
            off += 1
            continue
        out.append(to_source(cid, it, lane))
    return {'status': 'ok' if out else 'no_lane_items', 'sources': out, 'items': len(items), 'off_lane': off}
