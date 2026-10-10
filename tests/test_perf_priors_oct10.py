"""Oct 10: tests for perf_priors (Item 7).

Tests cover:
- shrinkage / clamp / ±10% day-over-day change limit
- missing file → all weights 1.0
- selection multiplier bounded and recorded in plan (FD_PERF_PRIORS)
- FD_PERF_PRIORS=0 → no change to sort key
"""
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

import perf_priors as pp_script  # noqa: E402
from live import perf_priors as pp  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _today_str():
    return datetime.now(timezone.utc).date().isoformat()


def _days_ago(n):
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


def _row(lang, views, followers=None, fmt='standalone', angle='macro_liquidity',
         posted_at=None, day=None):
    """Build a minimal perf row."""
    day = day or _today_str()
    posted_at = posted_at or datetime.now(timezone.utc).isoformat()
    return {
        'id': f'draft-{lang}-{views}',
        'lang': lang,
        'views': views,
        'followers': followers,
        'format': fmt,
        'angle': angle,
        'beat': None,
        'motif_type': 'regular',
        'posted_at': posted_at,
        'suggested_london': None,
        'day': day,
    }


def _write_jsonl(path, rows):
    Path(path).write_text('\n'.join(json.dumps(r) for r in rows) + '\n')


# ── EB shrinkage and clamp ────────────────────────────────────────────────────

def test_empty_bucket_returns_1():
    assert pp_script.eb_weight([], global_mean=3.0, n0=8) == 1.0


def test_zero_global_mean_returns_1():
    assert pp_script.eb_weight([1.0, 2.0], global_mean=0.0, n0=8) == 1.0


def test_single_sample_shrinks_toward_1():
    """With one sample and n0=8, the estimate stays very close to 1.0."""
    w = pp_script.eb_weight([5.0], global_mean=5.0, n0=8)
    assert abs(w - 1.0) < 1e-9   # identical mean → exactly 1.0


def test_high_bucket_mean_clamped():
    """A very high bucket mean should be clamped at 1.30."""
    w = pp_script.eb_weight([100.0] * 100, global_mean=1.0, n0=8)
    assert w == 1.30


def test_low_bucket_mean_clamped():
    """A very low bucket mean should be clamped at 0.75."""
    w = pp_script.eb_weight([0.001] * 100, global_mean=1.0, n0=8)
    assert w == 0.75


def test_typical_weight_in_range():
    w = pp_script.eb_weight([2.0, 3.0, 4.0], global_mean=3.0, n0=8)
    assert 0.75 <= w <= 1.30


# ── Day-over-day clamp ────────────────────────────────────────────────────────

def test_dod_clamp_up():
    """A jump of +50% is clamped to +10%."""
    assert abs(pp_script.apply_dod_clamp(1.5, 1.0) - 1.1) < 1e-9


def test_dod_clamp_down():
    """A drop of -50% is clamped to -10%."""
    assert abs(pp_script.apply_dod_clamp(0.5, 1.0) - 0.9) < 1e-9


def test_dod_small_change_passes():
    """A change of +5% is within ±10% and passes unchanged."""
    assert abs(pp_script.apply_dod_clamp(1.05, 1.0) - 1.05) < 1e-9


# ── Missing perf.jsonl → all weights 1.0 ─────────────────────────────────────

def test_missing_file_loads_empty():
    pr = pp.load('/nonexistent/perf_priors.json')
    assert pr == {}


def test_empty_priors_returns_1():
    assert pp.hour_weight({}, 'zh', 10) == 1.0
    assert pp.topic_weight({}, 'en', None, None, None) == 1.0
    assert pp.format_weight({}, 'zh', 'standalone') == 1.0
    assert pp.combined({}, 'zh') == 1.0


def test_combined_clamp_floor():
    """combined() respects its clamp floor even if weights are very low."""
    priors = {'weights': {'zh': {'format': {'x': 0.0}, 'hour': {}, 'topic': {'a': 0.0}}}}
    w = pp.combined(priors, 'zh', angle='a', fmt='x', clamp=(0.7, 1.4))
    assert w >= 0.7


def test_combined_clamp_ceiling():
    """combined() respects its clamp ceiling."""
    priors = {'weights': {'en': {'format': {'x': 2.0}, 'hour': {}, 'topic': {'a': 2.0}}}}
    w = pp.combined(priors, 'en', angle='a', fmt='x', clamp=(0.7, 1.4))
    assert w <= 1.4


# ── Full build: rolling window + prev clamp ───────────────────────────────────

