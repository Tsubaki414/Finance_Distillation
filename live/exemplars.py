"""Exemplar retrieval: real donor posts per persona, for voice only (fd-phase0).

Donor posts live in live/donors/posts/<handle>.jsonl (one post per line:
id, created, text, lang, and reply / rt / quote flags), written by
scripts/scrape_donor_posts.py. The corpus is data and stays untracked.

retrieve() is deterministic and offline: candidates are the persona's roster
donors' own original posts in the persona language (no replies, no reposts),
optionally inside a length window for the post type; each is scored by donor
weight times lexical overlap with the query (the units being written about),
and at most one post per donor is returned so no single donor dominates.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

POSTS_DIR = Path(__file__).resolve().parent / 'donors' / 'posts'
CJK = re.compile(r'[\u4e00-\u9fff]')
WORD = re.compile(r'[A-Za-z][A-Za-z0-9$%.-]+')
URL = re.compile(r'https?://\S+')


def _lang(text):
    return 'zh' if len(CJK.findall(text)) * 5 >= len(text.strip()) else 'en'


def _tokens(text):
    text = (text or '').lower()
    zh = CJK.findall(text)
    return {a + b for a, b in zip(zh, zh[1:])} | {w for w in WORD.findall(text) if len(w) > 2}


def load_posts(handle, posts_dir=None):
    from live.voice_cards import load_posts as read_posts
    return read_posts(handle, posts_dir or POSTS_DIR)


def _usable(post, lang, window):
    if post.get('reply') or post.get('rt') or post.get('pinned'):
        return False
    text = URL.sub('', post.get('text') or '').strip()
    if len(text) < 40:
        return False
    if (post.get('lang') or _lang(text)) != lang and _lang(text) != lang:
        return False
    if window:
        size = len(re.sub(r'\s+', '', text))
        return window[0] <= size <= window[1]
    return True


def window_for(post_type, post_types=None):
    if not post_type:
        return None
    from live import registry
    spec = (post_types or registry.load_post_types())['post_types'][post_type]['length']
    if spec.get('follows_source') or spec.get('min') is None:
        return None
    return int(spec['min'] * 0.5), int(spec['max'] * 1.5)


def retrieve(persona, *, post_type=None, query='', k=3, posts_dir=None, post_types=None, tags_dir=None):
    from live.voice_cards import load_tags, excluded, promo_heavy
    from live import registry
    weights = persona.donor_weights
    donor_info = registry.load_donor_roster()['donors']
    tags_dir = tags_dir or Path(posts_dir or POSTS_DIR).parent / 'tags'
    window = window_for(post_type, post_types)
    q = _tokens(query)
    best = []
    for handle, weight in weights.items():
        if promo_heavy(donor_info.get(handle.lower(), {})):
            continue
        tags = load_tags(handle, tags_dir)
        eligible_posts = [p for p in load_posts(handle, posts_dir)
                          if _usable(p, persona.lang, None) and not excluded(p, tags.get(str(p.get('id')), {}))]
        matching = [p for p in eligible_posts if post_type and tags.get(str(p.get('id')), {}).get('post_type') == post_type]
        # Prefer the requested type even when its length needs a graceful fallback.
        pool = matching or eligible_posts
        posts = [p for p in pool if _usable(p, persona.lang, window)] or pool
        if not posts:
            continue
        scored = sorted(posts, key=lambda p: (-len(q & _tokens(p['text'])), str(p.get('id'))))
        top = scored[0]
        overlap = len(q & _tokens(top['text']))
        best.append((0 if matching else 1, -(weight * (1 + overlap)), handle.lower(), {'handle': handle, 'id': str(top.get('id')),
                                                                'text': URL.sub('', top['text']).strip()}))
    best.sort(key=lambda row: row[:3])
    return [row[3] for row in best[:k]]


def copied_phrases(body, texts, min_zh=15, min_en_words=8):
    """Long verbatim runs shared with an exemplar (style donors are not sources)."""
    findings = []
    flat = re.sub(r'\s+', '', body)
    words = body.lower().split()
    for t in texts:
        tf = re.sub(r'\s+', '', t)
        hit = None
        for i in range(0, max(len(tf) - min_zh + 1, 0)):
            chunk = tf[i:i + min_zh]
            if len(CJK.findall(chunk)) >= min_zh * 0.6 and chunk in flat:
                hit = chunk
                break
        if not hit:
            tw = t.lower().split()
            grams = {' '.join(tw[i:i + min_en_words]) for i in range(max(len(tw) - min_en_words + 1, 0))}
            hit = next((' '.join(words[i:i + min_en_words]) for i in range(max(len(words) - min_en_words + 1, 0))
                        if ' '.join(words[i:i + min_en_words]) in grams), None)
        if hit:
            findings.append({'code': 'exemplar_phrase_copied', 'detail': hit[:60]})
    return findings
