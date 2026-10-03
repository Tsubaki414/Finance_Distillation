"""Read-only audit of existing functions. No collector, model, or live-store writes.

Run from the repo root: python3 -B docs/audits/2026-09-29-distillation/offline_probe.py
The printed JSON describes observed behavior, not passing product acceptance.
"""
from pathlib import Path
from unittest.mock import patch
import collections
import datetime
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
import analysis_corpus as ac
import draft_from_packet as dw
import production as prod
import public_writer as pw
import queue_store as qs

NOW = '2026-09-29T06:00:00+00:00'


def item(text, action='REWRITE', persona='macro'):
    return dict(id='audit-synthetic', source='x_PhyrexNi', author='Synthetic Author',
                title='', text=text, url='https://example.invalid/audit',
                published_at=NOW, action=action, reason='synthetic audit input',
                persona=persona, peers=[])


def packet(text):
    return prod._source_packet(item(text), [], [])


def full_gate(source, output):
    p = packet(source)
    with patch.object(pw, 'write_public', return_value={'text': output, 'model': 'stub'}):
        r = prod.write_hot_draft(p, 'macro', 'audit', ac.rewrite_from_matches([item(source)]))
    return {k: r[k] for k in ('content_status', 'fact_qa', 'originality_qa')}


def routing_probe(action, persona):
    i = item('I think liquidity matters because tighter funding changes the cost of risk.', action, persona)
    q = qs.empty()
    with patch.object(ac, 'classify_latest', return_value=[i]), \
         patch.object(prod, '_news_rows', return_value=[]), \
         patch.object(qs, 'save'), \
         patch.object(prod, 'write_hot_draft', return_value={
             'text': '', 'content_status': 'blocked', 'fact_qa': None,
             'originality_qa': None, 'draft_ready': None}) as writer:
        prod.source_first_pass(q, NOW)
    return {'writer_calls': writer.call_count, 'opportunities': len(q['opportunities'])}


