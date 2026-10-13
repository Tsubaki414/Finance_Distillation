"""Oct 13 (Fiona): archive / 回看 / evergreen drafts in the ACCOUNT'S OWN VOICE (FD_ARCHIVE_VOICE, default on; 0 = off).

10-13: crypto_macro_zh (and 5 other accounts) had drafts like
  "回看｜2025年10月\\n\\n@dapangdun 在当时评价 BTC 大势，认为“依然不明朗，不是很乐观”。……这一跌幅印证了当时的谨慎态度"
i.e. a date header, a donor's @handle, a quoted past view, a mechanical number list and a robotic closer. An archive
post now reads as the account's own present-tense take on a then-vs-now move ("BTC 去年10月还在10.7万，现在8.2万……"
+ a genuine reaction). Rules (compose_prevent.py style: cheap regex checks right after generation):

  - no header line: no 回看｜ / 回看| / Look back: / Looking back | / a bare month-year line
  - no @handle, never names another account / donor, no quoted past view, no "X said / 认为 / 提到 / 写道"
  - no invented biography: never "我当时说 / 我早就说 / I said back then / I called it"
  - no robotic phrasing (印证了 / 跌幅达 / a decline of / this data simply highlights), no 不是X而是Y,
    no NFA on commentary, at most 3 figures (dates excluded)

findings() -> [{'code', 'level': 'hard', 'detail'}]; strip() is the deterministic repair (header line and @handles
removed); anything still failing goes to the one model rewrite in archive_lookback.compose(), then HOLD.
"""
from __future__ import annotations

import os
import re

from live import compose_prevent as cp

HEADER = re.compile(
    r'^\s*(?:回看|回顾|复盘|Look(?:ing)?\s*back|Throwback|Flashback)\s*(?:[｜|:：·\-—]|$)'
    r'|^\s*(?:(?:19|20)\d\d\s*年\s*\d{1,2}\s*月|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(?:19|20)\d\d)'
    r'\s*[.。:：｜|]?\s*$', re.I)
HANDLE = re.compile(r'(?<![\w.])@[A-Za-z0-9_]{2,15}\b')
QUOTE = re.compile(r'[“"「『]([^”"」』\n]{2,})[”"」』]')
ATTRIB = {
    'zh': re.compile(r'(?:有人|某人|博主|大V|网友|朋友|他|她|对方|作者)[^。！？\n]{0,12}(?:说过|说|认为|提到|写道|发文|表示|评价|指出|判断|观点)'
                     r'|(?:评价|认为|提到|写道|发文写道|表示)[^。！？\n]{0,4}[“「"]'),
    'en': re.compile(r'\b(?:he|she|they|someone|one trader|an analyst|a friend)\s+(?:said|wrote|posted|argued|claimed|thought|suggested|called)\b'
                     r'|\b(?:said|wrote|posted|argued|suggested|claimed)\s*[:,]?\s*["“]'
                     r'|@[A-Za-z0-9_]+\s+(?:said|wrote|posted|argued|suggested|claimed|thought|called)\b', re.I),
}
BIOGRAPHY = {
    'zh': re.compile(r'我(?:当时|那时|去年|早就|早)(?:就)?(?:说|讲|提醒|判断|预测|预判|看空|看多|喊)|(?:我|本人)(?:之前|曾经)(?:说过|讲过|提醒过|预测过)|正如我(?:当时|之前)?(?:所)?说'),
    'en': re.compile(r"\b(?:I|we)\s+(?:said|called|warned|predicted|told you|flagged|wrote)\b[^.!?\n]{0,40}\b(?:back then|last year|at the time|then|before)\b"
                     r"|\bas I (?:said|wrote|warned|predicted)\b|\bI called it\b|\btold you so\b", re.I),
}
ROBOTIC = {
    'zh': re.compile(r'印证了|验证了当时|这一跌幅|这一涨幅|跌幅达|涨幅达|期间(?:微)?[跌涨]|截至今日|截至今天|数据表明|数据显示，|这组数据|值得注意的是|综上'),
    'en': re.compile(r'\b(?:a (?:decline|drop|gain|rise) of \d|this data (?:simply )?(?:highlights|shows)|as of (?:today, )?\w+ \d{1,2}, 20\d\d|'
                     r'validat(?:es|ed) the (?:cautious|bullish|bearish)|it is worth noting|in conclusion)', re.I),
}
_DATE_NUM = re.compile(r'(?:19|20)\d\d\s*年?|\d{1,2}\s*[月日号]|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b', re.I)
MAX_FIGURES = 3

