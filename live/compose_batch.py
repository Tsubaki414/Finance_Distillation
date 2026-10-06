"""Batch / daily compose entry point: several (source, account) jobs -> drafts -> arbitration.

P1-2 (2026-10-06): cross-persona claim arbitration runs by DEFAULT in soft mode on every batch, so
two accounts that only rephrase the same conclusion on the same day get one WRITE and one HOLD
(soft: text kept, finding + arbitration block added, never deleted). Opposite calls never collide.

Turn it off for a run with compose_batch(..., arbitration='off') or env FD_ARBITRATION=off.
Each job: {'source', 'account_id', optional 'post_type', 'extracted_units', 'key'}.
No publishing; every draft stays publishable=False.
"""
from __future__ import annotations

from live import compose


def compose_batch(jobs, client, *, ledger_factory=None, arbitration=None, on_error=None, **compose_kwargs):
    """Compose each job (errors become status='error' rows, never abort the batch), then arbitrate."""
    from live import compose_shapes
    results, batch_shapes = [], []
    for i, job in enumerate(jobs):
        account = job['account_id']
        key = job.get('key') or f'{account}#{i}'
        try:
            ledger = ledger_factory(account) if ledger_factory else None
            result = compose.compose_source(
                job['source'], account, client, post_type=job.get('post_type'),
                extracted_units=job.get('extracted_units'), view_ledger=ledger,
                shape_batch=tuple(batch_shapes), **compose_kwargs)
            result = dict(result, key=key, source=job['source'])
            if (result.get('composition_shape') or {}).get('id'):
                batch_shapes.append(result['composition_shape']['id'])
        except Exception as exc:   # one bad source must not sink the day's batch
            if on_error is not None:
                on_error(job, exc)
            result = {'key': key, 'account_id': account, 'status': 'error', 'draft_status': 'blocked',
                      'error': f'{type(exc).__name__}: {str(exc)[:300]}', 'publishable': False}
        results.append(result)
    compose_shapes.batch_findings(results)   # soft: shared shape / skeleton, >1 falsifier ending
    return compose.arbitrate_batch(results, mode=arbitration)