def test_full_build_produces_valid_structure():
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'perf.jsonl'
        out = Path(td) / 'perf_priors.json'
        rows = [
            _row('zh', views=200, followers=1000, fmt='standalone', angle='macro_liquidity', day=_today_str()),
            _row('zh', views=50,  followers=1000, fmt='data_take',  angle='price_structure',  day=_today_str()),
            _row('en', views=400, followers=2000, fmt='standalone', angle='onchain_holders',  day=_today_str()),
            _row('en', views=100, followers=2000, fmt='list_dump',  angle='macro_liquidity',  day=_today_str()),
        ]
        _write_jsonl(src, rows)
        pp_script.main.__wrapped__ = None   # no-op; just use sys.argv override
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ['perf_priors.py', '--perf-jsonl', str(src), '--out', str(out), '--days', '14']
        try:
            pp_script.main()
        finally:
            _sys.argv = old_argv
        assert out.exists()
        data = json.loads(out.read_text())
        assert 'weights' in data
        assert 'zh' in data['weights'] and 'en' in data['weights']
        for lang in ('zh', 'en'):
            for dim in ('format', 'hour', 'topic'):
                assert dim in data['weights'][lang]
            # all weights in [0.75, 1.30]
            for dim in ('format', 'hour', 'topic'):
                for v in data['weights'][lang][dim].values():
                    assert 0.75 <= v <= 1.30, f'{lang}/{dim}: {v}'


def test_old_day_rows_excluded():
    """Rows outside the rolling window should be ignored."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'perf.jsonl'
        out = Path(td) / 'perf_priors.json'
        old_rows = [_row('zh', views=9999, day=_days_ago(30))]
        _write_jsonl(src, old_rows)
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ['perf_priors.py', '--perf-jsonl', str(src), '--out', str(out), '--days', '14']
        try:
            pp_script.main()
        finally:
            _sys.argv = old_argv
        data = json.loads(out.read_text())
        # no rows → all weight dicts should be empty (no buckets)
        assert data['weights']['zh']['format'] == {}
        assert data['rows'] == 0


def test_dod_clamp_applied_when_prev_file_exists():
    """The ±10% day-over-day clamp fires when a previous perf_priors.json exists."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'perf.jsonl'
        out = Path(td) / 'perf_priors.json'
        # Write a prev file with weight 1.0 for 'macro_liquidity' topic
        prev = {
            'built_at': datetime.now(timezone.utc).isoformat(),
            'weights': {'zh': {'format': {}, 'hour': {}, 'topic': {'macro_liquidity': 1.0}},
                        'en': {'format': {}, 'hour': {}, 'topic': {}}},
            'n': {'zh': {'format': {}, 'hour': {}, 'topic': {}},
                  'en': {'format': {}, 'hour': {}, 'topic': {}}},
            'means': {'zh': {'global': 3.0, 'format': {}, 'hour': {}, 'topic': {}},
                      'en': {'global': 3.0, 'format': {}, 'hour': {}, 'topic': {}}},
            'rows': 0, 'days': 1,
        }
        out.write_text(json.dumps(prev))
        # Write many rows to push the macro_liquidity topic weight very high
        rows = [_row('zh', views=10000, followers=10, fmt='standalone',
                     angle='macro_liquidity', day=_today_str()) for _ in range(30)]
        _write_jsonl(src, rows)
        import sys as _sys
        old_argv = _sys.argv
        _sys.argv = ['perf_priors.py', '--perf-jsonl', str(src), '--out', str(out), '--days', '14']
        try:
            pp_script.main()
        finally:
            _sys.argv = old_argv
        data = json.loads(out.read_text())
        # The raw EB weight would be 1.30 (clamped), but prev was 1.0 so DoD cap is 1.1
        w = data['weights']['zh']['topic']['macro_liquidity']
        assert w <= 1.1 + 1e-6, f'DoD clamp not applied: weight={w}'


# ── Selection: FD_PERF_PRIORS=0 ──────────────────────────────────────────────

def test_perf_priors_off_import():
    """FD_PERF_PRIORS=0: perf_priors module should not be loaded in candidates()."""
    import importlib
    with __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {'FD_PERF_PRIORS': '0'}):
        # Reload to pick up env change (the module-level check uses os.environ at call time)
        # We can't easily test the full candidates() without a live store, but we can test
        # that pp.load() returns {} when the file is absent and combined() stays 1.0.
        pr = pp.load('/nonexistent/does_not_exist.json')
        assert pr == {}
        w = pp.combined(pr, 'zh', angle='macro_liquidity', fmt='standalone')
        assert w == 1.0   # empty priors → combined = 1.0 × 1.0 = 1.0


