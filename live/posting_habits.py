"""Posting habits per account, learned from the account's donor cluster; donor text stays in the ignored corpus.

Oct 7 rebuild (Fiona: learn HOW the donors post). The Oct 5 card counted raw post lengths of whichever donor was
attached (one donor, unweighted) and compose only used its short/medium/long shares to weight shapes, so the
format of every draft was the same judgment post. Now the card is built from the account's 5-donor cluster
(roster acct_<account>) and records, per donor and then mixed by donor weight (any single donor capped at
DONOR_CAP influence, the excess spread over the others):

- post-type mix (POST_TYPES, derived from the corpus: one-line take, quick take, question / 追问, news-flash
  headline, chart / image + caption, list / data dump, long single post, thread, quote-reply commentary),
- length mix per type (short / medium / long / thread, thread length in parts) - a post samples ONE type and
  then ONE length bucket from that type's distribution; nothing is averaged,
- topic mix across the beat, opener / closer habits per type, punctuation and line-break habits,
- posting-time distribution (London hours, from the tweet-id timestamp: restored posts carry no `created`).

Signals the corpus does not carry for every post are estimated, and the card says how (`method`):
`quote` and `media` metadata exist only on each donor's ~20 most recent posts, so the quote-reply share is the
donor's recent share shrunk toward the cluster mean, and an image is a `media` photo or (older posts) a
trailing t.co link on a post that does not read like a link share. Threads are posts with a thread marker
(1/, 🧵, (1/n)); the corpus keeps only the head tweet, so thread length comes from the marker or the head size.

choose_format() samples type + length for one post (rotation: a type used in the persona's last ROTATION posts
is down-weighted 20x) and format_block() turns it into the compose payload block with two real cluster posts of
that type as anchors (read from the local corpus at compose time, never written to the card).
"""
from __future__ import annotations

import collections
import json
import math
import random
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from live.exemplars import load_posts

CARDS_DIR = Path(__file__).resolve().parent / 'personas' / 'posting_habits'
CARD_VERSION = 'cluster-v2'
GUIDANCE = ('Write in the post_format the account sampled for this post (type, length, line breaks and '
            'punctuation habits of its donors), not one fixed judgment-post template.')

POST_TYPES = ('one_liner', 'quick_take', 'question', 'news_flash', 'chart_caption', 'list_dump',
              'long_take', 'thread', 'quote_comment')
LENGTHS = ('short', 'medium', 'long', 'thread')
# characters without whitespace (same unit as length_target / length_band)
BUCKETS = {'zh': {'short': (8, 80), 'medium': (80, 250), 'long': (250, 600)},
           'en': {'short': (20, 140), 'medium': (140, 400), 'long': (400, 1400)}}
THREAD_PART = {'zh': (50, 140), 'en': (120, 270)}
DONOR_CAP = 0.40
QUOTE_PRIOR_N = 40          # shrinkage of a donor's recent quote share toward the cluster mean
QUOTE_CAP = 0.30            # the quote flag covers each donor's last 1-2 days only (10-20 posts): too thin to set more
ROTATION = 3                # a type used in the last 3 posts is down-weighted
ROTATION_PENALTY = 0.05
TZ = 'Europe/London'
TWITTER_EPOCH_MS = 1288834974657

TYPE_LABEL = {'one_liner': 'one-line take', 'quick_take': 'quick take (2-4 short lines)',
              'question': 'question / 追问', 'news_flash': 'news-flash headline',
              'chart_caption': 'chart / image + caption', 'list_dump': 'list / data dump',
              'long_take': 'long single post', 'thread': 'thread', 'quote_comment': 'quote-reply commentary'}
