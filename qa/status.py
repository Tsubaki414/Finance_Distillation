"""Single choke point deciding what may leave the system.

Three independent statuses, so "the program finished" can never be mistaken for "the content is
fit to hand over":

  run_status      did the pipeline execute
  qa_status       did the seven gates pass
  content_status  may this leave the system

Any route that serves content to an active queue, a review surface, a visual package or an export
must call `assert_deliverable`. Diagnostic and audit routes call `classify` and label the payload.
"""
from __future__ import annotations

DELIVERABLE = 'ready_for_pipeline'
BLOCKED = 'blocked'

# Kinds that may never be delivered regardless of status fields.
QUARANTINED_KINDS = {'legacy_invalid_output', 'quarantined-generation'}


def classify(record: dict) -> dict:
    """Derive the three statuses from whatever the record carries, defaulting to closed."""
    kind = record.get('record_kind') or record.get('kind')
    if kind in QUARANTINED_KINDS:
        return {'run_status': record.get('run_status') or 'completed',
                'qa_status': 'failed', 'content_status': BLOCKED,
                'reason': f'{kind} is permanently quarantined',
                'deliverable': False}

    run = record.get('run_status') or record.get('status') or 'unknown'
    qa = record.get('qa_status')
    content = record.get('content_status')

    if qa is None:
        qa = 'not_run'
    if content is None:
        content = BLOCKED if qa != 'passed' else DELIVERABLE

    deliverable = (run == 'completed' and qa == 'passed' and content == DELIVERABLE)
    reason = None
    if not deliverable:
        if run != 'completed':
            reason = f'run_status={run}'
        elif qa == 'not_run':
            reason = 'QA gates have not been run on this record'
        elif qa != 'passed':
            reason = f'qa_status={qa}'
        else:
            reason = f'content_status={content}'
    return {'run_status': run, 'qa_status': qa, 'content_status': content,
            'reason': reason, 'deliverable': deliverable}


def assert_deliverable(record: dict, where: str = ''):
    """Raise unless the record may leave the system. Callers convert this into a 409."""
    st = classify(record)
    if not st['deliverable']:
        raise PermissionError(
            f"{where or 'content'} is not deliverable: {st['reason']} "
            f"(run={st['run_status']}, qa={st['qa_status']}, content={st['content_status']})")
    return st


def label(record: dict) -> dict:
    """Attach status to a payload served on a diagnostic route, never silently."""
    st = classify(record)
    return {**record, 'qa_state': st,
            'delivery_note': ('deliverable' if st['deliverable']
                              else 'diagnostic view only, not effective content')}
