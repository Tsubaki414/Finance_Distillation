"""Hook + voice checks (Oct 8 evening; views diagnosis: no hooks, no first-hand angle; quality skim: an airdrop draft
stated a source's $100k BTC call as the account's own view and a stale 'new high').

FD_HOOK_VOICE (default 1; tests/conftest.py turns it off for the scripted legacy compose tests):
  weak_hook               SOFT, but triggers compose's one targeted rewrite: line 1 opens generically ("最近市场…",
                          "Let's talk about…") or carries no concrete number / named fact / first-person observation.
                          Never a HOLD on its own.
  unattributed_forecast   HARD: a price-target / forecast number taken from the source is written as the account's
                          own call (no "X says / 据X / X 认为 / their call" in that sentence or the one before).
  stale_market_claim      HARD: a "new high / record / ATH / 新高" market-state claim when the source is older than
                          STALE_DAYS at post time, or the latest price in the pipeline (charts fetchers, FD_STALE_PRICE=1
                          in daily compose) sits more than OFF_HIGH below the recent high.
HARD findings get the usual one targeted rewrite and then HOLD (needs_review).

PROMPT_RULE goes into the compose payload (payload['hook_voice']) when enabled.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

VERSION = 'hook-voice-v2'   # v2: explicit weak opener list (Oct 9 hook1009)
STALE_DAYS = 3
OFF_HIGH = 0.05            # latest close more than 5% under the 60-day high = "new high" is contradicted
SOFT_CODES = frozenset({'weak_hook', 'opener_repeat'})
HARD_CODES = frozenset({'unattributed_forecast', 'stale_market_claim'})
REPAIR_TRIGGER = frozenset({'weak_hook', 'opener_repeat'})   # soft codes that still get the one targeted rewrite

# Oct 9: explicit weak openers — fire as weak_hook even when a number is present in the first line.
# ZH phrases that read like AI template / hedging / passive scroll (first-word match).
WEAK_OPENERS_ZH = (
    '我觉得', '我认为', '说实话', '老实说', '坦白说',
    '扫了眼', '扫了一眼', '刚才看了', '刚看了', '刚刚看到',
    '刷到', '看到一个', '今天看到', '注意到', '不得不说',
    '讲真', '有一说一',
)
# '其实' is only weak as the very first word (其实XX is an opener hedge; 其实... in the middle is fine).
_QISHI_FIRST = re.compile(r'^\W*其实')

# EN phrases — case-insensitive prefix match.
WEAK_OPENERS_EN = (
    'I think', 'Honestly,', 'To be honest', 'Just saw', 'Was looking at',
    'I noticed', 'Took a look', 'Scrolling', 'So I', 'Ngl',
)

_EXPLICIT_WEAK_ZH = re.compile(
    r'^\W*(?:' + '|'.join(re.escape(p) for p in WEAK_OPENERS_ZH) + r')', re.UNICODE)

# EN phrases may end in punctuation (e.g. 'Honestly,') so \b does not work reliably;
# require word boundary only for purely alphabetic endings, else require space-or-end.
def _build_en_weak_pattern():
    parts = []
    for phrase in WEAK_OPENERS_EN:
        escaped = re.escape(phrase)
        if phrase[-1].isalpha():
            parts.append(escaped + r'\b')
        else:
            parts.append(escaped + r'(?=\s|$)')
    return re.compile(r'^\W*(?:' + '|'.join(parts) + r')', re.I)

_EXPLICIT_WEAK_EN = _build_en_weak_pattern()

PROMPT_RULE = (
    'Hook and voice. Line 1 must carry a concrete number or named fact from the units, or a sharp first-person '
    'observation in the persona\'s own voice (what I noticed / logged / checked) - never a generic opener such as '
    '"Let\'s talk about", "Interesting times", "最近市场", "今天聊聊", "值得注意的是". Where the persona fits, write like '
    'someone keeping their own book: first person, what I am watching, what changed in my numbers. A forecast, price '
    'target or prediction that comes from a unit\'s speaker or the source is THEIR call: attribute it in the same '
    'sentence ("X expects...", "据X…", "X 认为…") and do not present it as your own view. Never call a level a '
    '"new high" / record / 新高 unless the units or reality lines show it is current as of the post time.')
FIXES = {
    'weak_hook': ('Rewrite line 1 only: open on the most concrete number or named fact in the units, or on a sharp '
                  'first-person observation (what I noticed / logged); no generic opener. Keep the rest.'),
    'unattributed_forecast': ('The forecast / price target named in the detail is the source\'s call, not the account\'s: '
                              'attribute it in the same sentence ("<speaker> expects...", "据<来源>…", "<来源> 认为…"), '
                              'or drop it. Do not write it as your own prediction.'),
    'stale_market_claim': ('Drop the "new high / record / 新高" claim or say when it happened (with the date): the source '
                           'is older than 3 days or the latest price no longer supports it.'),
}

GENERIC_EN = re.compile(
    r"^\W*(?:so,|well,|okay,|ok,|look,|alright,|here'?s the thing|here'?s why|let'?s (?:talk|dive|unpack|break)|"
    r"let me (?:explain|break)|in today'?s|in the world of|in the (?:ever-)?(?:changing|evolving)|"
    r"it'?s (?:been )?(?:an? )?(?:interesting|wild|crazy|big|busy) (?:day|week|time)|interesting (?:times|development|"
    r"to see)|quick (?:thought|take|note|reminder)|just (?:a )?(?:thought|reminder)|thoughts on|big news|"
    r"breaking[:!]|update[:!]|gm\b|another day|as we all know|it'?s worth (?:noting|mentioning)|notably,|"
    r"interestingly,|there'?s a lot (?:going on|of noise)|everyone(?: is|'s) talking|many (?:people|investors) (?:are|think)|"
    r"the (?:crypto )?market (?:is|has been) (?:showing|looking|moving)|markets? (?:are|is) (?:interesting|wild|crazy))",
    re.I)
GENERIC_ZH = re.compile(
    r'^\W*(?:最近|近期|近日|今天(?:来)?(?:聊聊|说说|简单说)|聊聊|说说|说一个|分享一个|大家好|各位|众所周知|'
    r'值得(?:注意|关注|一提)的是|有意思的是|不得不说|话说|随着|关于|市场(?:又|再次|最近|近期|现在)|币圈(?:又|最近)|'
    r'一个(?:有趣|值得)|今天(?:的)?(?:市场|行情)|行情(?:又|最近)|总的来说|简单来说)')
NUMBER = re.compile(r'\d|[一二三四五六七八九十两半百千万亿]+(?:成|倍|万|亿|个点|%)')
FIRST_PERSON_EN = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|my|me|mine|we|our)\b")
FIRST_PERSON_ZH = re.compile(r'我|咱|本人|自己')
GENERIC_ENTITIES = {'btc', 'bitcoin', 'crypto', 'eth', 'ethereum', 'market', 'markets', 'etf', 'etfs', 'ai', 'us',
                    'the', 'it', 'this', 'that', 'what', 'so', 'thank', 'bullish', 'bearish'}


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_HOOK_VOICE', '1') != '0'


def first_line(body):
    return next((ln.strip() for ln in str(body or '').splitlines() if ln.strip()), '')


def _explicit_weak_opener(first, lang):
    """Return the matched weak opener phrase if the first line opens with one of the listed phrases, else None.

    A first-person opener that is immediately followed by a concrete number / named fact in the same
    first clause is still weak when it matches one of the explicit WEAK_OPENERS lists — the rule is
    that those phrases read as AI template phrasing regardless of what follows.
    Exception: first-person openers that are NOT on the explicit list (e.g. '我记了一笔：ETH 费率…')
    are tested by hook_findings' existing number/entity path instead.
    """
    if lang == 'zh':
        m = _EXPLICIT_WEAK_ZH.search(first) or _QISHI_FIRST.search(first)
        if m:
            return m.group(0).strip()
    else:
        m = _EXPLICIT_WEAK_EN.search(first)
        if m:
            return m.group(0).strip()
    return None


def hook_findings(body, lang):
    """weak_hook when line 1 opens with an explicit weak phrase or is generic with no number/named fact/first person."""
    first = first_line(body)
    if not first:
        return []
    # Oct 9: explicit weak opener list always fires, even when a number follows in the same clause.
    explicit = _explicit_weak_opener(first, lang)
    if explicit:
        return [{'code': 'weak_hook', 'detail': f'line 1 opens with weak phrase: "{explicit}"'}]
    rx = GENERIC_ZH if lang == 'zh' else GENERIC_EN
    m = rx.search(first)
    if m:
        return [{'code': 'weak_hook', 'detail': f'line 1 opens generically: "{m.group(0).strip()}"'}]
    if NUMBER.search(first):
        return []
    if (FIRST_PERSON_ZH if lang == 'zh' else FIRST_PERSON_EN).search(first):
        return []
    from live.hotspot import entities
    if entities(first) - GENERIC_ENTITIES:
        return []
    # Latin names glued to CJK text (与Kraken的) are missed by hotspot.entities' word-boundary rule
    if lang == 'zh' and {w.lower() for w in re.findall(r'(?<![A-Za-z0-9@#$])([A-Z][A-Za-z0-9&.\-]{1,})', first)} - GENERIC_ENTITIES - {'i'}:
        return []
    if re.search(r'\$[A-Za-z]{2,10}\b', first):
        return []
    return [{'code': 'weak_hook', 'detail': 'line 1 has no concrete number, named fact or first-person observation'}]


# ------------------------------------------------------------------ forecasts

TARGET_EN = re.compile(
    r"(?:hit|hits|reach|reaches|reaching|top|tops|cross|crosses|crossing|break|breaks|breaking|see|sees|target|targets|"
    r"targeting|run to|rally to|rallies to|climb to|head(?:s|ing)? (?:to|toward|towards)|on (?:track|course) for|path to|"
    r"push(?:es)? (?:to|toward|past)|surge to|to)\s+(?:above\s+|past\s+|beyond\s+)?"
    r"(?:\$\s?\d[\d,.]*(?:\s?(?:[kKmMbB]|million|billion|trillion)(?![A-Za-z]))?|\d[\d,.]*\s?(?:[kK]\b|%))", re.I)
FUTURE_EN = re.compile(r"\b(?:will|could|would|likely|expected|expects?|on track|by (?:year[- ]end|the end of|end of|"
                       r"december|q[1-4]|20\d\d|next)|before (?:year[- ]end|the end of)|next (?:year|quarter|month)|"
                       r"target|forecast|predict|projection|path to|heading)\b", re.I)
TARGET_ZH = re.compile(r'(?:冲上|冲到|冲击|突破|站上|涨到|涨至|达到|看到|上看|摸到|迈向|剑指|目标价?|跌到|跌至|下看|回落到)'
                       r'\s*(?:\$\s?)?\d[\d,.]*\s*(?:万|千|亿|k|K)?\s*(?:美元|美金|刀|U|点|%)?')
FUTURE_ZH = re.compile(r'将|会|有望|大有希望|预计|预期|料将|目标|年底|年内|明年|今年底|下半年|圣诞|看到|上看|剑指|迈向|冲上')
ATTRIB_EN = re.compile(
    r"\baccording to\b|\b(?:says?|said|argues?|argued|expects?|expected by|predicts?|predicted|forecasts?|projects?|"
    r"sees|calls? for|thinks|believes?|wrote|writes|notes?|noted|claims?|reckons?|estimates?)\b|\bper\s+[A-Z@]|"
    r"\banalysts?\b|\bstrategists?\b|\bthe (?:report|note|desk|bank|firm|fund|team)\b|"
    r"\b(?:their|his|her)\s+(?:call|target|forecast|prediction|projection|view|model|base case|thesis)\b|"
    r"['’]s (?:call|target|forecast|prediction|projection|base case|model)|"
    r"\b(?:the|this|that)\s+(?:\w+\s+)?(?:call|target|forecast|prediction|projection)\b", re.I)
ATTRIB_ZH = re.compile(r'据|按照|在[^，。]{0,10}看来|认为|表示|称|指出|写道|报告|研报|分析师|机构|他们|他认为|她认为|他说|她说|观点|口中|眼里|'
                       r'喊出|给出的|的目标|的预测|的判断|的说法|这个(?:预测|判断|目标)|预测说|放话')
_SENT = re.compile(r'[^。！？!?\n]+[。！？!?]?|[^.!?\n]+(?:[.!?](?=\s|$))?')


def _sentences(body):
    out = []
    for line in str(body or '').splitlines():
        out += [s.strip() for s in re.split(r'(?<=[。！？!?])|(?<=\.)\s+', line) if s and s.strip()]
    return out


def _unit_texts(units, source=None):
    parts = []
    for u in units or ():
        u = u.get('unit', u) if isinstance(u, dict) else {}
        parts.append(str(u.get('statement') or ''))
        parts += [str(s.get('exact_text') or s) if isinstance(s, dict) else str(s) for s in u.get('source_spans') or ()]
        view = u.get('view') or {}
        parts += [str(view.get('subject') or '')] + [str(x) for x in view.get('reasoning') or ()]
    if source:
        parts.append(str(source.get('title') or ''))
    return ' '.join(parts)


def _speakers(units, source=None):
    names = set()
    for u in units or ():
        u = u.get('unit', u) if isinstance(u, dict) else {}
        sp = str(u.get('speaker') or '').strip()
        if sp and sp.lower() not in ('unknown', 'source', 'author'):
            names.add(sp)
    for k in ('publisher', 'author_name'):
        v = str((source or {}).get(k) or '').strip()
        if v:
            names.add(re.split(r'[（(]', v)[0].strip())
    out = set()
    for n in names:
        out.add(n.lower().lstrip('@'))
        out |= {w.lower() for w in re.findall(r'[A-Za-z][A-Za-z.&-]{2,}', n)}
    stop = {'the', 'and', 'news', 'rss', 'research', 'media', 'daily', 'times', 'post', 'group', 'capital', 'markets',
            'market', 'page', 'blog', 'report', 'weekly', 'inc', 'ltd', 'com', 'www'}
    return {n for n in out if len(n) >= 3 and n not in stop}


def forecast_findings(body, units, source=None, lang='en'):
    """unattributed_forecast: a forecast number the source holds, written without crediting its speaker."""
    from live.hotspot import numbers
    src_nums = numbers(_unit_texts(units, source))
    if not src_nums:
        return []
    speakers = _speakers(units, source)
    target, future, attrib = (TARGET_ZH, FUTURE_ZH, ATTRIB_ZH) if lang == 'zh' else (TARGET_EN, FUTURE_EN, ATTRIB_EN)
    sents = _sentences(body)
    out = []
    for i, s in enumerate(sents):
        for m in target.finditer(s):
            nums = numbers(m.group(0)) or numbers(s[m.start():m.end() + 12])
            if not nums or not (nums & src_nums) or not future.search(s):
                continue
            context = s + ' ' + (sents[i - 1] if i else '')
            low = context.lower()
            if attrib.search(context) or any(n in low for n in speakers):
                continue
            # the other script's cues also count (a zh post may say "Standard Chartered expects")
            if (ATTRIB_EN if lang == 'zh' else ATTRIB_ZH).search(context):
                continue
            out.append({'code': 'unattributed_forecast',
                        'detail': f'forecast "{m.group(0).strip()}" comes from the source but reads as the account\'s own '
                                  f'call: "{s[:120]}"'})
            break
    return out[:1]


# ------------------------------------------------------------------ stale market state

NEW_HIGH = re.compile(r"\b(?:new|fresh|record|all[- ]time|multi[- ](?:month|year)|year-to-date|ytd|cycle)\s+highs?\b|"
                      r"\bATH\b|\brecord (?:close|level|territory)\b|\bhighest (?:level|close) (?:since|ever|in)\b|"
                      r"创(?:下)?(?:了)?(?:近期|阶段性|历史|年内|年度|今年)?新高|历史(?:新)?高(?:点|位)|新高|刷新(?:了)?(?:纪录|记录|高点)",
                      re.I)
_PRICE_CACHE = {}


def _published(source, units):
    best = None
    for v in [(source or {}).get('published_at')] + [((u.get('unit', u) if isinstance(u, dict) else {}) or {}).get('published_at')
                                                    for u in units or ()]:
        try:
            t = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            continue
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        best = t if best is None or t > best else best
    return best


def price_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_STALE_PRICE', '0') == '1'


def off_high(text, fetch=None):
    """(symbol, last, recent high, fraction below high) for the text's main ticker, from the chart fetchers; None."""
    from live import charts
    subj = charts.pick_subject(text)
    if not subj:
        return None
    key = subj['symbol']
    if key not in _PRICE_CACHE:
        try:
            if fetch is not None:
                data = fetch(subj)
            elif subj['asset'] == 'crypto':
                data = charts.fetch_crypto(subj['symbol'], '1d', 60)
            else:
                data = charts.fetch_stock(subj['symbol'], '1d', 60)
        except Exception:   # noqa: BLE001 - no price, no verdict
            data = None
        rows = (data or {}).get('rows') or []
        if len(rows) < 5:
            _PRICE_CACHE[key] = None
        else:
            last, high = rows[-1][4], max(r[2] for r in rows)
            _PRICE_CACHE[key] = (subj['display'], last, high, (high - last) / high if high else 0.0)
    return _PRICE_CACHE[key]