TYPE_RULE = {
    'one_liner': ('ONE line, one sentence: the call with its reason folded in. No line breaks, no setup, '
                  'no closing moral.', '只写一行一句话：判断里带上原因。不换行，不铺垫，不收尾总结。'),
    'quick_take': ('2-4 short lines: the call, the one fact behind it, what it does. Line breaks between beats.',
                   '2 到 4 行短句：判断、撑住它的一个事实、它带来的后果。每个意思一行。'),
    'question': ('Make the point as a pointed question (追问) the data raises: one or two lines of setup with '
                 'the fact, then the question as the last line. The question carries the call; no answer after it.',
                 '用一个追问把观点问出来：先一两行摆出事实，最后一行是问题。问题本身带着判断，问完不自问自答。'),
    'news_flash': ('Headline-style flash: first line is the news in plain words (a tag like BREAKING only if the '
                   'donor anchors use one), then one or two lines on why it matters. Short, no paragraphs.',
                   '快讯式：第一行用大白话把消息说出来，再用一两行说它为什么重要。短，不分段。'),
    'chart_caption': ('Caption for a chart / image: the one line (or two) a donor writes above a chart - what the '
                      'chart shows and the call. Also fill image_needed with a short description of the chart '
                      'that should go with it (what series, what period, what to highlight). The caption must '
                      'make sense next to that chart; do not describe the chart in the caption.',
                      '配图帖：写博主贴图时上面那一两行话——这张图说明了什么、判断是什么。同时在 image_needed 里写清'
                      '要配的图（哪个数据序列、什么时间段、突出什么）。正文不要描述图本身。'),
    'list_dump': ('List / data dump: one headline line with the call, then 3-5 short list lines (one number or '
                  'fact each, -, • or numbered), optionally one closing line. Every list line from the units.',
                  '清单式：第一行是判断，接着 3 到 5 行短清单（每行一个数字或事实，用 - 或 • 或 1. 开头），'
                  '最后可以有一行收尾。清单内容都来自 units。'),
    'long_take': ('Long single post: 2-4 short paragraphs, each adding a new piece of evidence or a step of the '
                  'mechanism. No headers, no list.',
                  '长帖：2 到 4 个短段落，每段带来新的证据或机制里新的一环。不加小标题，不列清单。'),
    'thread': ('Thread: return the parts in "thread" (a JSON list of strings), each part a self-contained post '
               'of thread_part_length; part 1 is the hook with the call, the middle parts each add one piece of '
               'evidence or mechanism, the last part lands it. Numbering (1/, 2/) only if the anchors use it. '
               'body = the parts joined with a blank line.',
               '串推：在 "thread" 里返回每一条（JSON 字符串数组），每条单独成立、长度按 thread_part_length；'
               '第 1 条是带判断的开头，中间每条加一个证据或机制，最后一条收住。只有 anchor 用编号时才写 1/ 2/。'
               'body = 各条用空行连起来。'),
    'quote_comment': ('Quote-reply commentary: the post sits on top of a quoted headline / statement from the '
                      'source (shown as the quoted card, not in your text). React to it directly in 1-3 lines: '
                      'agree, push back or add the missing piece. Do not restate the quoted text. Also fill '
                      '"quoted" with the short headline / statement being quoted (from the units, <= 120 chars).',
                      '引用评论：这条帖子挂在一条被引用的标题/表态上面（引用卡片单独显示，不写进正文）。直接回应它，'
                      '1 到 3 行：认同、反驳或补上缺的那一块。不要复述被引用的话。同时在 "quoted" 里写出被引用的'
                      '那句标题/表态（来自 units，120 字以内）。'),
}
# post type -> composition shapes that fit it (compose_shapes.SHAPES ids)
TYPE_SHAPES = {'one_liner': ('take_short', 'one_number_punch'), 'quick_take': ('take_short', 'one_number_punch',
               'thesis_mechanism'), 'question': ('contrarian_question',), 'news_flash': ('one_number_punch', 'data_punch'),
               'chart_caption': ('one_number_punch', 'take_short'), 'list_dump': ('data_punch',),
               'long_take': ('thesis_mechanism', 'data_punch'), 'thread': ('short_thread', 'thesis_mechanism'),
               'quote_comment': ('take_short', 'one_number_punch', 'contrarian_question')}
# types whose form has no room for a separate "what it means" line (missing_implication is not asked)
DEFAULT_TYPE_MIX = {'quick_take': 0.45, 'long_take': 0.2, 'one_liner': 0.15, 'list_dump': 0.1, 'question': 0.1}
DEFAULT_LENGTH_MIX = {'short': 0.4, 'medium': 0.4, 'long': 0.2, 'thread': 0.0}
COMPACT_TYPES = frozenset({'one_liner', 'news_flash', 'chart_caption', 'quote_comment', 'question'})

PREVIOUS_DONOR = {'crypto_macro_zh': 'Bitwux', 'trading_shortterm': 'SPXVIX', 'market_data_charts': 'Mr_Derivatives',
                  'investing_philosophy': 'MebFaber', 'single_stock_deepdive_en': 'EconomyApp',
                  'crypto_macro_en': 'NateGeraci'}   # the "(原)" donor of donor_cluster_REPORT for the 6 new accounts

CJK = re.compile(r'[一-鿿]')
URL = re.compile(r'https?://\S+')
TRAIL_LINK = re.compile(r'https?://t\.co/\S+\s*$')
THREAD_MARK = re.compile(r'🧵|^\s*\(?1\s*/\s*\d*\)?(?:\s|$)|\(1/\d+\)|\b1/\d+\b|\bthread\b\s*[:👇⬇]|（1/\d*）|^\s*1[、.]\s*$', re.I | re.M)
THREAD_N = re.compile(r'\b1\s*/\s*(\d{1,2})\b')
LINKISH = re.compile(r'\b(?:read|article|report|via|link|podcast|interview|listen|watch|full|subscribe|newsletter|'
                     r'blog|substack|episode|webinar|live now|out now)\b|原文|链接|文章|全文|直播|播客|视频|研报全文', re.I)
