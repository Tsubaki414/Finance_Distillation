"""Deterministic naturalness post-processors: A5 lens-jargon, A9 number rounding guard,
A10 EN LLM-ism / em-dash (nat-tex, Oct 10 2026).

Called from live/humanize.apply() after all existing transforms.
Kill switches (default 1 = on):
  FD_NAT_JARGON=0   — skip A5 jargon rewrite
  FD_NAT_ROUND=0    — skip A9 number rounding (gate in humanize.py)
  FD_NAT_LLMISM=0   — skip A10 LLM-ism / em-dash rewrite

All transforms are soft-only: they never HOLD or block a draft.
No paid LLM calls; all deterministic regex rewrites.
"""
from __future__ import annotations

import os
import re
from hashlib import sha256
from typing import Any

# ------------------------------------------------------------------ kill switches

def jargon_enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_NAT_JARGON', '1') != '0'

def round_enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_NAT_ROUND', '1') != '0'

def llmism_enabled(env: dict | None = None) -> bool:
    return (env or os.environ).get('FD_NAT_LLMISM', '1') != '0'

# ------------------------------------------------------------------ deterministic seed helper

def _u(draft_id: str, tag: str, n: int = 0) -> float:
    h = sha256(f'{draft_id}\x00{tag}\x00{n}'.encode()).hexdigest()
    return int(h[:12], 16) / float(1 << 48)

# ================================================================== A5 — lens-jargon budget
#
# Donor audit (nat1010 metrics.py, 180 drafts vs ~5500 donor posts):
#   ZH: 流动性 30 % drafts vs 5 % donors, 宏观 14 % vs 2 %, 底层 16 % vs 2 %, 筹码 17 % vs 2.5 %
#   EN: structur* 29 % vs 4.6 %, liquidity 22 % vs 5 %, capital 16 % vs 4 %
#
# Strategy: per-account soft budget from donor_rates if available, else hard cap of 1.
# Soft-rewrite the offending sentence once; if still over, warn but never HOLD.
# Never invent replacement text — strip or paraphrase the lens word only.

# Words that are the "lens label" itself and not a quoted number / source term
_JARGON_ZH = re.compile(
    r'(流动性|宏观(?!经济数据|政策背景|调控)|底层(?!技术|框架)|筹码(?!分析)|结构性?(?!机会|调整|性问题))'
)
_JARGON_EN = re.compile(
    r'\b(structural(?:ly)?|liquidity|macro(?:\s+(?:backdrop|headwind|tailwind|picture|environment|conditions?))?'
    r'|capital\s+flows?)\b',
    re.I,
)

# Patterns that mean the word IS the content, not a lens label
# e.g. "liquidity of $2.4B", "capital flows into X", "结构性机会"
_JARGON_SAFE_ZH = re.compile(r'(流动性\s*(?:危机|枯竭|溢出|约束|紧缩|宽松|规模)|底层\s*(?:技术|架构|协议)|筹码\s*(?:分析|集中度))')
_JARGON_SAFE_EN = re.compile(
    r'((?:of|in|with|inject|add|drain|remove|provide|pull|boost)\s+(?:\$|USD)?\d|'
    r'capital\s+flows?\s+(?:into|out\s+of|from|toward|data|report)|'
    r'structural\s+(?:reform|deficit|surplus|shift|change|unemployment|break))',
    re.I,
)

# Sentence-level split (zh or en)
_SENT_SPLIT_ZH = re.compile(r'(?<=[。！？!?])\s*')
_SENT_SPLIT_EN = re.compile(r'(?<=[.!?])\s+(?=[A-Z"])')

# Strip patterns — drop the lens word and surrounding filler
_STRIP_ZH = {
    '流动性': re.compile(r'(?:宏观)?流动性(?:\s*(?:环境|状况|因素|压力|传导|背景))?'),
    '宏观': re.compile(r'宏观(?:\s*(?:环境|层面|背景|因素|压力|政策|形势|走势|驱动))?'),
    '底层': re.compile(r'底层(?:\s*逻辑)?'),
    '筹码': re.compile(r'筹码(?:\s*(?:结构|分布|面|集中))?'),
    '结构': re.compile(r'(?:底层|深层)?结构(?:性)?(?:\s*(?:问题|矛盾|变化|调整|因素))?'),
}
_STRIP_EN = {
    'structural': re.compile(r'\b(?:the\s+)?structural(?:ly)?\s*(?:story|shift|backdrop|driver|concern|issue|picture)?\b', re.I),
    'liquidity': re.compile(r'\b(?:macro\s+)?liquidity\s*(?:conditions?|environment|backdrop|picture)?\b', re.I),
    'macro': re.compile(r'\bmacro\s*(?:backdrop|headwind|tailwind|picture|environment|conditions?)?\b', re.I),
    'capital': re.compile(r'\bcapital\s+flows?\b', re.I),
}


