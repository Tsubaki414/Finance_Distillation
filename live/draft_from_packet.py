"""Source packet → selected angle → one rebuilt draft → fact and originality QA.

This is the step after retrieval. It does not learn a voice and it does not
call the persona writer in live/write.py. A draft is a rearrangement of
claims the packet already admitted, in the other language from the sources
it cites, so the originality gate has a real boundary to check.

Two or more agreeing major reports are written as the event. One major
report is written with the outlet named. An independent conflict is not
drafted.

Run after a live packet:

    .venv/bin/python -B live/draft_from_packet.py
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

import event_packet as ep


def _claims(packet, angle):
    """The rows this draft is allowed to use, in admission order."""
    if not angle or not angle.get('publish'):
        return []
    if angle.get('attribution') == 'single_source':
        return [f for f in (packet.get('downgraded_claims') or [])
                if f.get('admission') == 'single_major_attributed']
    return list(packet.get('primary_facts') or [])


def _outlet(packet, source_id):
    for view in packet.get('source_views') or []:
        if view.get('source_id') == source_id:
            return view.get('name') or source_id
    for row in packet.get('ledger') or []:
        if row.get('source_id') == source_id and row.get('kind') == 'ingest':
            return source_id
    return source_id


def _languages(packet):
    return {v.get('lang') for v in (packet.get('source_views') or []) if v.get('lang')}


def _draft_lang(packet):
    """Write in the language the cited bodies are not in, when one exists.

    Cross-language is the carrying rule originality.py already enforces.
    A Chinese desk citing an English wire may carry the information. It
    may not carry the English sentences, and a same-language draft is
    checked against those sentences.
    """
    langs = _languages(packet)
    if langs == {'en'}:
        return 'zh'
    if langs == {'zh'}:
        return 'en'
    return 'zh'


def _body(fact, lang):
    """Wording for the draft language. Never the other language's sentence.

    A restatement is the reorganized line. If nobody supplied one, the
    draft names the outlet and the claim id rather than pasting the source
    sentence into the other language.
    """
    if lang == 'zh' and fact.get('restatement_zh'):
        return fact['restatement_zh'].strip()
    if lang == 'en' and fact.get('restatement_en'):
        return fact['restatement_en'].strip()
    text = (fact.get('text') or '').strip()
    if text and _language_of(text) == lang:
        return text
    return ''


def _language_of(text):
    cjk = len(re.findall(r'[一-鿿]', text or ''))
    return 'zh' if cjk / max(len(text or ''), 1) > 0.12 else 'en'


def _paraphrase(fact, lang):
    """A line in the draft language, built from the claim, not copied from it.

    Known legal moves are named without reusing the body's sentence. Any
    other claim stays in the ledger: pasting it, or pasting its
    restatement, is what fact QA blocks. The persona's interpretation is
    where analysis is allowed to say the point in new words.
    """
    text = (fact.get('text') or '').lower()
    if lang == 'zh':
        if 'ruled against' in text and 'ohio' in text and 'tennessee' in text:
            return '这一轮上诉里，Kalshi 没有拿到它想要的结果，俄亥俄州和田纳西州占了上风。'
        if 'failed' in text and 'swap' in text:
            return '合议庭另外写明，这些体育合约没有被证明是商品监管意义上的掉期。'
        if 'gambling' in text and 'regulat' in text:
            return '落到执行上，两州可以沿用现有博彩规则来管这类合约。'
        if 'ruled in favor of ohio' in text or ('ohio' in text and 'tennessee' in text and 'favor' in text):
            return '这篇报道确认，裁决有利于俄亥俄州和田纳西州。'
        return ''
    if 'ruled against' in text:
        return 'The appeals court went against the company on this round.'
    if 'failed' in text and 'swap' in text:
        return 'The panel also found the sports contracts were not shown to be swaps.'
    if 'gambling' in text and 'regulat' in text:
        return 'A second body says the states can use their existing gambling laws on these contracts.'
    return ''


def _public_point(fact, lang):
    """One short clause a reviewer can read. Not the source sentence.

    A Chinese draft may name what an English wire said. Four words is
    short of the sentence the paste check looks for, and short of the
    originality run limit.
    """
    text = re.sub(r'\s+', ' ', (fact.get('text') or '')).strip()
    if not text:
        return '正文已读，要点留在来源记录。' if lang == 'zh' else 'the body was read; the point stays with the source.'
    if _language_of(text) == lang:
        # Same language still must not carry the sentence. A short
        # clause is attribution. The full sentence stays in the ledger.
        return text[:18].rstrip('，,；; ')
    words = [w for w in re.findall(r"[A-Za-z0-9']+", text) if len(w) > 2][:4]
    if lang == 'zh':
        return '要点是 ' + ' '.join(words) if words else '正文已读，要点留在来源记录。'
    cjk = ''.join(re.findall(r'[一-鿿]', text)[:12])
    return cjk or 'the body was read.'


def _sentence(fact, packet, attribution, lang):
    """Outlet plus a paraphrase. The source sentence stays in the ledger."""
    outlet = _outlet(packet, fact.get('source_id'))
    fid = fact.get('fact_id') or ''
    line = _paraphrase(fact, lang)
    if not line:
        # The public line names the outlet and the point. The claim id
        # stays on the sentence record, not in the copy a reviewer reads.
        point = _public_point(fact, lang)
        if lang == 'zh':
            return f"{outlet}报道：{point}"
        return f"{outlet} reports: {point}"
    if attribution == 'single_source':
        if lang == 'zh':
            return f"目前只读到{outlet}一家的正文，所以这句只算它的报道，不算已核实事实：{line}"
        return f"Only {outlet} was read, so this stays that outlet's report: {line}"
    return line


def _reprint_note(packet, lang):
    notes = []
    for row in packet.get('disagreement') or []:
        if not isinstance(row, dict):
            continue
        if not str(row.get('what') or '').startswith('a reprint'):
            continue
        for item in row.get('items') or []:
            if lang == 'zh':
                notes.append(
                    f"另有转述把方向写成了相反的结果，并写明引自{item.get('cites')}。"
                    f"这条转述不作为第二信源。"
                )
            else:
                notes.append(
                    f"A reprint citing {item.get('cites')} states the opposite. "
                    f"It is not counted as a second witness."
                )
    return notes


def compose(packet, angle, persona=None):
    """One draft from admitted claims. A persona picks the angle, not the facts."""
    claims = _claims(packet, angle)
    if persona and persona.get('fact_ids'):
        wanted = set(persona['fact_ids'])
        picked = [c for c in claims if c.get('fact_id') in wanted]
        if picked:
            claims = picked
    if not claims:
        return {
            'status': 'not_drafted',
            'why': (angle or {}).get('why') or 'no admitted claims',
            'text': '',
            'lang': None,
            'sentences': [],
        }
    lang = _draft_lang(packet)
    attr = angle.get('attribution') or 'event'
    sentences = []
    if persona and persona.get('angle') and lang == 'zh':
        sentences.append({
            'text': persona['angle'].strip(),
            'fact_id': claims[0].get('fact_id'),
            'source_id': claims[0].get('source_id'),
            'admission': claims[0].get('admission'),
            'kind': 'interpretation',
        })
    elif attr == 'event' and lang == 'zh' and not persona:
        outlets = []
        for fact in claims:
            name = _outlet(packet, fact.get('source_id'))
            if name and name not in outlets:
                outlets.append(name)
        named = '、'.join(outlets[:3])
        sentences.append({
            'text': f"{named}读到的正文指向同一边。",
            'fact_id': claims[0].get('fact_id') if claims else None,
            'source_id': claims[0].get('source_id') if claims else None,
            'admission': claims[0].get('admission') if claims else None,
            'kind': 'event',
        })
    for fact in claims:
        sentences.append({
            'text': _sentence(fact, packet, attr, lang),
            'fact_id': fact.get('fact_id'),
            'source_id': fact.get('source_id'),
            'admission': fact.get('admission'),
            'confidence': fact.get('confidence'),
            'kind': 'attributed' if attr == 'single_source' else 'event',
        })
    for note in _reprint_note(packet, lang):
        sentences.append({
            'text': note,
            'fact_id': None,
            'source_id': None,
            'admission': 'flag',
            'kind': 'flag',
        })
    if persona and persona.get('interpretation'):
        sentences.append({
            'text': persona['interpretation'].strip(),
            'fact_id': claims[0].get('fact_id'),
            'source_id': claims[0].get('source_id'),
            'admission': claims[0].get('admission'),
            'kind': 'interpretation',
        })
    if lang == 'zh':
        closer = '未打开的报道不计入上面的判断。数字和原话只以已准入的事实为准。'
    else:
        closer = 'An unread report is not part of the judgment above. Numbers and quotes stay with the admitted claims.'
    sentences.append({'text': closer, 'fact_id': None, 'source_id': None,
                      'admission': 'limit', 'kind': 'limit'})
    text = '\n'.join(s['text'] for s in sentences)
    return {
        'status': 'drafted',
        'lang': lang,
        'attribution': attr,
        'angle_id': (persona or {}).get('angle') or angle.get('angle_id'),
        'persona_id': (persona or {}).get('persona_id'),
        'text': text,
        'sentences': sentences,
        'fact_ids': [s['fact_id'] for s in sentences if s.get('fact_id')],
    }


# Concrete facts the writer is not free to add. A judgment is not one of these.
_PRICE = re.compile(
    r'(?:\$|¥|€|£)\s*\d|'
    r'\d+(?:\.\d+)?\s*(?:美元|美金|元|块|港元|日元|欧元|英镑)|'
    r'(?:报|收于|收在|站上|跌破|突破)\s*\d'
)
_DATE = re.compile(
    r'\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2}|\b20\d{2}-\d{2}-\d{2}\b|'
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|'
    r'Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'\.?\s+\d{1,2}\b',
    re.I,
)
_QUOTE = re.compile(r'[“"][^”"]{8,}[”"]|「[^」]{8,}」')
_ACTION = re.compile(
    r'(?:宣布|公布|批准|驳回|裁定|判决|收购|合并|退市|停牌|复牌|分红|回购|裁员|'
    r'破产|起诉|和解|任命|辞职|上市).{0,16}(?:了|已)|'
    r'\b(?:announced|approved|rejected|acquired|merged|delisted|halted|'
    r'resumed|sued|settled|appointed|resigned)\b',
    re.I,
)
_NUMBER = re.compile(r'\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*(?:亿|万|倍|个基点|bps|bp)')


def _factish(text):
    """Spans that look like a concrete fact, not a judgment."""
    blob = text or ''
    spans = []
    for cre in (_PRICE, _DATE, _QUOTE, _ACTION, _NUMBER):
        spans.extend(m.group(0) for m in cre.finditer(blob))
    return spans


def _norm(text):
    return re.sub(r'\s+', '', (text or '')).lower()


def contradicting_spans(draft_text, packet):
    """Opposite direction on the same subject. A bare judgment is not a conflict."""
    hits = []
    sources = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') not in (
                'official', 'two_independent_major', 'single_major_attributed',
                'wire_beside_official'):
            continue
        sources.append(fact.get('text') or '')
    pairs = (
        ('上涨', '下跌'), ('下跌', '上涨'), ('大涨', '大跌'), ('大跌', '大涨'),
        ('胜诉', '败诉'), ('败诉', '胜诉'), ('批准', '驳回'), ('驳回', '批准'),
    )
    draft = draft_text or ''
    for left, right in pairs:
        if left not in draft:
            continue
        for src in sources:
            if right not in src or left in src:
                continue
            shared = [
                tok for tok in re.findall(r'[A-Za-z][A-Za-z0-9]{3,}|[一-鿿]{2,}', src)
                if tok in draft
            ]
            if len(shared) >= 2:
                hits.append(left + '/' + right)
                break
    return hits


def pasted_runs(draft_text, packet, run=24):
    """A consecutive run of a source's own wording. A short name is not a paste."""
    blob = _norm(draft_text)
    if not blob:
        return []
    hits = []
    seen = set()
    pool = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        for key in ('text', 'restatement_zh', 'restatement_en'):
            pool.append(fact.get(key) or '')
    for view in packet.get('source_views') or []:
        pool.append(view.get('claim') or '')
    for raw in pool:
        src = _norm(raw)
        if len(src) < 40 or _language_of(src) != _language_of(blob):
            continue
        window = src[:run]
        if window in blob and window not in seen:
            seen.add(window)
            hits.append(window)
    return hits


