"""The prediction ledger: what each account claimed, and what would prove it wrong.

`Prediction Ledger & Review` is one of the six content lanes CLAUDE.md specifies and the only one
never built. Without it an account can say anything and never be held to it, which is precisely
the failure mode the whole evidence apparatus exists to prevent — every figure traceable to a
filing, and no record at all of whether the judgement drawn from those figures held up.

Every gated draft already carries the two halves this needs, because the gates require them:

    kind=interpretation   the judgement the account is staking
    kind=condition        what the account said would make it wrong
    proposed_thresholds   the numbers inside that condition, extracted by the numeric layer

So a position is not something a model is asked to summarise here. It is lifted from the ledger
the draft already had to produce in order to ship.

**What this cannot do, said plainly rather than implied by silence.** It cannot decide whether a
prediction came true. That needs a later observation of the same metric, from a source of the same
standing, and the system has no scheduler bringing those in. What it does instead:

  records     the claim, the invalidation condition, its thresholds, the source document and the
              date, append-only, so nothing can be quietly revised after the fact
  matches     a later fact pack covering the same entity and metric, and reports that the
              threshold is now checkable — with both numbers side by side
  refuses     to mark anything `confirmed` or `falsified` on its own. A threshold being crossed is
              reported as `checkable`; whether the judgement was right is a reading, and readings
              belong to a person.

Run: .venv/bin/python -B live/positions.py [--record] [--review] [--days=30]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, datetime, hashlib

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store'
LEDGER = STORE / 'positions.jsonl'

# A stance sentence puts the writer in it. The gates already separate fact from interpretation;
# this picks the interpretation the account is actually standing behind rather than the aside.
FIRST_PERSON = re.compile(r'我[^们]|我们|个人认为|我的判断|我倾向|我据此|我把|我更|'
                          r'\bI\b|\bmy\b|\bwe\b', re.I)
COUNTER = re.compile(r'最强的?相反|相反读法|strongest (?:reading|pushback|case) against|against me',
                     re.I)


def _stance(rows):
    """The sentence the account is standing behind, and the counter-reading it acknowledged."""
    interp = [r for r in rows if r.get('kind') == 'interpretation']
    counter = next((r for r in interp if COUNTER.search(r.get('text') or '')), None)
    body = [r for r in interp if r is not counter]
    mine = [r for r in body if FIRST_PERSON.search(r.get('text') or '')]
    pool = mine or body
    stance = max(pool, key=lambda r: len(r.get('text') or '')) if pool else None
    return stance, counter


def extract(draft):
    """One position from one gated draft, or None when the draft did not stake anything."""
    rows = draft.get('sentence_to_source_ledger') or []
    stance, counter = _stance(rows)
    cond = [r for r in rows if r.get('kind') == 'condition']
    if not stance or not cond:
        return None
    thresholds = [t for r in cond for t in (r.get('proposed_thresholds') or [])]
    payload = f"{draft['id']}|{stance['text']}|{'|'.join(c['text'] for c in cond)}"
    return {
        'position_id': 'pos-' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12],
        'draft_id': draft['id'],
        'account_id': draft.get('account_id'),
        'persona_id': draft.get('persona_id'),
        'entity': draft.get('entity'),
        'lang': draft.get('lang'),
        'taken_at': draft.get('finished_at') or draft.get('created_at'),
        'stance': stance['text'],
        'stance_sentence_id': stance['sentence_id'],
        'counter_reading': (counter or {}).get('text'),
        'invalidation': [c['text'] for c in cond],
        'thresholds': thresholds,
        'cited_fact_ids': sorted({f for r in rows for f in (r.get('fact_ids') or [])}),
        'packet_id': draft.get('packet_id'),
        'primary_url': draft.get('primary_url'),
        'source_rank': draft.get('source_rank'),
        'writer_model': draft.get('writer_model'),
        'status': 'open',
        'review': {'status': 'not_due', 'checked_at': None, 'by': None,
                   'note': 'no later observation of these metrics has been matched yet'},
        'version': 'positions-v1',
    }


def record():
    """Append every gated draft that staked something. Idempotent on position_id."""
    seen = set()
    if LEDGER.is_file():
        for line in LEDGER.read_text(encoding='utf-8').splitlines():
            if line.strip():
                seen.add(json.loads(line)['position_id'])
    # Only the current draft for an account and event counts. The store can hold an earlier
    # attempt at the same piece — a superseded $IBIT draft written from an unlabelled fact pack
    # sat beside its replacement — and a position lifted from a draft that was rewritten before
    # anything shipped is not a claim the account ever made. The ledger is append-only precisely
    # so that a real claim cannot be edited later, which makes it important that a claim never
    # made does not get written into it in the first place.
    current = {}
    for f in sorted((STORE / 'drafts').glob('*.json')):
        d = json.loads(f.read_text())
        if d.get('status') != 'ready_for_queue' or not d.get('text'):
            continue
        key = (d.get('account_id'), d.get('entity'))
        prev = current.get(key)
        if prev is None or str(d.get('finished_at') or '') > str(prev.get('finished_at') or ''):
            current[key] = d

    added = []
    for d in current.values():
        pos = extract(d)
        if pos and pos['position_id'] not in seen:
            added.append(pos)
            seen.add(pos['position_id'])
    if added:
        with LEDGER.open('a', encoding='utf-8') as fh:
            for p in added:
                fh.write(json.dumps(p, ensure_ascii=False) + '\n')
    return added


def _load():
    if not LEDGER.is_file():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding='utf-8').splitlines() if l.strip()]


def checkable(days=0):
    """Positions whose metrics a later fact pack now covers.

    Matching is by entity and by fact id, which is deliberately narrow: two packs for the same
    entity are comparable, a pack for a different entity is not, and nothing here tries to decide
    that two differently-named metrics are the same thing.
    """
    positions = _load()
    packs = {}
    for p in sorted((STORE / 'packets').glob('*.json')):
        pk = json.loads(p.read_text())
        packs.setdefault(pk['entity'], []).append(pk)
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for pos in positions:
        try:
            taken = datetime.datetime.fromisoformat(str(pos['taken_at']).replace('Z', '+00:00'))
        except Exception:
            taken = now
        age = (now - taken).days
        later = [pk for pk in packs.get(pos['entity'], [])
                 if pk['id'] != pos.get('packet_id')]
        out.append({**pos, 'age_days': age,
                    'later_packs': [pk['id'] for pk in later],
                    'checkable': bool(later) and age >= days,
                    'why': ('a later fact pack covers this entity; the threshold can be read '
                            'against it by a person'
                            if later else 'no later fact pack for this entity yet')})
    return out


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    if 'record' in args or not args:
        added = record()
        print(f'新记录 {len(added)} 条立场；账本共 {len(_load())} 条')
        for p in added:
            print(f"  {p['position_id']} {p['account_id']:12} {str(p['entity']):12} "
                  f"阈值 {len(p['thresholds'])}")
            print(f"     立场: {p['stance'][:76]}")
            print(f"     失效: {p['invalidation'][0][:76]}")
    if 'review' in args:
        days = int(args.get('days', 0))
        rows = checkable(days)
        due = [r for r in rows if r['checkable']]
        print(f"\n账本 {len(rows)} 条，其中 {len(due)} 条已可核对（≥{days} 天）")
        for r in due:
            print(f"  {r['position_id']} {r['account_id']:12} {str(r['entity']):10} "
                  f"{r['age_days']}天  后续事实包 {r['later_packs']}")
        print('\n  没有任何一条会被自动判为「应验」或「证伪」——'
              '阈值是否被跨过可以机器读出，判断对错是人的事。')


if __name__ == '__main__':
    main()
