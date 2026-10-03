"""One content opportunity queue for Hot and Evergreen.

JSON on disk. No new database. An opportunity is one persona's attempt at
one event, or one evergreen theme. Review status starts at pending. Nothing
here publishes.
"""
from __future__ import annotations
from pathlib import Path
import json, datetime

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'live/store/content_queue.json'

FIELDS = (
    'opportunity_id', 'type', 'created_at', 'priority', 'persona',
    'topic', 'source_packet', 'evergreen_topic', 'selected_angle',
    'draft_status', 'qa_status', 'review_status', 'freshness',
    'duplicate_of', 'text', 'generated_at', 'reaction_lag_seconds',
    'event_id', 'theme_id', 'family', 'version', 'failure_kind',
    'why', 'qa_findings',
    'pipeline_mode', 'pipeline_version', 'run_id', 'draft_id', 'account_id',
    'account_profile_version', 'source_language', 'target_language',
    'source_hash', 'source_ref', 'selection_id', 'translation_id', 'attempt_ref',
    'draft_version',
)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def empty():
    return {
        'updated_at': None,
        'publishing': 'not automated; human picks from the review report',
        'opportunities': [],
        'events': {},
        'themes': {},
    }


def load():
    if not STORE.is_file():
        return empty()
    data = json.loads(STORE.read_text(encoding='utf-8'))
    data.setdefault('opportunities', [])
    data.setdefault('events', {})
    data.setdefault('themes', {})
    return data


def save(data):
    data['updated_at'] = now_iso()
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(STORE)
    return data


def new_id(prefix, n):
    return f'{prefix}-{n:04d}'