CHARTISH = re.compile(r'\bcharts?\b|\bgraph\b|\bplot\b|\bshown?\b|\bbelow\b|\bhere\'?s\b|📊|📈|📉|👇|⬇|图|看图|走势', re.I)
FLASH = re.compile(r'^\s*(?:🚨|⚠️|‼️|❗|🔴|BREAKING|JUST IN|JUST ANNOUNCED|NEW\b|UPDATE\b|ALERT\b|FLASH\b|【|快讯|突发|刚刚|重磅|最新[:：])', re.I)
BULLET = re.compile(r'^\s*(?:[-•·▪▫◦*→>➡✅❌🔹🔸🟢🔴🟡⚪⚫]|\d{1,2}[.)、]|[①-⑳]|[a-e]\)|\$[A-Z]{1,5}\b)')
QUESTION_END = re.compile(r'[?？]\s*[\W_]*$')
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')
SELF = re.compile(r'我们|咱们|我的仓|重仓|持仓|建仓|加仓|减仓|清仓|带带我|\b(?:my position|i bought|i sold|long here|short here)\b', re.I)
PROMO = re.compile(r'返佣|开户|邀请码|注册|抽奖|空投|福利|私信|进群|关注|点赞|转发|评论区|课程|社群|直播|报名|优惠|广告|赞助|'
                   r'giveaway|subscribe|sign up|link in bio|discount|promo code|join my|newsletter|use code|webinar', re.I)
MENTION = re.compile(r'@\w+')

TOPICS = (
    ('rates_fed', r'美联储|联储|降息|加息|利率|点阵图|FOMC|鲍威尔|\bfed\b|rate cuts?|rate hikes?|powell|fomc|treasur|yield|bond|美债|国债|收益率'),
    ('macro_data', r'通胀|CPI|PCE|非农|就业|失业|GDP|PMI|零售|衰退|inflation|payrolls?|jobs|unemployment|gdp|pmi|recession|retail sales|economy'),
    ('fx', r'美元|日元|人民币|欧元|汇率|DXY|dollar|yen|yuan|euro|\bfx\b|currenc'),
    ('commodities', r'原油|石油|油价|黄金|白银|铜|天然气|\boil\b|crude|gold|silver|copper|opec|natgas|commodit'),
    ('crypto', r'比特币|BTC|ETH|以太坊|币圈|链上|稳定币|山寨|bitcoin|crypto|ethereum|stablecoin|altcoin|on-chain|onchain|\betf flows?\b'),
    ('ai_semis', r'英伟达|芯片|半导体|算力|AI|台积电|光模块|HBM|数据中心|nvidia|nvda|semis?|semiconductor|chips?|tsmc|gpu|data ?center|hyperscaler|capex'),
    ('earnings_stocks', r'财报|营收|利润|EPS|指引|估值|个股|earnings|revenue|guidance|margins?|eps\b|valuation|\$[A-Z]{2,5}\b'),
    ('index_breadth', r'标普|纳指|道指|大盘|美股|A股|港股|S&P|SPX|SPY|Nasdaq|QQQ|Dow|Russell|breadth|new highs|all-time high|index'),
    ('positioning_tech', r'期权|波动率|VIX|支撑|阻力|均线|仓位|空头|多头|options?|gamma|vol\b|volatility|support|resistance|moving average|'
                         r'positioning|sentiment|put|call skew|oversold|overbought|technical'),
    ('policy_politics', r'关税|特朗普|选举|政府|财政|赤字|监管|制裁|tariffs?|trump|election|congress|deficit|regulat|sanction|white house|shutdown'),
    ('china', r'中国|国内|央行|人民银行|房地产|china|chinese|pboc|beijing'),
    ('investing_principles', r'长期|复利|纪律|心态|风险管理|分散|耐心|投资者|long[- ]term|compounding|discipline|behavio|diversif|patience|investors? should|lesson|mistake'),
)
_TOPIC_RX = [(k, re.compile(v, re.I)) for k, v in TOPICS]


# ---------------------------------------------------------------- per-post features

def clean_text(text):
    """Text as a reader sees it: links and promo / @ lines cut (same rule as language_habits)."""
    from live.language_habits import strip_promo
    return strip_promo(text)


def size_of(text):
    return len(re.sub(r'\s', '', text or ''))


def post_time(post):
    """UTC datetime of a post: `created` when present, else the tweet-id (snowflake) timestamp."""
    created = post.get('created')
    if created:
        try:
            return datetime.strptime(created, '%a %b %d %H:%M:%S %z %Y').astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        ms = (int(post.get('id')) >> 22) + TWITTER_EPOCH_MS
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def london_hour(post):
    from zoneinfo import ZoneInfo
    t = post_time(post)
    return t.astimezone(ZoneInfo(TZ)).hour if t else None