def stale_claim_findings(body, units, source=None, now=None, fetch=None):
    m = NEW_HIGH.search(str(body or ''))
    if not m:
        return []
    now = now or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    pub = _published(source, units)
    if pub is not None and now - pub > timedelta(days=STALE_DAYS):
        return [{'code': 'stale_market_claim',
                 'detail': f'"{m.group(0)}" stated as current, but the source is {(now - pub).days} days old at post time'}]
    if fetch is not None or price_enabled():
        p = off_high(body, fetch=fetch)
        if p and p[3] > OFF_HIGH:
            return [{'code': 'stale_market_claim',
                     'detail': f'"{m.group(0)}" stated as current, but {p[0]} is {p[3]:.0%} under its recent high '
                               f'(last {p[1]:,.2f} vs high {p[2]:,.2f})'}]
    return []


def _normalize_opener(first_line_text, lang):
    """Canonical opener key for repeat-detection (first 6 CJK chars or first 4 EN words after stripping
    punctuation / @ / $). Returns '' when the line is empty."""
    s = str(first_line_text or '').strip()
    if not s:
        return ''
    # strip leading punctuation and social-media tokens
    s = re.sub(r'^[\W@$#]+', '', s).strip()
    if lang == 'zh':
        cjk = re.sub(r'[^一-鿿㐀-䶿 0-⩭f]', '', s)
        return cjk[:6]
    else:
        words = re.findall(r'\w+', s)
        return ' '.join(words[:4]).lower()


