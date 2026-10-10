"""Per-account line-end punctuation habit (Fiona Oct 10).

Many real posters do not end every line with 。/. ; our drafts did. This module
1) measures, from donor originals (live/donors/posts, local only), how each line and the final line of a post end
   (。 . ！ ! ？ ? … emoji, colon, comma, other, none), split zh / en, per donor and per account cluster
   (the same weighted sample as live/language_habits.cluster_posts, raw text so URL-only lines are skipped,
   not counted as "none");
2) stores only aggregates in live/donors/line_end_stats.json (no donor text) and in the local language_habits card;
3) at compose time strips trailing 。/. from lines deterministically (hash of draft id + line) so the account's
   share of period-ended lines follows its donors. Only a trailing 。 or a single trailing . is ever removed:
   never ? ! … / "...", never an abbreviation (U.S. e.g. etc. Inc.), a bare list marker ("1."), a URL or ticker.
FD_LINE_END=0 turns the compose post-processor off.
"""
from __future__ import annotations

import collections
import json
import os
import re
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATS = ROOT / 'donors' / 'line_end_stats.json'
CJK = re.compile(r'[一-鿿]')
_URL_TAIL = re.compile(r'(?:\s*(?:https?://\S+|pic\.twitter\.com/\S+))+\s*$')
_TAG_ONLY = re.compile(r'^(?:[@#$＄][\w.]+[\s,，、]*)+$')
_CLOSERS = ')）」』”"\'’》】]'
_EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0F\u200D\U000E0000-\U000E007F]')
CLASSES = ('period_zh', 'period_en', 'excl', 'question', 'ellipsis', 'emoji', 'colon', 'comma', 'other_punct', 'none')
_ABBR = re.compile(r'(?:\b(?:[A-Za-z]\.){2,}|\b(?:etc|Inc|Corp|Ltd|Co|vs|Jr|Sr|St|No|Mr|Mrs|Ms|Dr|Bros|approx|est|'
                   r'Jan|Feb|Mar|Apr|Aug|Sep|Sept|Oct|Nov|Dec|al|pp|ft|oz|Q[1-4])\.)$')
_LIST_MARK = re.compile(r'^\s*(?:\d{1,3}|[A-Za-z]|[ivx]{1,4})[.)]\s*$', re.I)


def lang_of(text):
    n = len(CJK.findall(text or ''))
    return 'zh' if n >= 15 else ('en' if n == 0 and len(text or '') >= 40 else None)


def _clean_line(line):
    s = _URL_TAIL.sub('', line).rstrip()
    return '' if not s or _TAG_ONLY.match(s) or re.fullmatch(r'https?://\S+', s) else s


def classify(line):
    s = line.rstrip()
    while s and s[-1] in _CLOSERS:
        s = s[:-1].rstrip()
    if not s:
        return 'none'
    c = s[-1]
    if s.endswith('...') or s.endswith('…') or s.endswith('。。'):
        return 'ellipsis'
    if c == '。' or c == '．':
        return 'period_zh'
    if c == '.':
        return 'period_en'
    if c in '!！':
        return 'excl'
    if c in '?？':
        return 'question'
    if _EMOJI.match(c):
        return 'emoji'
    if c in ':：':
        return 'colon'
    if c in ',，、;；':
        return 'comma'
    if c.isalnum() or CJK.match(c) or c in '%$＄+-–—~～' or c.isalpha():
        return 'none'
    return 'other_punct'


def post_lines(text):
    return [s for s in (_clean_line(ln) for ln in str(text or '').splitlines()) if s]


def _blank():
    return {'posts': 0, 'lines': collections.Counter(), 'final': collections.Counter()}


def _add(acc, text):
    lines = post_lines(text)
    if not lines:
        return
    acc['posts'] += 1
    for ln in lines:
        acc['lines'][classify(ln)] += 1
    acc['final'][classify(lines[-1])] += 1


def _rates(counter):
    n = sum(counter.values())
    return {k: round(counter[k] / n, 3) for k in CLASSES if counter.get(k)} if n else {}


def summarize(acc):
    """Aggregates only: shares by class, period rates, and the keep-probability compose uses."""
    lines, final = acc['lines'], acc['final']
    nl, nf = sum(lines.values()), sum(final.values())
    per = lambda c: c['period_zh'] + c['period_en']   # noqa: E731
    bare = lambda c: per(c) + c['none'] + c['emoji']   # noqa: E731
    return {
        'posts': acc['posts'], 'lines': nl,
        'line_end_mix': _rates(lines), 'final_line_mix': _rates(final),
        'line_end_period_rate': round(per(lines) / nl, 3) if nl else None,
        'final_line_period_rate': round(per(final) / nf, 3) if nf else None,
        # P(period | the line ends either with a period or bare / emoji): the only choice the post-processor edits.
        'line_period_keep': round(per(lines) / bare(lines), 3) if bare(lines) else None,
        'final_period_keep': round(per(final) / bare(final), 3) if bare(final) else None,
    }