def main():
    probes = {}
    long_text = ('A complete paragraph about liquidity, collateral and funding costs.\n\n' * 100
                 + 'TAIL: profit fell 7% only if the hedge was excluded.')
    stored = ac._row('audit', 'Synthetic Author', NOW, '', long_text,
                     'https://example.invalid/audit', 'newsletter')
    probes['ingest_truncation'] = {
        'input_chars': len(long_text), 'stored_chars': len(stored['text']),
        'tail_preserved': 'TAIL:' in stored['text'],
        'paragraph_breaks_preserved': '\n\n' in stored['text'],
        'qa_source_chars': len(packet(stored['text'])['source_views'][0]['claim']),
        'writer_source_chars': len(ac.rewrite_from_matches([stored])[0]['original_text']),
    }
    probes['skip'] = routing_probe('SKIP', 'macro')
    probes['null_persona'] = routing_probe('REWRITE', None)
    # These two are injected invalid/future classifier outputs, not labels the
    # current classifier emits. They test the absence of schema validation.
    probes['injected_action_NONE'] = routing_probe('NONE', 'macro')
    probes['injected_persona_NONE'] = routing_probe('REWRITE', 'NONE')
    probes['valid_currency_translation'] = full_gate(
        'Arbor revenue was $2.5 billion.', 'Arbor的营收为25亿美元。')
    probes['swapped_metric_values'] = full_gate(
        'Revenue grew 10%. Profit grew 5%.', '利润增长10%，营收增长5%。')
    probes['lost_all_selected_facts'] = full_gate(
        'Revenue grew 10%. Profit grew 5%.', '市场仍需观察。')
    probes['changed_stance_and_added_opinion'] = full_gate(
        'Margins may fall if costs rise.', '利润率将上升，市场必然长期受益。')
    probes['wrong_output_language'] = full_gate(
        '如果需求转弱，利润率可能下降，不能直接外推本季的改善。',
        'A durable recovery is certain and the outlook is strong.')
    probes['author_experience_transplanted'] = full_gate(
        'In my own fund I charge a performance fee and choose less leverage.',
        '我管理基金并收取业绩报酬，因此更重视降低杠杆。')
    probes['unrequested_author_attribution'] = full_gate(
        'Liquidity may tighten if collateral becomes scarce.',
        'Synthetic Author认为，如果抵押品稀缺，流动性可能收紧。')
    probes['writer_refusal_as_draft'] = full_gate(
        'Liquidity may tighten if collateral becomes scarce.', '没有可重组的判断，不写稿。')
    probes['number_after_qa_cutoff'] = full_gate(
        'Funding conditions remain uncertain. ' * 60 + 'Revenue grew 17%.',
        '营收增长17%。')
    probes['unrelated_news_number_match'] = prod.verify_cited_facts(
        'Arbor plans a $235 billion buyback.',
        [{'source': 'unrelated', 'title': 'A different country reports 235 million residents',
          'summary': '', 'url': 'https://example.invalid/unrelated'}])
    probes['substantive_judgment_without_marker'] = ac.classify_row(
        {'text': 'Margins remain fragile. Input costs are rising; customers reject higher prices.',
         'title': '', 'id': 'audit', 'entities': []}, [])
    probes['neutral_subscription_business_dropped'] = ac._row(
        'audit', 'Synthetic Author', NOW, '',
        '公司订阅收入保持增长，因为客户续费率稳定，但合同期限缩短会影响未来收入确认的节奏。',
        'https://example.invalid/audit', 'newsletter') is None
    empty_packet = packet('Liquidity may tighten if collateral becomes scarce.')
    with patch.object(pw.backend, 'complete', return_value={'text': '不写稿', 'model': 'stub'}) as call:
        pw.write_public(empty_packet, 'macro', None, {}, fact_pack=[], rewrite=[])
        probes['empty_rewrite_still_calls_llm'] = call.call_count

    rows = ac.load()
    corpus_bytes = ac.STORE.read_bytes()
    queue_bytes = qs.STORE.read_bytes()
    q = json.loads(queue_bytes)
    opportunities = q['opportunities']
    current = [o for o in opportunities if (o.get('audit') or {}).get('basis') == 'source-first']
    snapshot = {
        'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'corpus_sha256': hashlib.sha256(corpus_bytes).hexdigest(),
        'queue_sha256': hashlib.sha256(queue_bytes).hexdigest(),
        'queue_updated_at': q.get('updated_at'),
        'subscriptions': {'x': len(ac.PRIORITY_HANDLES), 'feed': len(ac.PRIORITY_FEEDS)},
        'corpus_rows': len(rows), 'corpus_rows_exactly_4000_chars': sum(len(r['text']) == 4000 for r in rows),
        'corpus_fields': sorted(set().union(*(r.keys() for r in rows))),
        'queue_rows': len(opportunities),
        'queue_statuses': dict(collections.Counter(o['draft_status'] for o in opportunities)),
        'source_first_rows': len(current),
        'source_first_statuses': dict(collections.Counter(o['draft_status'] for o in current)),
        'source_first_with_account_id': sum(bool(o.get('account_id')) for o in current),
        'source_first_with_target_language': sum(bool(o.get('target_language')) for o in current),
        'source_first_with_original': sum(bool((o.get('audit') or {}).get('original')) for o in current),
    }
    paths = []
    for directory in ('live', 'content', 'backend', 'scripts', 'tests', 'qa', 'ml', 'evidence_loop', 'evergreen'):
        paths.extend(p for p in (ROOT / directory).glob('*.py'))
    paths.extend(ROOT / p for p in ('live/accounts.json', 'live/source_registry.json', 'CLAUDE.md'))
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    test_item = item('Liquidity may tighten if collateral becomes scarce. The effect is conditional, not a forecast.')
    messages, _ = pw.messages_for(packet(test_item['text']), 'macro', prod._angle_for(test_item), {},
                                 fact_pack=[], rewrite=ac.rewrite_from_matches([test_item]))
    print(json.dumps({'scope': 'Offline characterization of current code, with stubbed model outputs; not a model evaluation.',
                      'network_calls': 0, 'production_writes': 0, 'snapshot': snapshot,
                      'probes': probes, 'effective_messages_synthetic_example': messages,
                      'code_sha256': manifest}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
