from live import jev_front as jf, registry


def test_every_jev_persona_maps_to_a_real_account():
    assert set(jf.ACCOUNT_FOR_PERSONA) == set(jf.PERSONAS)
    for jev_id, account in jf.ACCOUNT_FOR_PERSONA.items():
        assert registry.persona_for_account(account) is not None, (jev_id, account)
    assert jf.account_for('none') is None
    assert jf.jev_persona_for('zh_macro') == 'macro_zh' and jf.jev_persona_for('macro_zh') == 'macro_zh'


def test_routing_reports_account_ids_on_fallback():
    out = jf.route_sources([{'id': 'a', 'title': 'Fed holds rates, Treasury yields fall', 'snippet': ''}], jev=None)
    assert out['a']['persona'] == 'macro_rates_en' and out['a']['account_id'] == 'en_macro'
