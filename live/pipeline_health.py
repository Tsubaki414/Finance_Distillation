"""Read-only inventory of the configured daily loop, separate from content quality.

No provider requests, schema creation, draft generation or credential serialization.
Configuration readiness does not assert timeline completeness or editorial acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path

from live.account_intelligence import Store, accounts
from live.account_monitor import configuration, monitor_status
from live.account_sources import registry, universes
from live.content_stages import ContentStages


def inventory(store=None, *, status=None):
    store = store or Store()
    state = status if status is not None else monitor_status(store.root)
    config = configuration()
    catalog = registry()
    worlds = {u['account_id']: u for u in universes()}
    profiles = {a['id']: a for a in accounts()}
    observed = {(s['account'], s['source']): s for s in state.get('sources', [])}
    issues, rows = [], []
    try:
        stages = ContentStages(store.root / 'health-no-calls')
        provider = {**stages.configuration, 'configuration_valid': True,
                    'live_availability': 'See actual cycle and call results; no probe made'}
    except (ValueError, OSError, KeyError) as exc:
        provider = {'configuration_valid': False, 'error_type': type(exc).__name__}
        issues.append({'scope': 'provider', 'code': 'provider_configuration_invalid'})
    for aid in config['accounts']:
        profile, world = profiles.get(aid, {}), worlds.get(aid, {})
        if not profile.get('enabled') or not world or profile.get('language') not in {'en', 'zh'}:
            issues.append({'account_id': aid, 'code': 'account_configuration_invalid'})
        subscriptions = []
        for sub in world.get('subscriptions', []):
            sid, role = sub['source_id'], sub['role']
            source = catalog.get(sid, {})
            primary = sid.startswith('primary_') or source.get('content_role') == 'context_only'
            polling = bool(sub.get('enabled') and role in {'CORE', 'SECONDARY', 'EVENT_ONLY'})
            adapter = source.get('adapter') or ('x' if source.get('handle') else None)
            prior = observed.get((aid, sid), {})
            if polling and not adapter:
                issues.append({'account_id': aid, 'source_id': sid, 'code': 'source_adapter_missing'})
            try:
                cursor = json.loads(prior.get('cursor') or '{}')
            except (ValueError, TypeError):
                cursor = {}
                issues.append({'account_id': aid, 'source_id': sid, 'code': 'source_cursor_invalid'})
            subscriptions.append({
                'source_id': sid, 'name': source.get('name', sid), 'role': role,
                'enabled': sub.get('enabled') is True, 'polling': polling, 'adapter': adapter,
                'purpose': 'factual_context_only' if primary else 'content_candidates' if polling else 'not_polled',
                'candidate_policy': sub.get('candidate_policy'), 'topic_scope': sub.get('topic_scope', []),
                'last_checked': prior.get('last_checked'), 'last_seen': prior.get('last_seen'),
                'status': prior.get('status', 'not_checked' if polling else 'not_polled'),
                'error': prior.get('error'),
                'coverage': source.get('coverage') or (
                    'bounded_provider_search_not_exhaustive_timeline' if adapter == 'x' else
                    'current_feed_window_not_complete_archive' if adapter == 'feed' else
                    'configured_official_endpoints' if primary else 'configured_corpus'),
                'cursor_saved': bool(cursor),
                'quality_status': sub.get('audit_status') or source.get('quality_status') or 'not_established',
            })
        rows.append({'account_id': aid, 'name': profile.get('name', aid),
                     'target_language': profile.get('language'), 'mode': world.get('mode'),
                     'subscriptions': subscriptions,
                     'queue': state.get('queue_counts', {}).get(aid, {})})
    return {'configuration_ready': not issues, 'issues': issues, 'provider': provider,
            'accounts': rows, 'interval_seconds': config['interval_seconds'],
            'per_account_daily_ceiling': config['max_drafts_per_account_day'],
            'ceiling_is_not_quota': True, 'publishing_enabled': False,
            'human_review_required': True, 'budget': state.get('budget'),
            'daemon_running': state.get('daemon_running', False),
            'runtime': 'This Mac must be awake and the user logged in.',
            'external_platform_follow_actions': False,
            'quality_acceptance': 'Only actual human reviews establish publishability.'}