def _count_jargon(text: str, lang: str) -> int:
    rx = _JARGON_ZH if lang == 'zh' else _JARGON_EN
    safe = _JARGON_SAFE_ZH if lang == 'zh' else _JARGON_SAFE_EN
    # subtract safe uses
    total = len(rx.findall(text))
    safe_count = len(safe.findall(text))
    return max(0, total - safe_count)


def _strip_jargon_word(word: str, sentence: str, lang: str) -> str:
    """Remove one jargon word/phrase from a sentence. Returns cleaned sentence."""
    strips = _STRIP_ZH if lang == 'zh' else _STRIP_EN
    key = word.lower()
    # find the best strip pattern
    rx = None
    for k, v in strips.items():
        if lang == 'zh' and k in word:
            rx = v
            break
        if lang == 'en' and key.startswith(k):
            rx = v
            break
    if rx is None:
        # fallback: delete exact match
        rx = re.compile(re.escape(word), re.I)
    cleaned = rx.sub('', sentence).strip()
    # repair double spaces, leading conjunctions
    cleaned = re.sub(r'  +', ' ', cleaned)
    cleaned = re.sub(r'^[,，、。\s]+', '', cleaned)
    cleaned = re.sub(r'[,，、]\s*$', '', cleaned)
    return cleaned.strip()


def _rewrite_sentence_jargon(sentence: str, lang: str) -> str:
    """Strip one jargon hit from sentence. If still over, strip the second too."""
    rx = _JARGON_ZH if lang == 'zh' else _JARGON_EN
    safe = _JARGON_SAFE_ZH if lang == 'zh' else _JARGON_SAFE_EN
    count = 0
    result = sentence
    for m in rx.finditer(sentence):
        # skip safe uses
        ctx = sentence[max(0, m.start()-15):m.end()+15]
        if safe.search(ctx):
            continue
        count += 1
        if count > 2:
            break
        result = _strip_jargon_word(m.group(0), result, lang)
    return result


def apply_jargon(body: str, lang: str, draft_id: str, donor_budget: int = 1) -> tuple[str, list[str]]:
    """A5: reduce lens-jargon toward donor_budget. Soft only — warns, never HOLDs.

    donor_budget: max allowed lens-word occurrences (from donor_rates or default 1).
    Returns (new_body, list_of_change_notes).
    """
    if not jargon_enabled():
        return body, []

    hits = _count_jargon(body, lang)
    if hits <= donor_budget:
        return body, []

    # rewrite sentence by sentence
    splitter = _SENT_SPLIT_ZH if lang == 'zh' else _SENT_SPLIT_EN
    sentences = splitter.split(body)
    changes: list[str] = []
    rewrites = 0
    # rebuild with rewrites
    new_sentences = []
    for s in sentences:
        s_hits = _count_jargon(s, lang)
        if s_hits > 0 and rewrites < (hits - donor_budget):
            before = s
            s = _rewrite_sentence_jargon(s, lang)
            if s != before:
                rewrites += 1
                changes.append(f'jargon: rewrote sentence (removed {s_hits} lens word(s))')
        new_sentences.append(s)
    new_body = ''.join(new_sentences) if lang == 'zh' else ' '.join(new_sentences)

    # verify: if still over budget, just warn (never HOLD)
    remaining = _count_jargon(new_body, lang)
    if remaining > donor_budget:
        changes.append(f'jargon: {remaining} lens word(s) remain after rewrite (soft warning)')

    return new_body, changes


# ================================================================== A10 — EN LLM-ism blocklist + em-dash
#
# Audit (llm_out.json, 92 EN drafts):
#   "I'm not convinced" 4 accounts, "So much for" 3, "That's the structural story" / building 2-3,
#   "Make no mistake" 3, em-dash density ~0.6/post vs donors ~0.1/post.
#
# Blocklist: exact phrase → replacement or delete.
# Em-dash: swap "—" for ", " or " – " when density > donor rate.