def has_image(post):
    """Photo attached (recent posts carry `media`); older posts: a trailing t.co link that is not a link share."""
    media = post.get('media') or []
    if media:
        return any(str(m).startswith('photo') or (isinstance(m, dict) and m.get('type') == 'photo') for m in media)
    if post.get('restored_from') and TRAIL_LINK.search(post.get('text') or ''):
        text = URL.sub('', post.get('text') or '')
        return not LINKISH.search(text) or bool(CHARTISH.search(text))
    return False


def length_bucket(size, lang, truncated=False):
    b = BUCKETS['zh' if lang == 'zh' else 'en']
    if truncated or size >= b['long'][0]:
        return 'long'
    return 'medium' if size >= b['medium'][0] else 'short'


def classify(post, lang, tag=None):
    """(post_type, length_bucket, thread_parts or None) for one original post."""
    tag = tag or {}
    raw = post.get('text') or ''
    text = clean_text(raw)
    size = size_of(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    truncated = bool(post.get('text_truncated'))
    bucket = length_bucket(size, lang, truncated)
    struct = tag.get('structure') or {}
    if struct.get('thread_marker') or THREAD_MARK.search(text):
        m = THREAD_N.search(text)
        per = THREAD_PART['zh' if lang == 'zh' else 'en'][1]
        parts = int(m.group(1)) if m and 2 <= int(m.group(1)) <= 25 else max(3, min(8, math.ceil(size / per) + 1))
        return 'thread', 'thread', parts
    if post.get('quote'):
        return 'quote_comment', bucket, None
    if FLASH.search(text) and bucket != 'long':
        return 'news_flash', bucket, None
    if has_image(post) and bucket != 'long':
        return 'chart_caption', bucket, None
    list_lines = sum(bool(BULLET.match(ln)) for ln in lines)
    if list_lines >= 3 or (struct.get('list') and len(lines) >= 4):
        return 'list_dump', bucket, None
    if QUESTION_END.search(text) and bucket != 'long':
        return 'question', bucket, None
    if bucket == 'long':
        return 'long_take', bucket, None
    if len(lines) <= 1 and bucket == 'short':
        return 'one_liner', bucket, None
    return 'quick_take', bucket, None


def topic_of(text):
    hits = [k for k, rx in _TOPIC_RX if rx.search(text)]
    return hits[0] if hits else 'other'


def opener_kind(text, lang):
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), '')
    if not first:
        return 'empty'
    if FLASH.search(first):
        return 'headline_tag'
    if EMOJI.match(first):
        return 'emoji'
    if re.match(r'^\$[A-Z]{1,5}\b', first):
        return 'ticker'
    if re.match(r'^[\d$€£¥%+\-.]', first):
        return 'number'
    if QUESTION_END.search(first.split('。')[0]) or re.match(r'^(?:why|what|how|is|are|does|do|can|will|who)\b|^为什么|^凭什么|^难道', first, re.I):
        return 'question'
    if re.search(r'^[^，,。.:：]{1,24}[：:](?!//)', first) or re.match(r'^(?:据|according to|per\b)', first, re.I):
        return 'attribution_or_label'
    return 'statement'


def closer_kind(text):
    t = text.rstrip()
    if not t:
        return 'none'
    end = t[-1]
    if EMOJI.match(end):
        return 'emoji'
    if end in '?？':
        return 'question'
    if end in '!！':
        return 'exclaim'
    if end in '.。':
        return 'ellipsis' if t.endswith(('...', '…')) else 'period'
    if end == '…':
        return 'ellipsis'
    return 'no_terminal_punct'


# ---------------------------------------------------------------- card

def capped_weights(weights, cap=DONOR_CAP):
    """Normalise donor weights and cap any single donor at `cap`, spreading the excess over the rest."""
    w = {h: max(float(v or 0), 0.0) for h, v in (weights or {}).items()}
    total = sum(w.values()) or 1.0
    w = {h: v / total for h, v in w.items()}
    if len(w) * cap < 1:
        return w
    for _ in range(len(w)):
        over = {h for h, v in w.items() if v > cap + 1e-9}
        if not over:
            break
        excess = sum(w[h] - cap for h in over)
        free = {h: v for h, v in w.items() if h not in over and v < cap}
        for h in over:
            w[h] = cap
        base = sum(free.values()) or 1.0
        for h, v in free.items():
            w[h] = v + excess * v / base
    return {h: round(v, 4) for h, v in w.items()}