def _originals(posts):
    return [p for p in posts if p.get('text') and not p.get('rt') and not p.get('reply') and not p.get('pinned')]


def _promo_free(text):
    from live.language_habits import _PROMO_LINE
    return '\n'.join(ln for ln in str(text).splitlines() if not _PROMO_LINE.search(_URL_TAIL.sub('', ln)))


def donor_stats(posts_dir=None):
    """{handle: {'zh': summary, 'en': summary}} over every local donor corpus."""
    base = Path(posts_dir or ROOT / 'donors' / 'posts')
    out = {}
    for f in sorted(base.glob('*.jsonl')):
        accs = {'zh': _blank(), 'en': _blank()}
        handle = None
        for raw in f.read_text(errors='replace').splitlines():
            try:
                p = json.loads(raw)
            except ValueError:
                continue
            handle = handle or p.get('handle') or p.get('user') or None
            if not _originals([p]):
                continue
            text = _promo_free(p['text'])
            lg = lang_of(text)
            if lg:
                _add(accs[lg], text)
        out[f.stem] = {lg: summarize(a) for lg, a in accs.items() if a['posts']}
    return out


def cluster_stats(persona, posts_dir=None):
    """Weighted cluster sample (same quotas as language_habits.cluster_posts), in the account's language."""
    from live.exemplars import load_posts
    from live.language_habits import SAMPLE_TOTAL
    acc, per_donor = _blank(), {}
    for handle, weight in (getattr(persona, 'donor_weights', {}) or {}).items():
        try:
            posts = load_posts(handle, posts_dir)
        except Exception:   # noqa: BLE001 - donor corpus missing locally
            continue
        rows = [dict(p, text=_promo_free(p['text'])) for p in _originals(posts)]
        rows = [p for p in rows if lang_of(p['text']) == persona.lang]
        rows.sort(key=lambda p: str(p.get('id')), reverse=True)
        d = _blank()
        for p in rows[:max(20, int(round(weight * SAMPLE_TOTAL)))]:
            _add(acc, p['text'])
            _add(d, p['text'])
        if d['posts']:
            s = summarize(d)
            per_donor[handle] = {k: s[k] for k in ('posts', 'line_end_period_rate', 'final_line_period_rate')}
    return dict(summarize(acc), lang=persona.lang, donors=per_donor)


def build_all(posts_dir=None, personas=None):
    from live import registry
    personas = personas if personas is not None else registry.load_personas()
    items = personas.values() if isinstance(personas, dict) else personas
    donors = donor_stats(posts_dir)
    accounts = {}
    for p in sorted(items, key=lambda x: x.persona_id):
        s = cluster_stats(p, posts_dir)
        if s['posts']:
            s['by_lang'] = _pooled(donors, p.donor_weights)
            accounts[p.persona_id] = s
    return {'version': '1', 'built_by': 'live/line_end.py (Fiona 2026-10-10)',
            'method': ('originals only, promo lines dropped, trailing URLs / tag-only lines skipped; one line = one '
                       'non-empty line; final = last such line; zh post >= 15 CJK chars, en post 0 CJK and >= 40 chars; '
                       'account = weighted donor cluster sample in the account language (language_habits quotas). '
                       'period = 。 or single . (… / ... counted as ellipsis). keep = period / (period + none + emoji).'),
            'use': 'line-end punctuation habit only; aggregates, no donor text',
            'accounts': accounts, 'donors': donors}


def _pooled(donors, handles):
    """All originals of the cluster's donors pooled per language (unweighted): {lang: {period rates, lines}}."""
    low = {k.lower(): v for k, v in donors.items()}
    out = {}
    for lg in ('zh', 'en'):
        nl = nf = pl = pf = 0
        for h in handles:
            s = (low.get(h.lower()) or {}).get(lg)
            if not s or not s['lines']:
                continue
            nl += s['lines']
            nf += s['posts']
            pl += s['line_end_period_rate'] * s['lines']
            pf += (s['final_line_period_rate'] or 0) * s['posts']
        if nl:
            out[lg] = {'lines': nl, 'posts': nf, 'line_end_period_rate': round(pl / nl, 3),
                       'final_line_period_rate': round(pf / nf, 3)}
    return out


_PROFILE_CACHE = {}


