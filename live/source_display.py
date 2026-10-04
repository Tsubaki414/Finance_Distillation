"""Source display-name + licence gate (runs before compose).

Every name a post credits comes from here: a clean professional publisher name in the
post's language, or a generic credit where the policy says the originator is not named.

- Licence: only tiers A/B may be credited/composed (C/D/unknown -> gate fails).
- Names: live/source_display.json overrides first, then an automatic clean-up of the
  registry name (channel descriptors and parentheticals dropped). EN posts need a name
  with Latin letters; a pure-Chinese name without an English override fails the gate.
- Sell-side research that arrives via ReportGem: credit policy `sell_side_credit`
  ('generic' -> "sell-side research" / "券商研报", the bank and analyst are not named;
  'bank' -> the bank's name). ReportGem itself is never named either way.
- never_name: names (D-tier distributors plus, under the generic policy, the bank's
  aliases) that must not appear anywhere in the post.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

FILE = Path(__file__).with_name('source_display.json')
CJK = re.compile(r'[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]')
PAREN = re.compile(r'\s*[（(][^（）()]*[）)]')
DESCRIPTORS = re.compile(
    r'\s*(?:免费内容|免费版|数据发布|资讯流|研报中心|新闻中心|新闻稿|新闻|播客|电话会全文|市场展望|研究|最新公告|演讲|'
    r'\bRSS\b|\bJSON\b|\bfeed\b|\bblog\b|\bAPI\b)\s*', re.I)


def config():
    return json.loads(FILE.read_text())


def is_sell_side(source):
    sid = str(source.get('source_id') or '')
    return sid.startswith('reportgem_') or source.get('adapter') == 'reportgem'


def _clean(name):
    name = PAREN.sub('', name or '')
    name = DESCRIPTORS.sub(' ', name)
    name = re.sub(r'\s*(?:/|\+|·)\s*$', '', re.sub(r'\s+', ' ', name)).strip(' -|·/+')
    return name


def _latin(name):
    cleaned = re.sub(r'\s+', ' ', CJK.sub(' ', name or '')).strip(' -|·/+')
    return cleaned if re.search(r'[A-Za-z]', cleaned) else ''


def _chinese(name):
    """A ZH credit keeps the Chinese name when the mixed name has one ('吴说 Wu Blockchain' -> keeps both)."""
    return name


def display(source, lang, *, tier=None, raw_name=None, check_licence=True):
    """Return {'ok', 'name', 'policy', 'never_name', 'reason'} for crediting `source` in `lang`."""
    from live import registry
    from live.qa_levels import D_TIER_NAMES
    cfg = config()
    sid = source.get('source_id')
    tier = tier if tier is not None else registry.source_licence_tier(sid)
    never = [*D_TIER_NAMES, *cfg.get('never_name', [])]
    out = {'ok': False, 'name': '', 'policy': 'name', 'never_name': never, 'reason': ''}
    if check_licence and tier not in ('A', 'B'):
        out['reason'] = f'licence tier {tier!r} is not creditable (A/B only)'
        return out
    lang = 'en' if lang == 'en' else 'zh'
    if is_sell_side(source) and cfg.get('sell_side_credit', 'generic') == 'generic':
        from live.attribution_frame import aliases
        out.update(ok=True, name=cfg['generic']['sell_side'][lang], policy='generic_sell_side')
        bank = source.get('publisher') or ''
        out['never_name'] = never + [n for n in [bank, *aliases(sid)] if n]
        return out
    override = (cfg.get('sources') or {}).get(sid) or {}
    name = override.get(lang)
    if not name and sid == 'sec_edgar':   # filer names from EDGAR metadata ('Amazon Com', 'Oracle Corp')
        filer = re.sub(r'[\s,]+(?:Com|Inc|Corp|Corporation|Co|Ltd|Plc|Holdings|N\.?V\.?)\.?$', '', (raw_name or source.get('publisher') or '').strip(), flags=re.I)
        name = (f'{filer} filing' if lang == 'en' else f'{filer} 公告') if filer else ''
    if not name:
        cleaned = _clean(raw_name if raw_name is not None else source.get('publisher') or '')
        name = _latin(cleaned) if lang == 'en' else _chinese(cleaned)
    if not name:
        out['reason'] = f'no {"English" if lang == "en" else "display"} name for {sid}'
        return out
    if lang == 'en' and CJK.search(name):
        out['reason'] = f'English post would credit a non-English name: {name}'
        return out
    if any(n.casefold() in name.casefold() for n in never if n):
        out['reason'] = f'display name hits the never-name list: {name}'
        return out
    out.update(ok=True, name=name)
    return out


def never_name_findings(text, never):
    low = (text or '').casefold()
    hits = sorted({n for n in never if n and n.casefold() in low})
    return [{'paragraph_id': None, 'stage': 'post', 'code': 'never_name_in_post',
             'detail': 'Never-name source in post: ' + ', '.join(hits)}] if hits else []