def _tags(handle):
    from live.exemplars import POSTS_DIR
    path = POSTS_DIR.parent / 'tags' / (handle.lower() + '.json')
    if not path.exists():
        path = POSTS_DIR.parent / 'tags' / (handle + '.json')
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _lang_ok(text, lang):
    n = len(CJK.findall(text))
    return n >= 6 if lang == 'zh' else n == 0 and len(text) >= 8


def donor_rows(handle, lang, posts_dir=None):
    """[(post, cleaned text, type, bucket, parts)] of one donor's originals in the account language."""
    try:
        posts = load_posts(handle, posts_dir)
    except Exception:   # noqa: BLE001
        return []
    tags = _tags(handle)
    out = []
    for p in posts:
        if not p.get('text') or p.get('rt') or p.get('reply') or p.get('reply_to') or p.get('pinned'):
            continue
        text = clean_text(p['text'])
        if not text or not _lang_ok(text, lang):
            continue
        kind, bucket, parts = classify(p, lang, tags.get(str(p.get('id'))))
        out.append((p, text, kind, bucket, parts))
    return out


def _share(counter, n):
    return {k: round(v / n, 4) for k, v in counter.most_common()} if n else {}


def donor_profile(rows, lang):
    """Per-donor distributions (all shares of this donor's own posts)."""
    n = len(rows)
    types, lens, topics = collections.Counter(), collections.defaultdict(collections.Counter), collections.Counter()
    openers, closers = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    hours, parts = collections.Counter(), []
    recent = [r for r in rows if not r[0].get('restored_from')]
    quotes = sum(bool(r[0].get('quote')) for r in recent)
    short_n = short_noperiod = lines_total = blank_para = emoji_posts = multi_line = 0
    for p, text, kind, bucket, n_parts in rows:
        types[kind] += 1
        lens[kind][bucket] += 1
        topics[topic_of(text)] += 1
        openers[kind][opener_kind(text, lang)] += 1
        closers[kind][closer_kind(text)] += 1
        h = london_hour(p)
        if h is not None:
            hours[h] += 1
        if n_parts:
            parts.append(n_parts)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        lines_total += len(lines)
        multi_line += len(lines) > 1
        blank_para += '\n\n' in text
        emoji_posts += bool(EMOJI.search(text))
        if bucket == 'short':
            short_n += 1
            short_noperiod += closer_kind(text) != 'period'
    return {'n': n, 'recent_n': len(recent), 'recent_quotes': quotes,
            'types': _share(types, n), 'type_counts': dict(types),
            'length_by_type': {k: _share(c, sum(c.values())) for k, c in lens.items()},
            'topics': _share(topics, n), 'hours': {h: c / max(1, sum(hours.values())) for h, c in hours.items()},
            'openers': {k: _share(c, sum(c.values())) for k, c in openers.items()},
            'closers': {k: _share(c, sum(c.values())) for k, c in closers.items()},
            'thread_parts': parts,
            'punct': {'short_no_terminal_period': round(short_noperiod / short_n, 3) if short_n else None,
                      'lines_per_post': round(lines_total / n, 2) if n else None,
                      'multi_line_share': round(multi_line / n, 3) if n else None,
                      'blank_line_paragraphs': round(blank_para / n, 3) if n else None,
                      'emoji_post_share': round(emoji_posts / n, 3) if n else None}}