def profile(persona_or_id, lang=None):
    """The account's stored habit ({line_period_keep, final_period_keep, ...}) or None."""
    pid = getattr(persona_or_id, 'persona_id', persona_or_id)
    path = Path(os.environ.get('FD_LINE_END_STATS') or STATS)
    key = (str(path), path.stat().st_mtime if path.exists() else 0)
    if _PROFILE_CACHE.get('key') != key:
        try:
            _PROFILE_CACHE.update(key=key, data=json.loads(path.read_text()).get('accounts') or {})
        except (OSError, ValueError):
            _PROFILE_CACHE.update(key=key, data={})
    return _PROFILE_CACHE['data'].get(pid)


def enabled():
    return os.environ.get('FD_LINE_END', '1') != '0'


def _u(seed, line, k):
    h = sha256(f'{seed}\x00{line.strip()}\x00{k}'.encode('utf-8')).hexdigest()
    return int(h[:12], 16) / float(1 << 48)


def _strippable(line):
    """Index of the trailing 。/. to drop, or None when the period must stay."""
    s = line.rstrip()
    j = len(s)
    while j and s[j - 1] in _CLOSERS:
        j -= 1
    core = s[:j]
    if not core or len(CJK.findall(core)) + len(re.findall(r'[A-Za-z]', core)) < 2:
        return None
    c = core[-1]
    if c in '。．':
        if core.endswith('。。'):
            return None
        return j - 1
    if c != '.':
        return None
    if core.endswith('..') or _LIST_MARK.match(core) or _ABBR.search(core):
        return None
    tok = core.split()[-1] if core.split() else core
    if re.search(r'https?://|www\.|\.(?:com|io|xyz|org|net|ai|fi)\.$', tok, re.I) or re.match(r'^[$＄#@]', tok):
        return None
    if re.search(r'\d\.$', tok) and not re.search(r'[A-Za-z%一-鿿]', tok[:-1].lstrip('$')):
        # "5." / "3.2." at the end: fine to drop unless the whole line is a number list marker (handled above)
        return j - 1
    return j - 1


def apply(text, persona_or_id, seed, *, lang=None, final=True, prof=None):
    """Drop trailing 。/. per line with the account's donor keep-rate. Deterministic for (seed, line text)."""
    if not text or not enabled():
        return text
    prof = prof if prof is not None else profile(persona_or_id)
    if not prof or prof.get('line_period_keep') is None:
        return text
    keep_line = prof['line_period_keep']
    keep_final = prof.get('final_period_keep')
    keep_final = keep_line if keep_final is None else keep_final
    lines = text.split('\n')
    idx = [i for i, ln in enumerate(lines) if _clean_line(ln)]
    last = idx[-1] if idx and final else None
    seen = collections.Counter()
    for i in idx:
        ln = lines[i]
        cut = _strippable(ln)
        if cut is None:
            continue
        key = ln.strip()
        seen[key] += 1
        keep = keep_final if i == last else keep_line
        if _u(seed, key, seen[key]) >= keep:
            s = ln.rstrip()
            lines[i] = s[:cut] + s[cut + 1:] + ln[len(s):]
    return '\n'.join(lines)


def apply_parts(parts, persona_or_id, seed, prof=None):
    """Thread parts: same per-line decisions as on the joined body (only the very last line is 'final')."""
    out = []
    for k, part in enumerate(parts):
        out.append(apply(part, persona_or_id, seed, final=(k == len(parts) - 1), prof=prof))
    return out


def prompt_habit(persona_or_id):
    """Short persona-prompt line describing the habit, or None."""
    prof = profile(persona_or_id)
    if not prof or prof.get('line_end_period_rate') is None:
        return None
    lr, fr = prof['line_end_period_rate'], prof['final_line_period_rate']
    zh = prof.get('lang') == 'zh'
    mark = '。' if zh else '.'
    return {'line_end_period_rate': lr, 'final_line_period_rate': fr,
            'guidance': (f'Line-end habit of this account\'s donors: about {round(lr * 100)}% of lines and '
                         f'{round((fr or 0) * 100)}% of final lines end with "{mark}". '
                         + ('Most lines end bare (no period); a line break already ends the thought. ' if lr < 0.35 else
                            'Periods at line ends are common but not on every line. ' if lr < 0.7 else
                            'Lines usually end with a period. ')
                         + 'Keep ? and ! where meant; never drop periods inside a line, in numbers or abbreviations.')}


if __name__ == '__main__':
    import sys
    data = build_all()
    STATS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    print('accounts', len(data['accounts']), 'donors', len(data['donors']), file=sys.stderr)
