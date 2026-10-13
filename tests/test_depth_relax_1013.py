from live import depth_check as dc

SRC = 'Polymarket is pricing an October rate hold at 84%, which implies a pause; odds of a 25 bp hike fell to 17%.'


def test_insight_plus_reaction_passes():
    body = ('Polymarket is pricing an October rate hold at 84%\n\nThat implies a pause is basically locked in\n\n'
            'are we really fading the hike risk this hard?')
    assert dc.findings(body, 'en', None, source_text=SRC) == []


def test_pure_headline_relay_held():
    assert dc.findings('Polymarket prices an October rate hold at 84%. Hike odds fell to 17%.', 'en', None,
                       source_text=SRC)[0]['code'] == 'depth'


def test_reaction_without_attributable_insight_held():
    assert dc.findings('Rate hold priced at 84%. Wild.', 'en', None, source_text=SRC)


def test_human_kind_needs_a_reaction():
    assert dc.findings('韩国股市大跌，币圈跟跌，绷不住', 'zh', 'reaction') == []
    assert dc.findings('韩国股市大跌，币圈跟跌', 'zh', 'reaction')
