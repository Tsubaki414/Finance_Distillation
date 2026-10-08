"""Advisory style/history checks. History is local data, never publishing authority."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

HISTORY_DIR = Path(os.environ.get('FD_DRAFT_HISTORY') or '/workspace/x/fd_draft_history')
FALLBACK_DIR = Path(__file__).resolve().parent / 'store' / 'recent_drafts'
ZH = ('还早着呢', '还要再看', '才是关键', '才值得看', '真正的核心', '真正的问题是', '这才是……的地方',
      '现在下结论还太早', '能不能守住', '链路往下推', '每一环的议价权', '这才是要分开看的地方')
EN = ('my read is that', 'the catch?', 'valuation-free', 'supply-discipline check',
      'Calling a strong chance', 'is a start.', 'is a start', 'That said,', 'before that door closes',
      'that door closes')
# Judgment glue labels (same family): 我的判断： / 以我个人判断(，) / 个人判断：
LABEL = re.compile(r'(?m)^\s*(?:我的判断|我?个人判断)(?:\s*[：:]\s*|[ \t]+)'
                   r'|以我个人判断\s*[，,：:]?\s*'
                   r'|(?:我的|我?个人)判断[：:]\s*')


def strip_judgment_label(body):
    cleaned, count = LABEL.subn('', body)
    return cleaned, bool(count)


def _path(persona_id, directory):
    if not re.fullmatch(r'[\w-]+', persona_id):
        raise ValueError('Invalid persona_id')
    return directory / (persona_id + '.jsonl')


def load_recent(persona_id, limit=30):
    for directory in (HISTORY_DIR, FALLBACK_DIR):
        path = _path(persona_id, directory)
        try:
            rows = []
            for line in path.read_text().splitlines():
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and isinstance(row.get('text'), str):
                        rows.append(row)
                except ValueError:
                    continue
            return rows[-limit:] if limit > 0 else []
        except OSError:
            continue
    return []


def load_same_day(exclude_persona=None, now=None):
    """Texts every OTHER persona recorded on the same UTC day as `now` (Oct 7 cross-account ending rule)."""
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now.replace('Z', '+00:00'))
        except ValueError:
            now = None
    now = now or datetime.now(timezone.utc)
    day = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date().isoformat()
    for directory in (HISTORY_DIR, FALLBACK_DIR):
        try:
            paths = sorted(directory.glob('*.jsonl'))
        except OSError:
            continue
        if not paths:
            continue
        out = []
        for path in paths:
            if path.stem == exclude_persona:
                continue
            try:
                lines = path.read_text().splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get('text'), str) and str(row.get('ts', ''))[:10] == day:
                    out.append(row['text'])
        return out
    return []


def topic(body, stance=None):
    stance = stance or {}
    subject = stance.get('subject') or (stance.get('view') or {}).get('subject')
    tickers = sorted(set(re.findall(r'\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b', body)))
    return str(subject or '').casefold(), sorted({a or b for a, b in tickers if a or b not in ('I', 'A')})


def record_draft(persona_id, text, *, meta=None):
    meta = meta or {}
    subject, tickers = topic(text, meta)
    row = {'ts': datetime.now(timezone.utc).isoformat(), 'text': text, 'subject': subject,
           'tickers': meta.get('tickers', tickers), 'closing': text.strip().splitlines()[-1][-40:] if text.strip() else ''}
    if meta.get('draft_id'):
        row['draft_id'] = meta['draft_id']
    for key in ('shape', 'post_format', 'skeleton', 'account_view', 'source_hash', 'source_title'):   # structure / theme history
        if meta.get(key):
            row[key] = meta[key]
    try:   # Oct 6 v10: event (news hook) of the draft, for selection's same-event dedupe
        from live import news_hook
        hooks = sorted(news_hook.hooks(' '.join(str(x or '') for x in (text, row.get('subject'), meta.get('source_title')))))
    except Exception:   # noqa: BLE001 - history writing never fails on hook tagging
        hooks = []
    if hooks:
        row['news_hooks'] = hooks
    rows = load_recent(persona_id, 29) + [row]
    for directory in (HISTORY_DIR, FALLBACK_DIR):
        path = _path(persona_id, directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
            return True
        except OSError:
            continue
    return False  # Storage failure must never stall compose.


def _style_tokens(text, units):
    # Strip bound metrics and source-supported fact vocabulary before forming grams.
    for unit in units or []:
        unit = unit.get('unit') or unit
        for number in unit.get('numbers') or []:
            metric = str(number.get('metric') or '')
            if metric:
                text = re.sub(re.escape(metric), ' ', text, flags=re.I)
    text = re.sub(r'\$?[A-Z]{1,5}\b|\d+(?:[.,:/%-]\d+)*%?', ' ', text)
    text = re.sub(r'\b(?:revenue|guidance|billion|million|growth|quarter|margin|earnings|USD)\b', ' ', text, flags=re.I)
    grams = {p.casefold() for p in ZH + EN if p.casefold() in text.casefold()}
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        for n in (4, 5, 6):
            grams.update(run[i:i+n] for i in range(len(run)-n+1))
    for run in re.split(r'[^a-zA-Z\s\']+', text):
        words = run.lower().split()
        grams.update(' '.join(words[i:i+3]) for i in range(len(words)-2))
    for unit in units or []:
        unit = unit.get('unit') or unit
        if unit.get('kind') == 'fact':
            evidence = str(unit.get('statement') or '') + ' ' + ' '.join(
                str(span.get('exact_text') or '') for span in unit.get('source_spans', []) if isinstance(span, dict))
            grams -= _style_tokens(evidence, [])
    return grams


def _closing(text, units):
    last = text.strip().splitlines()[-1][-40:] if text.strip() else ''
    return _style_tokens(last, units)


def verify_source(body, units=None, source=None):
    findings = []
    for unit in units or []:
        unit = unit.get('unit') or unit
        for number in unit.get('numbers') or []:
            metric = str(number.get('metric') or '')
            period = str(number.get('period') or '')
            if not re.search(r'revenue|guidance|营收|收入|指引', metric, re.I):
                continue
            if not re.search(r'quarter|Q[1-4]|季度', period, re.I):
                continue
            match = re.search(r'\$?([\d.]+)\s*(?:billion|B\b)', str(number.get('text')), re.I)
            usd = '$' in str(number.get('text')) or 'USD' in str(number.get('text')).upper() or number.get('currency') == 'USD'
            if match and usd and float(match[1]) >= 40:
                findings.append({'code': 'verify_source', 'detail': 'Quarterly USD revenue/guidance ≥ $40B: verify the original source; do not replace the number.'})
    blob = body + ' ' + json.dumps(units or [], ensure_ascii=False)
    if re.search(r'Micron|美光', blob, re.I) and re.search(r'61\.5\s*(?:billion|B\b)', blob, re.I) and re.search(r'revenue|guidance|营收|指引', blob, re.I):
        findings.append({'code': 'verify_source', 'detail': 'Micron $61.5B revenue/guidance requires a human source check.'})
    return findings[:1]


# PM relax 2026-10-05 eve: with < MIN_HISTORY prior bodies, history-based checks
# (stylistic_repeat / duplicate_topic) are skipped. A fresh persona or a fixture
# re-smoke otherwise matched its own first draft and triggered a false regenerate.
# phrase_ban / judgment_label / verify_source always run.
MIN_HISTORY = 3


# Oct 6 v5 PM: en_industry v5 "The open question is who actually captures the volume" repeated v4
# "But who actually captures the volume?" - not caught because the history had 2 rows (< MIN_HISTORY)
# and the 3-gram check is gated. phrase_repeat runs from the first prior draft, with longer grams
# (EN 5 words / ZH 6 chars), fact vocabulary removed, and skips drafts of the same source (re-smoke).
PHRASE_EN_WORDS = 5
PHRASE_ZH_CHARS = 6


def _phrase_grams(text, units):
    for unit in units or []:
        unit = unit.get('unit') or unit
        for number in unit.get('numbers') or []:
            metric = str(number.get('metric') or '')
            if metric:
                text = re.sub(re.escape(metric), ' ', text, flags=re.I)
    text = re.sub(r'\d+(?:[.,:/%-]\d+)*%?', ' ', text)
    grams = set()
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        n = PHRASE_ZH_CHARS
        grams.update(run[i:i + n] for i in range(len(run) - n + 1))
    for run in re.split(r"[^a-zA-Z\s']+", text):
        words = run.lower().split()
        n = PHRASE_EN_WORDS
        grams.update(' '.join(words[i:i + n]) for i in range(len(words) - n + 1))
    return grams


def phrase_repeat_findings(body, recent, units=None, source_hash=None):
    if not recent:
        return []
    grams = _phrase_grams(body, units)
    for unit in units or []:   # wording that comes from the evidence itself is not a style repeat
        unit = unit.get('unit') or unit
        evidence = str(unit.get('statement') or '') + ' ' + ' '.join(
            str(sp.get('exact_text') or '') for sp in unit.get('source_spans', []) if isinstance(sp, dict))
        grams -= _phrase_grams(evidence, [])
    for row in reversed(recent[-30:]):
        if source_hash and row.get('source_hash') == source_hash:
            continue
        if row.get('text', '').strip() == body.strip():
            continue
        shared = grams & _phrase_grams(row['text'], units)
        if shared:
            return [{'code': 'phrase_repeat', 'detail': f"phrase from a recent draft: {sorted(shared)[0]!r}"}]
    return []


# Theme repeat (v5 PM: zh_industry wrote 财富集中 again from a different source). Generic concept
# tokens do not count as a shared theme.
GENERIC_THEME = frozenset({'@path', '@rates', '@ai', '@expectations', '@outlook', 'market', 'marke'})
THEME_SUBJECT_MIN = 0.6
THEME_TEXT_MIN = 0.3
THEME_WINDOW = 3


def _theme(subject, text):
    from live.view_ledger import _tokens
    subj = _tokens(str(subject or '')) - GENERIC_THEME
    return subj, subj | (_tokens(str(text or '')) - GENERIC_THEME)


def _overlap_min(a, b):
    return len(a & b) / max(1, min(len(a), len(b))) if a and b else 0.0


_NOT_ENTITY = frozenset({'the', 'ai', 'us', 'u.s.', 'global', 'china', 'chinese', 'market', 'markets', 'equity',
                         'equities', 'year-on-year', 'near-term', 'long-term', 'sustainability', 'local'})


def lead_entity(subject):
    """Named lead entity of a subject ('Micron Technology AI memory ...' -> 'micron'), else ''.
    v6: a second Micron source (options implied move) shared no subject wording with the 8-K call."""
    words = re.findall(r"[A-Za-z][\w&.'-]+", str(subject or ''))
    if not words:
        return ''
    w = re.sub(r"(?:'s|’s)$", '', words[0])
    return '' if w.lower() in _NOT_ENTITY or not (w[0].isupper() and len(w) >= 3) else w.lower()


def theme_overlap(subject, text, row):
    """(subject overlap, subject+call overlap) between a call and a history row; the same named lead
    entity (company / central bank) counts as full subject overlap."""
    ent = lead_entity(subject)
    if ent and re.match(re.escape(ent) + r"\b", str(row.get('subject') or '').lower()):
        return 1.0, 1.0
    s1, t1 = _theme(subject, text)
    first = (row.get('text') or '').strip().splitlines()[0] if (row.get('text') or '').strip() else ''
    s2, t2 = _theme(row.get('subject'), row.get('account_view') or first)
    return round(_overlap_min(s1, s2), 2), round(_overlap_min(t1, t2), 2)


def theme_findings(stance, recent, n=THEME_WINDOW):
    """SOFT theme_repeat: this call's subject / entity strongly overlaps one of the persona's last n drafts."""
    stance = stance or {}
    subject = (stance.get('view') or {}).get('subject') or stance.get('subject')
    if not subject and not stance.get('account_view'):
        return []
    for row in reversed((recent or [])[-n:]):
        subj, text = theme_overlap(subject, stance.get('account_view'), row)
        if subj >= THEME_SUBJECT_MIN or text >= THEME_TEXT_MIN:
            link = (stance.get('continuity') or {}).get('link')
            return [{'code': 'theme_repeat',
                     'detail': f"same theme as recent draft ({row.get('subject') or row.get('text', '')[:40]}); "
                               f"subject overlap {subj}, call overlap {text}" + (f"; ledger link: {link}" if link else '')}]
    return []


def findings(body, persona_id, *, units=None, stance=None, source=None, now=None, recent=None):
    out = [{'code': 'phrase_ban', 'detail': phrase} for phrase in ZH + EN if phrase.casefold() in body.casefold()]
    if re.search(r'这才是[^。！？\n]{1,30}的地方', body):
        out.append({'code': 'phrase_ban', 'detail': '这才是…的地方'})
    label = LABEL.search(body)
    if label:
        out.append({'code': 'judgment_label', 'detail': label.group(0).strip() or '我的判断：'})
    recent = load_recent(persona_id) if recent is None else recent
    out += phrase_repeat_findings(body, recent, units, (source or {}).get('source_hash'))
    if len(recent) < MIN_HISTORY:
        return out + verify_source(body, units, source)
    grams, closing = _style_tokens(body, units), _closing(body, units)
    for row in recent[-30:]:
        old = row['text']
        old_closing = _closing(old, units)
        shared = grams & _style_tokens(old, units)
        union = closing | old_closing
        if shared or (union and len(closing & old_closing) / len(union) >= .7):
            out.append({'code': 'stylistic_repeat', 'detail': sorted(shared)[:3] or 'Similar closing'})
            break
    if recent:
        previous = recent[-1]
        try:
            ts = datetime.fromisoformat(previous['ts'].replace('Z', '+00:00'))
            ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            current = now or datetime.now(timezone.utc)
            current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
            subject, tickers = topic(body, stance)
            prior_tickers = set(previous.get('tickers', []))
            ticker_union = set(tickers) | prior_tickers
            overlap = bool(subject and subject == previous.get('subject')) or bool(
                ticker_union and len(set(tickers) & prior_tickers) / len(ticker_union) >= .7)
            advances = re.search(r'但是|不过|最新|继续|接着|相比|\b(?:update|now|vs|previous|since|following)\b', body, re.I)
            if timedelta(0) <= current - ts <= timedelta(hours=36) and overlap and not advances:
                out.append({'code': 'duplicate_topic', 'detail': subject or tickers})
        except (ValueError, KeyError, TypeError):
            pass
    return out + verify_source(body, units, source)
