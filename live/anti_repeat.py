"""Advisory style/history checks. History is local data, never publishing authority."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

HISTORY_DIR = Path('/workspace/x/fd_draft_history')
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
    for key in ('shape', 'skeleton'):   # structure-variety history (live/compose_shapes.py)
        if meta.get(key):
            row[key] = meta[key]
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


def findings(body, persona_id, *, units=None, stance=None, source=None, now=None, recent=None):
    out = [{'code': 'phrase_ban', 'detail': phrase} for phrase in ZH + EN if phrase.casefold() in body.casefold()]
    if re.search(r'这才是[^。！？\n]{1,30}的地方', body):
        out.append({'code': 'phrase_ban', 'detail': '这才是…的地方'})
    label = LABEL.search(body)
    if label:
        out.append({'code': 'judgment_label', 'detail': label.group(0).strip() or '我的判断：'})
    recent = load_recent(persona_id) if recent is None else recent
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
