"""QA date binding must accept ISO datetimes ending in 'Z' (crash seen in the compose A/B:
ValueError: Invalid isoformat string: '2026-09-30T00:00:00Z')."""
from live import draft_qa

NOW = '2026-10-04'


def unit(published_at, as_of='2026-09-30'):
    return {'unit_id': 'u1', 'kind': 'fact', 'usage': 'paraphrase', 'statement': 'Payrolls rose 123.',
            'numbers': [{'text': '123', 'metric': 'payrolls', 'period': ''}],
            'as_of': as_of, 'published_at': published_at, 'published_at_norm': '2026-09-30'}


def test_z_suffixed_published_at_does_not_crash_and_binds():
    u = unit('2026-09-30T00:00:00Z')
    assert not any(f['code'] == 'wrong_date_fact'
                   for f in draft_qa.stale_time_findings('On September 30 payrolls rose 123.', [u], NOW, 'en'))
    assert any(f['code'] == 'wrong_date_fact'
               for f in draft_qa.stale_time_findings('On September 12 payrolls rose 123.', [u], NOW, 'en'))


def test_offset_and_malformed_dates_are_tolerated():
    for raw in ('2026-09-30T00:00:00+00:00', '2026-09-30 08:00:00Z', 'not-a-date', ''):
        draft_qa.stale_time_findings('Payrolls rose 123 on 2026-09-30.', [unit(raw)], NOW, 'en')
    # as_of itself carrying a Z timestamp
    draft_qa.stale_time_findings('Payrolls rose 123 on 2026-09-30.', [unit('2026-09-30', as_of='2026-09-30T00:00:00Z')], NOW, 'en')