_LLMISM_EN: list[tuple[re.Pattern[str], str]] = [
    # sober reminder
    (re.compile(r'\bsober reminder\b', re.I),                     'reminder'),
    # structural story variants
    (re.compile(r"\b[Tt]hat['']s\s+the\s+structural\s+story\b"),  "That's the picture"),
    (re.compile(r'\bthe\s+structural\s+story\s+(?:keeps?\s+)?building\b', re.I), 'the picture keeps building'),
    (re.compile(r'\bstructural\s+story\b', re.I),                  'story'),
    # The question is whether
    (re.compile(r'\b[Tt]he\s+question\s+is\s+whether\b'),         'Whether'),
    (re.compile(r'\b[Tt]he\s+question\s+(?:now\s+)?is\b'),        'The issue'),
    # So much for
    (re.compile(r'\b[Ss]o\s+much\s+for\b'),                       'Forget'),
    # Here's the thing
    (re.compile(r"\b[Hh]ere['']s\s+the\s+thing(?:\s*[:\-])?\s*"), ''),
    # Make no mistake
    (re.compile(r'\b[Mm]ake\s+no\s+mistake(?:\s*[:\-])?\s*'),     ''),
    # Let that sink in
    (re.compile(r'\b[Ll]et\s+that\s+sink\s+in\.?\s*'),            ''),
    # I'm not convinced by/that
    (re.compile(r"\b[Ii]['']m\s+not\s+convinced\s+(?:by|that)\b"), "I doubt"),
    (re.compile(r"\b[Ii]['']m\s+not\s+convinced\b"),               "I doubt this"),
    # at its core
    (re.compile(r'\bat\s+its\s+core[,.]?\s*', re.I),              ''),
    # the real story (when used as LLM filler)
    (re.compile(r'\bthe\s+real\s+story\s+(?:here\s+)?is\b', re.I), 'what matters is'),
    # It's not X, it's Y variants (only when comma-separated)
    (re.compile(r"\b[Ii]t['']s\s+not\s+\w[\w\s]{0,20},\s+it['']s\b"), "It's"),
    # Yes, X is tempting. But...
    (re.compile(r'\b[Yy]es,\s+\w[\w\s]{0,30}(?:is|are)\s+tempting\.\s+[Bb]ut\b'), 'But'),
]

_EMDASH_RX = re.compile(r'\s*—\s*')
_EMDASH_COUNT = re.compile(r'—')


def _donor_emdash_rate(rates: dict[str, Any]) -> float:
    """Donor em-dash rate from donor_rates. Fallback 0.1/post (audit: donors ~0.1/post)."""
    return float(rates.get('emdash_rate', 0.10))


def apply_llmism(body: str, lang: str, draft_id: str,
                 rates: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """A10: EN-only. Remove LLM stock phrases; reduce em-dash toward donor rate.

    Soft only — warns, never HOLDs.
    """
    if not llmism_enabled():
        return body, []
    if lang != 'en':
        return body, []

    changes: list[str] = []
    new_body = body

    # phrase substitutions
    for rx, replacement in _LLMISM_EN:
        prev = new_body
        new_body = rx.sub(replacement, new_body)
        if new_body != prev:
            # capitalise first word of sentence if replacement started a sentence
            new_body = re.sub(r'(?<=[.!?]\s)([a-z])', lambda m: m.group(1).upper(), new_body)
            # remove double spaces
            new_body = re.sub(r'  +', ' ', new_body)
            changes.append(f'llmism: removed phrase {rx.pattern!r:.50}')

    # em-dash density
    n_em = len(_EMDASH_COUNT.findall(new_body))
    words = len(new_body.split())
    if words > 0:
        post_rate = n_em / max(words / 15, 1)   # per ~15-word chunk, rough
        donor_rate = _donor_emdash_rate(rates or {})
        if n_em > 1 and post_rate > donor_rate * 1.5:
            # swap all-but-one em-dash for ", " or " - "
            # deterministically keep one if donor_rate > 0
            keep = 1 if donor_rate > 0.0 else 0
            count = [0]
            def _swap(m: re.Match) -> str:
                count[0] += 1
                if count[0] <= keep:
                    return m.group(0)
                # decide replacement: if preceded by a word and followed by a word → ", "
                return ', '
            replaced = _EMDASH_RX.sub(_swap, new_body)
            if replaced != new_body:
                new_body = replaced
                changes.append(f'llmism: reduced em-dash density ({n_em} → {keep})')

    # clean up any double spaces or leading/trailing spaces on lines
    new_body = re.sub(r'  +', ' ', new_body)
    new_body = '\n'.join(ln.strip() if ln.strip() else ln for ln in new_body.splitlines())

    return new_body, changes


# ================================================================== combined entry point

def apply(body: str, lang: str, draft_id: str,
          rates: dict[str, Any] | None = None,
          donor_jargon_budget: int | None = None) -> tuple[str, list[str]]:
    """Run A5 + A10 in sequence. A9 (FD_NAT_ROUND) is guarded in humanize.py.

    Returns (new_body, all_changes).
    """
    if rates is None:
        rates = {}
    all_changes: list[str] = []

    # A5 — jargon
    budget = donor_jargon_budget if donor_jargon_budget is not None else int(rates.get('jargon_budget', 1))
    body, chg = apply_jargon(body, lang, draft_id, donor_budget=budget)
    all_changes += chg

    # A10 — LLM-isms (EN only)
    body, chg = apply_llmism(body, lang, draft_id, rates=rates)
    all_changes += chg

    return body, all_changes