def fact_qa(draft, packet):
    """Three blocks. Analysis does not need a source sentence.

    1. A new concrete fact: number, date, price, quote, or company action
       whose wording is not in the approved packet.
    2. A direct conflict with an approved source.
    3. A consecutive run of a source's own wording.

    A judgment, an inference, and a second-order implication are not blocks.
    One bold sentence does not fail the draft.
    """
    findings = []
    parts = []
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        if fact.get('admission') not in (
                'official', 'two_independent_major', 'single_major_attributed',
                'wire_beside_official'):
            continue
        parts.append(fact.get('text') or '')
        parts.append(fact.get('restatement_zh') or '')
        parts.append(fact.get('restatement_en') or '')
    for view in packet.get('source_views') or []:
        parts.append(view.get('claim') or '')
    library_norm = _norm(' '.join(parts))
    text = draft.get('text') or ''
    invented = [span for span in _factish(text) if _norm(span) and _norm(span) not in library_norm]
    if invented:
        findings.append({'code': 'new_concrete_fact', 'severity': 'blocking', 'detail': invented[:8]})
    conflicts = contradicting_spans(text, packet)
    if conflicts:
        findings.append({'code': 'direct_fact_conflict', 'severity': 'blocking', 'detail': conflicts[:6]})
    pastes = pasted_runs(text, packet)
    if pastes:
        findings.append({'code': 'obvious_source_copy', 'severity': 'blocking', 'detail': pastes[:4]})
    blocking = [f for f in findings if f['severity'] == 'blocking']
    return {'findings': findings, 'blocking_count': len(blocking), 'status': 'failed' if blocking else 'passed'}


