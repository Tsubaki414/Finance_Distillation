"""What the people we follow are actually saying about this event.

This closes a gap that made the whole product miss its point. The user's description of what they
want has been consistent and blunt:

    我要的就是，汇集和搬运当下热点的帖子，然后参考热点的观点进行洗稿

and the pipeline did not do the second half at all. Tracing it: a fact packet carries
`signal_posts`, which turned out to be **seven bare ID strings** — no text, no author, no
timestamp. The excerpt block that shows a writer what people said was built only for
`lane == 'cross_language_gap'`. So on every other lane, including the hot-signal lane that exists
precisely to react to what people are posting, the writer saw a table of 40 extracted numbers and
nothing else. It never read a single opinion.

That explains a complaint that had been read as a style problem. Drafts argue from figures alone
because figures alone are all the writer was given. No amount of prompt tuning and no amount of
training data changes that; the opinions were not in the input.

What this module does not do: it does not make the drafts a digest of other people's takes. The
excerpts are attributed material to reason from and disagree with. The carrying rule from
CLAUDE.md is enforced by content/originality.py downstream and restated in the prompt here:

    同语言禁止    a Chinese source may not have its wording, sentence shape or argument order
                  carried into a Chinese draft — only independently rewritten
    跨语言允许    English primary information may inform a Chinese piece, carrying the
                  information and not the sentences, attributed and never passed off as original

Relevance, and why it is filtered rather than trusted. The `signal_posts` on one NVDA packet
resolve to posts about the yen, a Taiwanese memory stock, a 90-year earnings channel and a
nuclear utility. Handing those to a writer as "what people are saying about NVDA" would invite it
to connect things that are not connected. So membership is re-derived here against the entity
rather than inherited, and the packet's own list is kept only where it agrees.
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
sys.path.insert(0, str(ROOT / 'live'))

WINDOW_DAYS = 14
MIN_CHARS = 80
# Enough for a writer to see the reasoning, short enough that it is plainly an excerpt.
EXCERPT_CHARS = 260


def _posts():
    for line in (STORE / 'posts.jsonl').read_text(encoding='utf-8').split('\n'):
        if line.strip():
            try:
                yield json.loads(line)
            except Exception:
                continue


def gather(entity, days=WINDOW_DAYS, per_side=5, packet=None):
    """Attributed opinions on this entity, most recent first, split by language.

    `packet['signal_posts']` is used as a hint, not as truth: an id in that list is kept only if
    the post also matches the entity. See the module docstring for the NVDA packet whose signal
    posts were about the yen.
    """
    import crosslang as cl
    import clean as clean_mod

    pats = cl._patterns(entity)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    claimed = {str(x) for x in ((packet or {}).get('signal_posts') or [])}

    rows, dropped_claimed = [], 0
    for r in _posts():
        if r.get('is_retweet'):
            continue
        c = clean_mod.clean_post(r)
        text = c['text']
        if len(text) < MIN_CHARS or c['cleaning']['excluded']:
            continue
        matched = any(p.search(text) for p in pats)
        pid = str(r.get('post_id'))
        if pid in claimed and not matched:
            dropped_claimed += 1
            continue
        if not matched:
            continue
        at = cl._dt(r.get('created_at'))
        if not at or at < cutoff:
            continue
        rows.append({
            'post_id': pid,
            'handle': r.get('handle'),
            'lang': cl._lang(text),
            'at': at.isoformat(),
            'text': text,
            'from_packet': pid in claimed,
        })

    rows.sort(key=lambda x: x['at'], reverse=True)
    # At most two per author per side. Sorting by recency alone filled the Chinese side of an
    # NVDA query with five consecutive posts from one handle, four of which were that account
    # reporting its own positions. A writer given those would be reading one person and calling
    # it what people are saying.
    by, seen = {'zh': [], 'en': []}, {}
    for r in rows:
        k = (r['lang'], r['handle'])
        if seen.get(k, 0) >= 2:
            continue
        if len(by[r['lang']]) < per_side:
            by[r['lang']].append(r)
            seen[k] = seen.get(k, 0) + 1
    return {
        'entity': entity, 'window_days': days,
        'zh': by['zh'], 'en': by['en'],
        'matched': len(rows),
        'packet_claimed': len(claimed),
        'packet_claimed_dropped_as_irrelevant': dropped_claimed,
        'note': ('opinions to reason from and argue with, not a digest to summarise; '
                 'same-language wording may not be carried'),
    }


def _lines(rows):
    return '\n'.join(
        f"  · @{r['handle']}（{r['at'][:10]}）：{r['text'][:EXCERPT_CHARS]}" for r in rows)


def prompt_block(op, lang='zh'):
    """The excerpts as the writer sees them, with the carrying rule for its own language."""
    zh, en = op.get('zh') or [], op.get('en') or []
    if not (zh or en):
        return ''
    if lang == 'zh':
        # The rule differs by the draft's language, not by the source's, which is why this is
        # built per draft rather than once per event.
        head = ('\n【这件事上，被关注的人在说什么】\n'
                '下面是最近这些账号自己写的东西。读它们是为了知道别人怎么想、'
                '哪里有分歧、你同不同意——不是为了总结它们。\n'
                '  · 中文的几条：可以据其内容推理，但**一个词组都不要搬**，'
                '句式和论证顺序也不要学。同语言搬运一律禁止。\n'
                '  · 英文的几条：信息可以用，必须用你自己的中文重写，并写明是英文那边的说法。\n'
                '  · 你可以明确不同意其中某个说法，并说出为什么——这比复述有用。\n')
        parts = []
        if zh:
            parts.append(f'\n中文（只读，不得搬用措辞）：\n{_lines(zh)}\n')
        if en:
            parts.append(f'\n英文（可据内容推理，须用中文自己写并注明来源侧）：\n{_lines(en)}\n')
    else:
        head = ('\n[What the accounts we follow are saying about this]\n'
                'These are recent posts by those accounts. Read them to know what others think, '
                'where they disagree, and whether you agree — not to summarise them.\n'
                '  · The English ones: reason from them, but do **not** lift a phrase, a sentence '
                'shape or the order of an argument. Same-language carrying is forbidden.\n'
                '  · The Chinese ones: the information may be used, written in your own English '
                'and attributed to the Chinese-language side.\n'
                '  · Disagreeing with one of these explicitly, and saying why, is worth more than '
                'restating it.\n')
        parts = []
        if en:
            parts.append(f'\nEnglish (read only, do not reuse wording):\n{_lines(en)}\n')
        if zh:
            parts.append(f'\nChinese (reason from, write your own English, attributed):\n'
                         f'{_lines(zh)}\n')
    return head + ''.join(parts)


# The sample is twelve handles. Writing 「英文社区」 turns it into a community, which is the same
# error as 「英文侧最早提及领先134.3小时」 with the number removed: a property of our collection
# stated as a property of the world. Withholding the counts did not stop it — the first draft
# written after that change still opened a sentence with 「英文社区最近更多在讲」.
OVERCLAIM = {
    # 「市场共识」「所有人都」被移出：这些是真人常用的修辞，误伤 0.6%。
    # 留下的是**我们特有的**那个错误——把这 12 个账号说成一个语言社区。
    # 真人不会写「英文社区最近更多在讲」，因为他们没有一份观察名单。
    'zh': re.compile(r'英文社区|中文社区|英文圈普遍|中文圈普遍|英文侧最早|中文侧最早'),
    'en': re.compile(r'the (?:English|Chinese)[- ]speaking (?:community|market)|'
                     r'everyone (?:is|has)|the (?:whole|entire) market|'
                     r'Wall Street (?:generally|broadly)|the consensus is',
                     re.I),
}
OVERCLAIM_FIX = {
    'zh': ('不要写「英文社区」「市场共识」这种口径。我们看到的是十几个账号，'
           '不是一个社区，也不是整个市场。写「我关注的几个英文账号」「@某某这几天在讲」，'
           '或者干脆点名是谁说的。'),
    'en': ('Do not write "the English-speaking community" or "the consensus". What we have is a '
           'dozen handles, not a community. Name the accounts, or say "the English-language '
           'accounts I follow".'),
}


def overclaim_check(text, lang='zh'):
    """Blocking: a claim about a community or a market, drawn from a watchlist of twelve."""
    pat = OVERCLAIM.get('zh' if str(lang).startswith('zh') else 'en')
    hits = sorted({m.group(0) for m in pat.finditer(text or '')})
    return {'findings': [{'code': 'watchlist_stated_as_market', 'severity': 'blocking',
                          'detail': f'{hits} — {OVERCLAIM_FIX["zh" if str(lang).startswith("zh") else "en"]}'}]
                        if hits else [],
            'blocking_count': 1 if hits else 0,
            'hits': hits,
            'status': 'failed' if hits else 'passed',
            'check_version': 'overclaim-v1'}


def overclaim_faults(result, lang='zh'):
    k = 'zh' if str(lang).startswith('zh') else 'en'
    return [OVERCLAIM_FIX[k]] if result.get('hits') else []


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    entity = args.get('entity')
    if not isinstance(entity, str):
        raise SystemExit('用法: python -B live/opinions.py --entity=\\$NVDA [--days=14]')
    op = gather(entity, days=int(args.get('days', WINDOW_DAYS)))
    print(f"{entity}：{op['window_days']} 天内匹配 {op['matched']} 条  "
          f"中文 {len(op['zh'])} / 英文 {len(op['en'])}")
    if op['packet_claimed_dropped_as_irrelevant']:
        print(f"  事实包 signal_posts 里有 {op['packet_claimed_dropped_as_irrelevant']} 条"
              f"与该标的无关，已剔除")
    print(prompt_block(op, 'zh')[:1800])


if __name__ == '__main__':
    main()