def batch_opener_findings(rows):
    """SOFT opener_repeat check over one day's drafts.

    rows: list of dicts with id, account_id, lang, body (the full draft body, not the post text).
    Stable order within the batch must be by suggested_post_time_london then id (caller's responsibility).

    Returns a list of finding dicts: {'id': draft_id, 'finding': {...}}.
    Each finding has code 'opener_repeat', level 'soft', and a detail string.

    Rules:
      1. Same normalised opener used by >= 2 accounts: every draft after the first gets a finding.
      2. Same weak-opener PHRASE used by >= 3 accounts in a day: every one of those drafts gets a
         phrase-cluster finding (all of them, not just the later ones).
    """
    seen_openers = {}   # normalised key -> first account_id that used it
    phrase_counts = {}  # weak-opener phrase -> list of (draft_id, account_id)
    out = []

    for row in rows:
        body = str(row.get('body') or '')
        lang = str(row.get('lang') or 'zh')
        draft_id = row.get('id', '')
        account_id = str(row.get('account_id', ''))
        fl = first_line(body)
        key = _normalize_opener(fl, lang)

        # track weak-opener phrases for the 3-account rule
        explicit = _explicit_weak_opener(fl, lang)
        if explicit:
            phrase_counts.setdefault(explicit, []).append((draft_id, account_id))

        if not key:
            continue
        if key in seen_openers:
            out.append({'id': draft_id, 'finding': {
                'code': 'opener_repeat', 'level': 'soft',
                'detail': f'opener "{key}" also used by {seen_openers[key]}'}})
        else:
            seen_openers[key] = account_id

    # phrase-cluster rule: >= 3 accounts sharing a weak opener phrase
    for phrase, hits in phrase_counts.items():
        if len(hits) >= 3:
            accounts_using = [a for _, a in hits]
            for draft_id, account_id in hits:
                # avoid double-appending if already flagged by key-repeat above
                already = any(f['id'] == draft_id and f['finding']['code'] == 'opener_repeat'
                              and f'phrase cluster' in f['finding']['detail']
                              for f in out)
                if not already:
                    others = [a for a in accounts_using if a != account_id]
                    out.append({'id': draft_id, 'finding': {
                        'code': 'opener_repeat', 'level': 'soft',
                        'detail': f'phrase cluster "{phrase}" used by {len(hits)} accounts including {others[0]}'}})
    return out


def findings(body, units, source=None, now=None, lang='en'):
    if not enabled():
        return []
    return (hook_findings(body, lang) + forecast_findings(body, units, source, lang)
            + stale_claim_findings(body, units, source, now))