def _mix(profiles, weights, key):
    out = collections.Counter()
    for h, prof in profiles.items():
        for k, v in (prof.get(key) or {}).items():
            out[k] += weights.get(h, 0) * v
    total = sum(out.values()) or 1.0
    return {k: round(v / total, 4) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def _with_quote_estimate(profiles):
    """Restored posts carry no quote flag: a donor's quote share = recent share shrunk to the cluster mean;
    the other types are scaled by (1 - quote share) over the non-quote posts."""
    rq = sum(p['recent_quotes'] for p in profiles.values())
    rn = sum(p['recent_n'] for p in profiles.values()) or 1
    mean = rq / rn
    for prof in profiles.values():
        q = min(QUOTE_CAP, (prof['recent_quotes'] + QUOTE_PRIOR_N * mean) / (prof['recent_n'] + QUOTE_PRIOR_N))
        counts = {k: v for k, v in prof['type_counts'].items() if k != 'quote_comment'}
        tot = sum(counts.values()) or 1
        prof['types'] = {**{k: round((1 - q) * v / tot, 4) for k, v in counts.items()}, 'quote_comment': round(q, 4)}
    return round(mean, 4)


def build_card_for(handles_weights, lang, persona_id='', posts_dir=None, cap=DONOR_CAP):
    """Card from {handle: weight} (the cluster, or a single previous donor for the before/after table)."""
    weights = capped_weights(handles_weights, cap)
    rows_by = {h: donor_rows(h, lang, posts_dir) for h in weights}
    profiles = {h: donor_profile(rows, lang) for h, rows in rows_by.items() if rows}
    weights = capped_weights({h: weights[h] for h in profiles}, cap) if profiles else {}
    quote_mean = _with_quote_estimate(profiles) if profiles else 0
    type_mix = _mix(profiles, weights, 'types')
    by_type = {}
    for kind in POST_TYPES:
        acc = collections.Counter()
        for h, prof in profiles.items():
            share = weights.get(h, 0) * (prof['types'].get(kind) or 0)
            dist = prof['length_by_type'].get(kind) or {}
            if kind == 'quote_comment' and not dist:   # quote metadata: recent posts only
                dist = {'short': 1.0}
            for b, v in dist.items():
                acc[b] += share * v
        tot = sum(acc.values())
        if tot:
            by_type[kind] = {b: round(v / tot, 4) for b, v in acc.most_common()}
    length_mix = collections.Counter()
    for kind, share in type_mix.items():
        for b, v in (by_type.get(kind) or {}).items():
            length_mix[b] += share * v
    parts = [n for prof in profiles.values() for n in prof['thread_parts']]
    hours = collections.Counter()
    for h, prof in profiles.items():
        for hr, v in prof['hours'].items():
            hours[int(hr)] += weights.get(h, 0) * v
    punct = {}
    for key in ('short_no_terminal_period', 'lines_per_post', 'multi_line_share', 'blank_line_paragraphs', 'emoji_post_share'):
        vals = [(weights.get(h, 0), prof['punct'][key]) for h, prof in profiles.items() if prof['punct'][key] is not None]
        tw = sum(w for w, _ in vals)
        punct[key] = round(sum(w * v for w, v in vals) / tw, 3) if tw else None
    per_type = {}
    for kind in type_mix:
        per_type[kind] = {'openers': dict(list(_mix({h: {'openers': p['openers'].get(kind, {})} for h, p in profiles.items()},
                                                    weights, 'openers').items())[:3]),
                          'closers': dict(list(_mix({h: {'closers': p['closers'].get(kind, {})} for h, p in profiles.items()},
                                                    weights, 'closers').items())[:3])}
    b = BUCKETS['zh' if lang == 'zh' else 'en']
    if not profiles:   # no corpus: the Oct 5 default mix, so compose still varies
        type_mix, length_mix = dict(DEFAULT_TYPE_MIX), collections.Counter(DEFAULT_LENGTH_MIX)
        by_type = {k: dict(DEFAULT_LENGTH_MIX) for k in type_mix}
    return {
        'persona_id': persona_id, 'version': CARD_VERSION, 'lang': lang,
        'basis': 'donor cluster observations' if profiles else 'Fiona Oct 5 default; donor posts missing',
        'sample_ids': [],
        'donors': {h: {'weight_capped': weights.get(h), 'posts': profiles[h]['n'],
                       'recent_quote_share': round(profiles[h]['recent_quotes'] / profiles[h]['recent_n'], 3)
                       if profiles[h]['recent_n'] else None} for h in profiles},
        'posts': sum(p['n'] for p in profiles.values()),
        'post_type_mix': type_mix,
        'length_by_type': by_type,
        'length_mix': {k: round(length_mix.get(k, 0), 4) for k in LENGTHS},
        'length_buckets': {'unit': 'characters without whitespace', **{k: list(v) for k, v in b.items()},
                           'thread_part': list(THREAD_PART['zh' if lang == 'zh' else 'en'])},
        'thread': {'share': type_mix.get('thread', 0), 'parts_observed': len(parts),
                   'parts_median': sorted(parts)[len(parts) // 2] if parts else 3,
                   'parts_range': [min(parts), max(parts)] if parts else [3, 5]},
        'topic_mix': _mix(profiles, weights, 'topics'),
        'per_type_habits': per_type,
        'punctuation': punct,
        'posting_hours_london': {str(h): round(v, 4) for h, v in sorted(hours.items())},
        'method': (f'per-donor shares mixed by donor weight capped at {cap:.0%}; type = first match of thread marker, '
                   'quote flag, flash tag, image, >=3 list lines, closing question, long, one line; quote share = '
                   f'recent-post share shrunk to the cluster mean (n={QUOTE_PRIOR_N}, cluster mean {quote_mean}), capped at {QUOTE_CAP}; image = '
                   'media photo or trailing t.co not reading as a link share; hours = tweet-id timestamps in Europe/London'),
        'guidance': GUIDANCE,
    }


def build_card(persona, posts_dir=None):
    return build_card_for(getattr(persona, 'donor_weights', {}) or {}, persona.lang, persona.persona_id, posts_dir)


def previous_donor(persona_id):
    if persona_id in PREVIOUS_DONOR:
        return PREVIOUS_DONOR[persona_id]
    try:
        accounts = json.loads((Path(__file__).resolve().parent / 'accounts.json').read_text())['accounts']
    except (OSError, ValueError, KeyError):
        return None
    for a in accounts:
        if a.get('id') == persona_id:
            return (a.get('language_donor') or {}).get('handle')
    return None


def load_card(persona):
    try:
        card = json.loads((CARDS_DIR / (persona.persona_id + '.json')).read_text())
        if card.get('version') == CARD_VERSION or not getattr(persona, 'donor_weights', None):
            return card
    except (OSError, ValueError):
        pass
    return build_card(persona)


def write_card(persona, posts_dir=None):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    card = build_card(persona, posts_dir)
    prev = previous_donor(persona.persona_id)
    if prev:   # before/after: the single previous donor through the same classifier (aggregates only)
        old = build_card_for({prev: 1.0}, persona.lang, persona.persona_id, posts_dir, cap=1.0)
        card['previous_single_donor'] = {'handle': prev, 'posts': old['posts'], 'post_type_mix': old['post_type_mix'],
                                         'length_mix': old['length_mix']}
    (CARDS_DIR / (persona.persona_id + '.json')).write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    return card


# ---------------------------------------------------------------- compose time

def _rng(seed):
    return random.Random(int(sha256(str(seed).encode()).hexdigest()[:12], 16))


def _draw(rng, dist):
    items = [(k, v) for k, v in dist.items() if v > 0]
    if not items:
        return None
    r, acc = rng.random() * sum(v for _, v in items), 0.0
    for k, v in items:
        acc += v
        if r <= acc:
            return k
    return items[-1][0]


def recent_types(recent):
    out = []
    for r in recent or ():
        pf = r.get('post_format') if isinstance(r, dict) else None
        if isinstance(pf, dict) and pf.get('type'):
            out.append(pf['type'])
        elif isinstance(pf, str):
            out.append(pf)
    return out


def type_weights(card, recent=(), allowed=None, rotation=ROTATION):
    mix = dict(card.get('post_type_mix') or {})
    if allowed is not None:
        mix = {k: v for k, v in mix.items() if k in allowed}
    last = recent_types(recent)[-rotation:]
    return {k: v * (ROTATION_PENALTY if k in last else 1.0) for k, v in mix.items()}


def target_chars(lang, bucket, rng=None, parts=None):
    key = 'zh' if lang == 'zh' else 'en'
    if bucket == 'thread':
        lo, hi = THREAD_PART[key]
        return {'min': lo * (parts or 3), 'max': hi * (parts or 3), 'per_part': {'min': lo, 'max': hi}}
    lo, hi = BUCKETS[key][bucket]
    if bucket == 'long':   # long single posts sit in the lower part of the observed range
        hi = int(lo + (hi - lo) * 0.45)
    return {'min': lo, 'max': hi}


def choose_format(persona, *, recent=(), seed='', allowed=None, card=None, force_type=None, force_length=None):
    """Sample one post type (rotation against the last ROTATION posts), then one length bucket from that type's
    own length distribution in the cluster. Deterministic for a seed."""
    card = card or load_card(persona)
    rng = _rng(f'{persona.persona_id}|{seed}|format')
    weights = type_weights(card, recent, allowed)
    kind = force_type or _draw(rng, weights) or 'quick_take'
    dist = (card.get('length_by_type') or {}).get(kind) or {'medium': 1.0}
    bucket = force_length or ('thread' if kind == 'thread' else _draw(rng, dist) or 'medium')
    if kind == 'one_liner':
        bucket = 'short'
    if kind == 'long_take':
        bucket = 'long'
    parts = None
    if bucket == 'thread':
        lo, hi = (card.get('thread') or {}).get('parts_range') or [3, 5]
        parts = max(3, min(5, rng.randint(max(3, lo), max(3, min(hi, 5)))))
    return {'type': kind, 'length': bucket, 'thread_parts': parts,
            'length_target': target_chars(persona.lang, bucket, parts=parts),
            'type_weights': {k: round(v, 4) for k, v in weights.items()},
            'length_dist': dist, 'recent_types': recent_types(recent)[-ROTATION:],
            'shapes': list(TYPE_SHAPES.get(kind, ())), 'card_version': card.get('version')}


_ANCHOR_CACHE = {}


def type_anchors(persona, kind, seed='', k=2, posts_dir=None):
    """k real cluster posts of this type from distinct donors (weight-ordered draw), cleaned; never stored."""
    key = (persona.persona_id, str(posts_dir or ''))
    if key not in _ANCHOR_CACHE:
        crypto_ok = persona.persona_id.startswith('crypto_')
        from live.language_habits import _CRYPTO
        try:
            from live.zh_register import _TRAD
        except Exception:   # noqa: BLE001
            _TRAD = re.compile(r'(?!)')
        pools = collections.defaultdict(lambda: collections.defaultdict(list))
        for handle in (getattr(persona, 'donor_weights', {}) or {}):
            for p, text, t, bucket, parts in donor_rows(handle, persona.lang, posts_dir):
                if PROMO.search(text) or SELF.search(text) or MENTION.search(text):
                    continue
                if (not crypto_ok and _CRYPTO.search(text)) or (persona.lang == 'zh' and _TRAD.search(text)):
                    continue
                if size_of(text) > (600 if persona.lang == 'zh' else 1100) or size_of(text) < 6:
                    continue
                pools[t][handle].append({'handle': handle, 'id': str(p.get('id')), 'text': text, 'length': bucket,
                                         **({'thread_parts': parts} if parts else {})})
        _ANCHOR_CACHE[key] = pools
    by = _ANCHOR_CACHE[key].get(kind) or {}
    if not by:
        return []
    weights = capped_weights(getattr(persona, 'donor_weights', {}) or {})
    rng = _rng(f'{persona.persona_id}|{seed}|{kind}|anchors')
    handles, out = sorted(by), []
    while handles and len(out) < k:
        h = rng.choices(handles, weights=[max(weights.get(x, 0.05), 0.05) for x in handles])[0]
        out.append(rng.choice(by[h]))
        handles.remove(h)
    if len(out) < k:   # one donor only: a second post of the same donor
        rest = [e for e in by[out[0]['handle']] if e is not out[0]] if out else []
        if rest:
            out.append(rng.choice(rest))
    return out


def format_block(persona, fmt, *, seed='', card=None, posts_dir=None):
    """post_format block for the COMPOSE payload (HARD for this post)."""
    card = card or load_card(persona)
    zh = persona.lang == 'zh'
    kind = fmt['type']
    habits = (card.get('per_type_habits') or {}).get(kind) or {}
    punct = card.get('punctuation') or {}
    rule_en, rule_zh = TYPE_RULE[kind]
    block = {'type': kind, 'label': TYPE_LABEL[kind], 'length': fmt['length'],
             'length_target': fmt['length_target'], 'unit': 'characters without whitespace',
             'structure': rule_zh if zh else rule_en,
             'opener_habits': habits.get('openers', {}), 'closer_habits': habits.get('closers', {}),
             'punctuation_habits': {k: v for k, v in punct.items() if v is not None},
             'anchor_posts': [{'handle': a['handle'], 'text': a['text']} for a in
                              type_anchors(persona, kind, seed, 2, posts_dir)],
             'rule': ('HARD for this post: write in this post type and length (length_target counts characters '
                      'without whitespace); it overrides composition_shape on form and length. Follow the donors\' '
                      'opener / closer and punctuation habits for this type (e.g. a short post with no terminal '
                      'period when closer_habits says so). anchor_posts are two real posts of this type from the '
                      'account\'s donor cluster: copy their FORM only (length, line breaks, punctuation, how they '
                      'open and land) - never a sentence, fact, number or opinion from them.')}
    if kind in COMPACT_TYPES:
        block['compact_note'] = ('这种帖子没有单独的「影响」句：原因要带在判断里，后果可以不写。' if zh else
                                 'This type has no separate "what it means" line: fold the reason into the call; '
                                 'the consequence may stay implicit.')
    if fmt.get('thread_parts'):
        block['thread_parts'] = fmt['thread_parts']
        block['thread_part_length'] = fmt['length_target'].get('per_part')
    if kind == 'chart_caption':
        block['image_needed_rule'] = ('Return "image_needed": one short line describing the chart to attach '
                                      '(series, period, what to highlight), in the post language, from the units only.')
    if kind == 'quote_comment':
        block['quoted_rule'] = 'Return "quoted": the short headline / statement being quoted, from the units.'
    return block


def compact_type(fmt):
    return bool(fmt) and (fmt.get('type') if isinstance(fmt, dict) else fmt) in COMPACT_TYPES


# ---------------------------------------------------------------- posting time

def sample_post_time(card, day, seed='', taken=(), min_gap_min=20):
    """A London posting time on `day` (date) drawn from the card's hour distribution; avoids `taken` minutes."""
    from datetime import datetime as _dt, time as _time
    from zoneinfo import ZoneInfo
    rng = _rng(f'{card.get("persona_id")}|{seed}|{day}|time')
    hours = {int(h): v for h, v in (card.get('posting_hours_london') or {}).items() if v > 0}
    hours = {h: v for h, v in hours.items() if 6 <= h <= 23} or {9: 1.0}
    for _ in range(50):
        h = int(_draw(rng, hours))
        m = rng.randrange(0, 60)
        t = _dt.combine(day, _time(h, m), tzinfo=ZoneInfo(TZ))
        if all(abs((t - x).total_seconds()) >= min_gap_min * 60 for x in taken):
            return t
    return t