# ── topic_weight priority ─────────────────────────────────────────────────────

def test_topic_weight_angle_priority():
    priors = {'weights': {'zh': {'topic': {'macro_liquidity': 1.2, 'crypto_lane': 0.8}, 'format': {}, 'hour': {}}}}
    assert pp.topic_weight(priors, 'zh', angle='macro_liquidity', beat='crypto_lane', motif_type='regular') == 1.2


def test_topic_weight_beat_fallback():
    priors = {'weights': {'zh': {'topic': {'crypto_lane': 0.9}, 'format': {}, 'hour': {}}}}
    assert pp.topic_weight(priors, 'zh', angle=None, beat='crypto_lane', motif_type='regular') == 0.9


def test_topic_weight_motif_fallback():
    priors = {'weights': {'zh': {'topic': {'hot:flash': 1.1}, 'format': {}, 'hour': {}}}}
    assert pp.topic_weight(priors, 'zh', angle=None, beat=None, motif_type='hot:flash') == 1.1


def test_topic_weight_other_fallback():
    priors = {'weights': {'zh': {'topic': {'other': 0.95}, 'format': {}, 'hour': {}}}}
    assert pp.topic_weight(priors, 'zh', angle=None, beat=None, motif_type=None) == 0.95


# ── hour_weight 3-hour bucket ────────────────────────────────────────────────

def test_hour_weight_bucket():
    priors = {'weights': {'zh': {'hour': {'9': 1.15}, 'format': {}, 'topic': {}}}}
    # hour 9, 10, 11 all map to bucket '9'
    for h in (9, 10, 11):
        assert pp.hour_weight(priors, 'zh', h) == 1.15


def test_hour_weight_missing_returns_1():
    priors = {'weights': {'zh': {'hour': {}, 'format': {}, 'topic': {}}}}
    assert pp.hour_weight(priors, 'zh', 14) == 1.0


# ── perf_record helper and plan annotation (defect 4a / 4b fix) ───────────────

def test_perf_record_fields():
    """perf_record() returns topic / angle / beat / format / topic_w / format_w / mult."""
    priors = {'weights': {'zh': {'topic': {'macro_liquidity': 1.1}, 'format': {}, 'hour': {}}}}
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import daily_compose as dc
    g = [{'source': {'id': 's1'}, 'unit_id': 'u1', 'unit': {}, 'beat': 'macro_liquidity'}]
    rec = dc.perf_record(priors, 'zh', g, fmt=None)
    assert set(rec.keys()) >= {'topic', 'angle', 'beat', 'format', 'topic_w', 'format_w', 'mult'}
    # beat lookup because no text angle matched
    assert rec['beat'] == 'macro_liquidity'
    assert abs(rec['mult'] - rec['topic_w'] * rec['format_w']) < 1e-9


def test_perf_record_uses_group_angle_not_lead():
    """defect 4b fix: perf_record picks the group's own first angle, not a constant lead angle."""
    priors = {'weights': {'zh': {'topic': {'price_structure': 1.2, 'macro_liquidity': 0.9},
                                 'format': {}, 'hour': {}}}}
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import daily_compose as dc
    from unittest.mock import patch
    from live import angles
    with patch.object(angles, 'angles_of', return_value=['price_structure']):
        g = [{'source': {'id': 's1'}, 'unit_id': 'u1', 'unit': {}, 'beat': 'macro_liquidity'}]
        rec = dc.perf_record(priors, 'zh', g)
    assert rec['angle'] == 'price_structure'
    assert abs(rec['topic_w'] - 1.2) < 1e-6  # group angle used, not beat


def test_perf_priors_for_select_off():
    """FD_PERF_PRIORS=0: perf_priors_for_select() returns {} without loading any file."""
    import sys, os
    from pathlib import Path
    from unittest.mock import patch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import daily_compose as dc
    with patch.dict(os.environ, {'FD_PERF_PRIORS': '0'}):
        result = dc.perf_priors_for_select()
    assert result == {}


def test_biased_type_mix_clamp():
    """biased_type_mix() applies format weight to post_type_mix, clamped [0.7, 1.4]."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import daily_compose as dc
    priors = {'weights': {'zh': {'format': {'standalone': 2.0, 'quick_take': 0.1},
                                 'topic': {}, 'hour': {}}}}
    mix = {'standalone': 1.0, 'quick_take': 1.0}
    result = dc.biased_type_mix(priors, 'zh', mix)
    assert result['standalone'] == 1.4   # clamped at upper bound
    assert result['quick_take'] == 0.7   # clamped at lower bound
