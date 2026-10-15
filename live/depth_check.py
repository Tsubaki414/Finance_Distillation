"""Analysis depth (Oct 13, Fiona). FD_DEPTH_CHECK=0 disables both parts (default on).

Prompt (Fiona clarification): depth comes from the SOURCE's own analysis (reasoning, comparisons, implications),
kept and credited by the attribution frame, translate-and-light-edit; the model never invents insights.
Post-check (no model call): a news / original draft whose body carries none of those moves is a pure relay and is
HELD (needs_review, hold_reason 'depth: ...'). Archive / 回看 rows (their then-vs-now is the comparison) are exempt.
Deterministic marker lists, deliberately broad: it catches bare relays, not weak analysis."""
from __future__ import annotations

import os
import re

CODE = 'depth'
PROMPT = ('Depth (HARD): carry at least one of the SOURCE\'s own insights from the units - its reasoning, its '
          'comparison to a prior event, who it says is affected, or what it says to watch - translated and lightly '
          'edited, not just the headline. Never invent an insight, figure, date or precedent the units lack; if the '
          'units hold only a headline, say only what they support.')


def is_headline_source(pick):
    """Flash / headline-only sources (7x24 flashes, lane flashes): ranked after analysis sources."""
    sid = str(pick.get('source_id') or '')
    return sid.startswith(('lf-', 'flash', 'fl-')) or 'flash' in sid.lower()[:20]


MARKERS = {
    'en': re.compile(r"\b(?:last time|previous(?:ly)?|prior|compared|versus|vs\.?|unlike|like in|since|again|"
                     r"watch|next|until|unless|if\b|once\b|when\b|depends|the test|the tell|key level|"
                     r"means|for (?:holders|traders|borrowers|lenders|users|savers|investors|LPs|miners|issuers)|"
                     r"who (?:pays|wins|loses|gets)|squeez|pressure on|exposed|at risk|hurts?|benefits?)\b", re.I),
    'zh': re.compile(r'上次|此前|之前|以往|历史上|相比|对比|同比|环比|不同于|和.{0,8}一样|又一次|再次|'
                     r'关注|盯着|接下来|下一步|如果|一旦|除非|取决于|关键在|意味着|对.{0,12}(?:来说|而言)|'
                     r'受影响|受益|承压|吃亏|买单|风险在|压力'),
}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_DEPTH_CHECK', '1') != '0'


def prompt_rule(env=None):
    return ('\n' + PROMPT) if enabled(env) else ''


# Oct 13 09:21 (Fiona): a reaction / question / life-feel post passes when it carries at least one ATTRIBUTABLE source
# insight (a causal / implication sentence that overlaps the source text) plus a genuine reaction; a pure headline
# relay (no insight, or no reaction) is still held.
REACTION = {
    'en': re.compile(r"\?|\b(?:watching|wary|hesitant|hesitat\w*|unsure|not sure|surpris\w*|wild|welp|bruh|lol|"
                     r"can't believe|curious|wonder\w*|nervous|uneasy|feels?|honestly|wow|ouch|yikes|ugh|"
                     r"stayed up|staying up|refresh\w*)\b", re.I),
    'zh': re.compile(r'[?？]|绷不住|麻了|无语|惊了|笑死|犹豫|还在看|盯盘|熬夜|看不懂|有点悬|心里没底|慌|吓|离谱|太荒谬|'
                     r'怎么看|你们|说实话|服了|唉|哎|真挺|有点|难受|爽'),
}
INSIGHT = {
    'en': re.compile(r"\b(?:because|since|so\b|which|implies|implying|means|meaning|signals?|suggests?|shows?|"
                     r"driven by|thanks to|due to|as a result|reflects?|why|while|despite|even as|decoupl\w*)\b", re.I),
    'zh': re.compile(r'因为|所以|导致|引发|原因|说明|意味着|反映|看出|带崩|拖累|推动|靠|由于|于是|结果|背后|脱钩|分化'),
}


def _toks(text):
    words = {w.lower() for w in re.findall(r'[A-Za-z][A-Za-z0-9$%.-]{2,}|\d[\d.,%]*', text or '')}
    cjk = re.sub(r'[^\u4e00-\u9fff]', '', text or '')
    return words | {cjk[i:i + 2] for i in range(len(cjk) - 1)}


def attributable_insight(body, lang, source_text=None):
    """A sentence with a causal / implication move that shares >= 2 tokens with the source (any such sentence when
    no source text is given)."""
    rx = INSIGHT['zh' if str(lang)[:2] == 'zh' else 'en']
    src = _toks(source_text) if source_text else None
    for s in re.split(r'(?<=[。！？!?.])\s+|\n+', body or ''):
        if s.strip() and rx.search(s) and (src is None or len(_toks(s) & src) >= 2):
            return s.strip()
    return None