PROMPT_RULE = (
    'VOICE (HARD, archive posts): write it as the account\'s OWN present-tense take, e.g. '
    '"BTC 去年10月还在10.7万，现在8.2万。……" followed by a genuine human reaction (what it feels like, what you are '
    'watching now). NO header or date line (no "回看｜…", "Look back: …", "Feb 2025."). NEVER @-mention or name any '
    'other account, author or donor, and never quote or paraphrase anyone else\'s past view ("X 认为…", "X said…"). '
    'No invented biography: the account never claims it said, predicted or warned anything in the past ("我当时就说", '
    '"I called it", "as I said"). Keep 2-3 figures at most, woven into sentences (no number list, no "跌幅达23.4%"), '
    'no robotic closers ("这一跌幅印证了…", "This data simply highlights…"), no 不是X而是Y / "not X but Y", no '
    'NFA / 不构成投资建议.')


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_ARCHIVE_VOICE', '1') != '0'


def figures(body):
    """Figures of the body other than dates / years (one per number token)."""
    clean = _DATE_NUM.sub(' ', body or '')
    return [m.group(0).strip() for m in cp._NUM.finditer(clean) if re.search(r'\d', m.group(0))]


def findings(body, lang, strategy=False):
    lg = cp._lang(lang)
    body = body or ''
    out = []
    lines = [l for l in body.strip().splitlines() if l.strip()]
    if lines and HEADER.search(lines[0]):
        out.append({'code': 'archive_header', 'detail': lines[0][:60]})
    hs = sorted(set(HANDLE.findall(body)))
    if hs:
        out.append({'code': 'archive_handle', 'detail': hs[:5]})
    qs = [q for q in QUOTE.findall(body)]
    if qs:
        out.append({'code': 'archive_quoted_view', 'detail': qs[:3]})
    for k, rx in (('archive_attribution', ATTRIB), ('archive_invented_biography', BIOGRAPHY), ('archive_robotic', ROBOTIC)):
        hits = [m.group(0) for r in {rx[lg], rx['en']} for m in r.finditer(body)]
        if hits:
            out.append({'code': k, 'detail': hits[:3]})
    if cp._NOT_BUT[lg].search(body) or cp._NOT_BUT['en'].search(body):
        out.append({'code': 'archive_not_x_but_y', 'detail': (cp._NOT_BUT[lg].search(body) or cp._NOT_BUT['en'].search(body)).group(0)})
    if not strategy and cp._NFA.search(body):
        out.append({'code': 'archive_disclaimer', 'detail': cp._NFA.search(body).group(0)})
    figs = figures(body)
    if len(figs) > MAX_FIGURES:
        out.append({'code': 'archive_too_many_numbers', 'detail': figs})
    return [{**f, 'level': 'hard'} for f in out]


CODES = ('archive_header', 'archive_handle', 'archive_quoted_view', 'archive_attribution', 'archive_invented_biography',
         'archive_robotic', 'archive_not_x_but_y', 'archive_disclaimer', 'archive_too_many_numbers')

FIXES = {
    'archive_header': 'Delete the header / date line; open straight with the take.',
    'archive_handle': 'Remove every @handle and never name the other account; the view is the account\'s own.',
    'archive_quoted_view': 'No quotation of anyone\'s past view; say it in the account\'s own words as a present take.',
    'archive_attribution': 'Do not attribute the view to anyone ("X 认为 / X said"); write it as the account\'s own take.',
    'archive_invented_biography': 'Never claim the account said / predicted / warned anything in the past.',
    'archive_robotic': 'Drop the robotic phrasing (印证了 / 跌幅达 / "a decline of" / "this data highlights"); react like a person.',
    'archive_not_x_but_y': 'No "not X but Y" / 不是X而是Y construction.',
    'archive_disclaimer': 'Delete the NFA / 不构成投资建议 line.',
    'archive_too_many_numbers': 'Keep 2-3 figures at most (then price, now price, maybe the move), woven into sentences.',
}


_HEAD_PREFIX = re.compile(
    r'^\s*(?:(?:回看|回顾|复盘|Look(?:ing)?\s*back|Throwback|Flashback)\s*[｜|:：·\-—]?\s*)?'
    r'(?:(?:19|20)\d\d\s*年\s*\d{1,2}\s*月|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(?:19|20)\d\d)?'
    r'\s*[.。:：｜|，,]?\s*', re.I)


def strip(body):
    """Deterministic repair: drop the header (a whole header line, or a header prefix of the first line) and every
    @handle. Attribution / quotes left behind are for the model rewrite."""
    lines = (body or '').strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and HEADER.search(lines[0]):
        rest = _HEAD_PREFIX.sub('', lines[0], count=1).strip()
        lines[0:1] = [rest] if rest else []
    out = '\n'.join(lines)
    out = HANDLE.sub('', out)
    out = re.sub(r'[ \t]{2,}', ' ', out)
    return re.sub(r'\n{3,}', '\n\n', out).strip()