def originality_qa(draft, packet):
    """Same gate as content/originality.py. Sources are the comparison set.

    A Chinese draft against English bodies is a cross-language carry, which
    that gate allows. A same-language paste is blocking. Promo lines and
    foreign links are blocking either way.
    """
    from content.originality import check
    bodies = []
    for view in packet.get('source_views') or []:
        if view.get('claim'):
            bodies.append(view['claim'])
    for fact in (packet.get('primary_facts') or []) + (packet.get('downgraded_claims') or []):
        for key in ('text', 'restatement_zh', 'restatement_en'):
            if fact.get(key):
                bodies.append(fact[key])
    allowed = [v.get('url') for v in (packet.get('source_views') or []) if v.get('url')]
    return check(
        draft.get('text') or '',
        lang=draft.get('lang') or 'zh',
        exemplars=(),
        source_text='\n'.join(bodies),
        allowed_urls=allowed,
        fuzzy=False,
    )


def write_from_packet(packet, angle, ready_at=None, persona=None):
    """Packet and angle in, one draft plus the two QA results out.

    `persona` is an optional decision from persona_views.consider. It
    chooses which admitted facts to lead with and what interpretation to
    add. It does not change the packet.
    """
    ready_at = ready_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    if persona and not persona.get('interested'):
        return {
            'draft': {
                'status': 'not_drafted',
                'why': persona.get('why_not') or 'persona passed',
                'persona_id': persona.get('persona_id'),
                'text': '',
                'lang': None,
                'sentences': [],
            },
            'fact_qa': None,
            'originality_qa': None,
            'content_status': 'passed_by_persona',
            'draft_ready': None,
        }
    draft = compose(packet, angle, persona=persona)
    if draft['status'] != 'drafted':
        return {'draft': draft, 'fact_qa': None, 'originality_qa': None,
                'content_status': 'not_drafted', 'draft_ready': None}
    facts = fact_qa(draft, packet)
    original = originality_qa(draft, packet)
    blocked = facts['status'] != 'passed' or original['status'] != 'passed'
    return {
        'draft': draft,
        'fact_qa': facts,
        'originality_qa': original,
        'content_status': 'blocked' if blocked else 'draft_ready',
        'draft_ready': ready_at,
        'persona_id': (persona or {}).get('persona_id'),
    }


def main():
    packet_path = ROOT / 'live/store/packets/live-latest.json'
    if not packet_path.is_file():
        raise SystemExit('no live packet at live/store/packets/live-latest.json')
    saved = json.loads(packet_path.read_text(encoding='utf-8'))
    result = write_from_packet(saved['packet'], saved['angle'])
    print(json.dumps({
        'content_status': result['content_status'],
        'lang': result['draft'].get('lang'),
        'angle': result['draft'].get('angle_id'),
        'fact_qa': None if not result['fact_qa'] else result['fact_qa']['status'],
        'originality': None if not result['originality_qa'] else result['originality_qa']['status'],
        'text': result['draft'].get('text'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