# Oct 15 (FD_DEPTH_HOLD_CAL, default on; =0 is the exact Oct 13 behaviour): ~20 of 10-15's held drafts were
# data_take / judgment_take posts with post_kind None (the reaction-kind exemption never applies), a source figure and
# an own take line ("I think this'll break … retest", "并没有改变主线", "looks nice on paper") that neither MARKERS nor
# INSIGHT list, while the attributable-insight overlap needs >= 2 tokens of an often title-only source. A take post
# now also passes when ALL hold: (1) a concrete figure (number / level / %, dates and list markers ignored) that the
# units or source text carry; (2) a judgment line (stance / forecast / evaluation token below) in (3) a body of >= 2
# sentences, the judgment sentence not a copy of the source (< 70% of its tokens in the source / units). A headline
# or flash relay (one sentence, or facts only, or the source's own sentence restated, or a reported-speech claim
# "X says / 表示 …") is still held.
TAKE_KINDS = ('data_take', 'judgment_take', 'contrarian_take', 'view_relay', 'earnings_take', 'insight', 'reaction')
JUDGE = {
    'en': re.compile(r"\b(?:I think|I'd (?:say|argue|bet)|I suspect|I doubt|I'm (?:skeptical|not convinced)|my (?:read|take|bet)|"
                     r"to me|looks? (?:like|nice|cheap|expensive|fragile|weak|strong|stretched|overdone)|on paper|"
                     r"likely|unlikely|probably|eventually|will (?:retest|break|hold|stay|struggle|fade|bounce|follow|"
                     r"need)|won't|wouldn't|isn't|aren't|doesn't|don't|no longer|not (?:enough|stalling|holding|the|a|just)|"
                     r"keeps? (?:stepping|buying|selling|draining|bleeding)|stepping in|holding back|leaves? the door|"
                     r"before anyone|baseline|the real|what matters|bullish|bearish|fragile|reckless|overdone|overpriced|"
                     r"contained|shatter\w*|draining|pretend\w*|absorb\w*|exposes?|proves?|usually follows|"
                     r"hold the bag|the point)\b", re.I),
    'zh': re.compile(r'我觉得|我看|在我看来|感觉|估计|大概率|恐怕|看来|显然|挺明显|并没有|没有改变|不会|难以|很难|还得看|得看|'
                     r'才是|更重要|说白了|本质上|无非|值得|小心|警惕|当傻子|太难看|挺悬|靠不住|水分|比想象|过热|撑不住|'
                     r'扛不住|接不住|不等于|割韭菜|老鼠仓'),
}
# a reported-speech sentence relays the source's (or an official's) claim - never the post's own judgment line
REPORTED = {
    'en': re.compile(r"\b(?:says?|said|notes?|noted|reports?|reported|according to|told|warns?|warned|claims?|claimed|"
                     r"argues?|argued|expects?|expected|announced|stated|per)\b", re.I),
    'zh': re.compile(r'表示|(?<![名对])称|(?<!小)说(?!白了)|认为|指出|(?<!数)据|报道|透露|预计|预期|警告|宣布|发布|公布|强调|提到'),
}
_DATE = re.compile(r'\b(?:19|20)\d\d[-/]\d{1,2}[-/]\d{1,2}\b|(?:19|20)\d\d\s*年|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|'
                   r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?|'
                   r'\b(?:19|20)\d\d\b|^\s*\d{1,2}\s*[.、)]', re.I | re.M)


def cal_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_DEPTH_HOLD_CAL', '1') != '0'


def units_text(units):
    """Statements, exact source spans and number texts of compose units (any missing field is skipped)."""
    out = []
    for u in units or []:
        if not isinstance(u, dict):
            continue
        out.append(str(u.get('statement') or ''))
        out += [str(s.get('exact_text') or '') if isinstance(s, dict) else str(s) for s in u.get('source_spans') or []]
        out += [str(n.get('text') or '') if isinstance(n, dict) else str(n) for n in u.get('numbers') or []]
    return ' '.join(x for x in out if x).strip() or None


def _figures(text):
    return {n.replace(',', '').rstrip('.') for n in re.findall(r'\d[\d,]*(?:\.\d+)?', _DATE.sub(' ', text or ''))}


def _sentences(body):
    return [s.strip() for s in re.split(r'(?<=[。！？!?])|(?<=\.)\s+|\n+', body or '') if s and s.strip()]


def grounded_take(body, lang, ground_text=None):
    """The judgment sentence when the body carries a grounded figure + an own judgment line (see FD_DEPTH_HOLD_CAL);
    None otherwise. ground_text: source text + units text (None = no grounding text: never passes)."""
    if not ground_text:
        return None
    figs = _figures(body) & _figures(ground_text)
    if not figs:
        return None
    sents = _sentences(body)
    if len(sents) < 2:
        return None
    lg = 'zh' if str(lang)[:2] == 'zh' else 'en'
    rx, src = JUDGE[lg], _toks(ground_text)
    for s in sents:
        if rx.search(s) and not REPORTED[lg].search(s):
            t = _toks(s)
            if t and len(t & src) / len(t) < 0.7:
                return s
    return None


def findings(body, lang, post_kind=None, env=None, source_text=None, post_type=None, units=None):
    """[] when the body shows depth (or check off / archive row); else one finding dict."""
    if not enabled(env) or not (body or '').strip():
        return []
    if post_kind in ('archive_lookback', 'anniversary') or re.match(r'^\s*(?:回看|Look back)', body, re.I):
        return []
    lg = 'zh' if str(lang)[:2] == 'zh' else 'en'
    if MARKERS[lg].search(body):
        return []
    reaction = REACTION[lg].search(body)
    if reaction and (post_kind in ('reaction', 'question', 'diary', 'meme', 'industry_people')
                     or attributable_insight(body, lg, source_text)):
        return []
    if cal_enabled(env) and (post_type in TAKE_KINDS or post_kind in TAKE_KINDS):
        ground = ' '.join(x for x in (source_text, units_text(units)) if x).strip() or None
        if grounded_take(body, lg, ground):
            return []
    return [{'code': CODE, 'severity': 'hard', 'level': 'hard',
             'detail': 'pure news relay: no attributable source insight + reaction, comparison, affected party or '
                       'what-to-watch beyond the source'}]
