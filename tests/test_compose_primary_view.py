"""Oct 6 P1-1: zh_industry Meta pack led with a legacy view (no structured `view`), so stance
rejected pre-model although two structured views were in the pack."""
from live import compose


def _u(uid, kind, view=None):
    u = {'unit_id': uid, 'kind': kind, 'usage': 'support', 'numbers': [], 'speaker_type': 'media'}
    if view is not None:
        u['view'] = view
    return u


def test_structured_view_is_stance_primary_before_legacy_view():
    units = [_u('legacy', 'view'), _u('fact', 'fact'),
             _u('meta', 'view', {'subject': 'Meta stock', 'direction': 'bearish'})]
    rows = compose.eligible('judgment_take', units)
    assert [u['unit_id'] for u in rows] == ['meta', 'legacy']


def test_order_kept_when_all_views_structured():
    units = [_u('a', 'view', {'subject': 'A'}), _u('f', 'fact'), _u('b', 'view', {'subject': 'B'})]
    assert [u['unit_id'] for u in compose.eligible('judgment_take', units)] == ['a', 'b']
