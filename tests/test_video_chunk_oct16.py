"""Oct 16 FD_VIDEO_CHUNK: semantic chunking, merge, per-source cap, source check of numbers / names (no network, no model)."""
import pytest

from live import video_src
from live.distillation_source import digest, paragraphs
from live.content_units import validate_units_partial

from datetime import datetime, timezone
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ('FD_VIDEO_CHUNK', 'FD_VIDEO_CHUNK_CHARS', 'FD_VIDEO_MAX_CHUNKS', 'FD_VIDEO_SOURCE_USD', 'FD_VIDEO_EXTRACT_S'):
        monkeypatch.delenv(k, raising=False)


def long_text(n=40):
    return '\n\n'.join(f'第{i}段：这是一个关于储蓄习惯的句子，编号{i}。再来一句关于复利的说明，数字是{i * 7 + 100}。' * 3 for i in range(n))


def test_chunks_cover_text_cut_on_paragraph_boundaries_with_small_overlap():
    t = long_text()
    spans = video_src.chunk_spans(t, target=1500, overlap=300, max_chunks=99)
    assert len(spans) > 3 and spans[0][0] == 0 and spans[-1][1] == len(t.rstrip())
    for (a, b), (a2, b2) in zip(spans, spans[1:]):
        assert a < a2 <= b                       # consecutive chunks overlap (or touch), never leave a gap
        assert b - a2 <= 300 + 5                 # overlap stays small
        assert b - a <= 1500
        assert t[b - 1] in '。\n' or t[b:b + 1] in ('\n', '')    # cut at a paragraph / sentence end
        assert t[a2 - 2:a2] == '\n\n' or t[a2 - 1] == '。'


def test_timestamp_lines_are_cut_between_lines():
    t = '\n'.join(f'[0:{i // 60:02d}:{i % 60:02d}] ' + 'word ' * 12 for i in range(200))
    for a, b in video_src.chunk_spans(t, target=1000, overlap=200, max_chunks=99):
        assert t[a:a + 1] == '[' and (b == len(t.rstrip()) or t[b:].lstrip().startswith('['))


def test_short_text_is_one_chunk_and_max_chunks_caps():
    assert video_src.chunk_spans('短文本。') == [(0, 4)]
    assert len(video_src.chunk_spans(long_text(), target=1000, overlap=100, max_chunks=3)) == 3


def test_extract_chunks_merge_shift_offsets_and_back_half_units(monkeypatch):
    t = long_text(160)
    src = {'id': 'video-9', 'source_id': video_src.SOURCE_ID, 'original_text': t, 'source_hash': digest(t), 'adapter': 'video_idea'}
    seen_chunks = []

    def fake_batch(group, client, **kw):
        s = group[0]
        seen_chunks.append(s['original_text'])
        p = paragraphs(s['original_text'])[-1]            # one unit on the last paragraph of every chunk
        raw = {'kind': 'fact', 'statement': '把钱先存起来再花' + '嗯' * len(seen_chunks) + '。', 'source_spans': [{'paragraph_id': p['paragraph_id'], 'exact_text': p['exact_text'][:30]}],
               'speaker': 'author', 'speaker_type': 'author', 'freshness_class': 'current'}
        units, _ = validate_units_partial(s, {'units': [raw]}, 'B')
        return {s['id']: units}

    class Budget:
        def __init__(self): self.n = 0
        def spent(self): return self.n * 0.01
        def set_cap(self, c): pass
        class BudgetExceeded(Exception): pass

    class Db:
        def __init__(self): self.rows = []
        def add(self, src, units, adapter=None):
            self.rows += units
            return {'added': len(units)}
        def set_persona_tags(self, tags, th): pass
    monkeypatch.setenv('FD_VIDEO_CHUNK_CHARS', '1500')
    monkeypatch.setenv('FD_VIDEO_MAX_CHUNKS', '20')
    monkeypatch.setenv('FD_VIDEO_SOURCE_USD', '1')
    b = Budget()
    orig = fake_batch

    def counting(group, client, **kw):
        b.n += 1
        return orig(group, client, **kw)
    db, state = Db(), {}
    stats = video_src.extract(db, [src], client=None, budget=b, cost_cap_usd=9, fence_usd=9, state=state,
                              now=NOW, extract_batch=counting)
    assert stats['chunks'] == len(seen_chunks) >= 4 and stats['units_added'] == len(db.rows) and len(db.rows) >= 4
    # spans point into the FULL transcript, with the full source hash, and the unit id is the full-text one
    for u in db.rows:
        sp = u['source_spans'][0]
        assert t[sp['start']:sp['end']] == sp['exact_text'] and sp['source_hash'] == src['source_hash']
        assert u['unit_id'].startswith('cu-')
    assert max(u['source_spans'][0]['start'] for u in db.rows) > video_src.MAX_SOURCE_CHARS   # back half reached
    assert len({u['unit_id'] for u in db.rows}) == len(db.rows)


def test_per_source_cost_cap_and_flag_off(monkeypatch):
    t = long_text()
    src = {'id': 'video-8', 'source_id': video_src.SOURCE_ID, 'original_text': t, 'source_hash': digest(t)}
    monkeypatch.setenv('FD_VIDEO_CHUNK_CHARS', '1500')
    monkeypatch.setenv('FD_VIDEO_SOURCE_USD', '0.025')
    calls = []

    class Budget:
        n = 0
        def spent(self): return self.n * 0.01
        def set_cap(self, c): pass
        class BudgetExceeded(Exception): pass

    b = Budget()

    def fb(group, client, **kw):
        b.n += 1
        calls.append(len(group[0]['original_text']))
        return {group[0]['id']: []}

    class Db:
        def add(self, *a, **k): return {'added': 0}
        def set_persona_tags(self, *a): pass
    st = video_src.extract(Db(), [src], client=None, budget=b, cost_cap_usd=9, fence_usd=9, state={}, now=NOW, extract_batch=fb)
    assert len(calls) == 3 and st['chunks_deferred'] > 0          # 0.01 x 3 >= cap 0.025 -> stop after the 3rd call
    calls.clear()
    monkeypatch.setenv('FD_VIDEO_CHUNK', '0')                      # rollback: one call, whole text as given
    video_src.extract(Db(), [src], client=None, budget=Budget(), cost_cap_usd=9, fence_usd=9, state={}, now=NOW, extract_batch=fb)
    assert calls == [len(t)]
    assert not video_src.chunking()


def test_wall_clock_stops_further_chunks(monkeypatch):
    t = long_text()
    src = {'id': 'video-7', 'source_id': video_src.SOURCE_ID, 'original_text': t, 'source_hash': digest(t)}
    monkeypatch.setenv('FD_VIDEO_CHUNK_CHARS', '1500')
    monkeypatch.setenv('FD_VIDEO_EXTRACT_S', '10')
    now = [0.0]
    calls = []

    class Budget:
        def spent(self): return 0
        def set_cap(self, c): pass
        class BudgetExceeded(Exception): pass

    def fb(group, client, **kw):
        calls.append(1); now[0] += 6
        return {group[0]['id']: []}

    class Db:
        def add(self, *a, **k): return {'added': 0}
        def set_persona_tags(self, *a): pass
    st = video_src.extract(Db(), [src], client=None, budget=Budget(), cost_cap_usd=9, fence_usd=9, state={}, now=NOW,
                           extract_batch=fb, clock=lambda: now[0])
    assert len(calls) == 2 and st['chunks_deferred'] > 0


# ---------------------------------------------------------------- source check

SRC = ('今年苹果公司的利润是 1,200 亿美元，Tesla 的交付量约 180万 辆。Mike Smith 说储蓄率达到 35% 才安全。'
       '一共有三十条规则，其中前十二条最重要。')


def unit(statement, **kw):
    return dict({'unit_id': 'u', 'kind': 'fact', 'statement': statement, 'source_spans': [], 'numbers': []}, **kw)


def test_numbers_in_source_pass_and_missing_numbers_are_dropped():
    kept, flagged = video_src.verify_units([unit('储蓄率 35% 比较稳妥。'), unit('储蓄率 45% 比较稳妥。'),
                                            unit('利润约为 1200 亿。'), unit('规则一共三十条，前十二条重要。'),
                                            unit('规则一共四十条。'), unit('交付量约 180 万。')], SRC)
    assert [u['statement'] for u in kept] == ['储蓄率 35% 比较稳妥。', '利润约为 1200 亿。', '规则一共三十条，前十二条重要。', '交付量约 180 万。']
    assert {f['detail'] for f in flagged} == {'45%', '四十'} and all(f['reason'] == 'number_not_in_source' for f in flagged)


def test_company_names_must_be_in_source_and_people_never_pass():
    kept, flagged = video_src.verify_units([unit('苹果公司利润很高。'), unit('谷歌公司利润很高。'), unit('Tesla 交付量增长。'),
                                            unit('Nvidia 交付量增长。'), unit('Mike Smith 认为要存钱。'),
                                            unit('王先生认为要存钱。'), unit('先存后花更稳妥。')], SRC)
    assert [u['statement'] for u in kept] == ['苹果公司利润很高。', 'Tesla 交付量增长。', '先存后花更稳妥。']
    assert {(f['reason'], f['detail']) for f in flagged} == {('name_not_in_source', '谷歌公司'), ('name_not_in_source', 'Nvidia'),
                                                             ('person_name', 'Mike Smith'), ('person_name', '王先生')}


def test_numbers_in_view_and_numbers_field_are_checked():
    u = unit('储蓄要有节奏。', numbers=[{'text': '99%', 'metric': 'rate'}], view={'subject': '储蓄', 'reasoning': ['约 35% 才安全']})
    kept, flagged = video_src.verify_units([u], SRC)
    assert not kept and flagged[0]['detail'] == '99%'


def test_copy_rule_and_clean_units_unchanged():
    assert video_src.VERBATIM_CHARS == 12
    body = '沟通的本质从某个角度来讲其实就是示弱，我们很多人不会示弱。'
    src = {'source_id': video_src.SOURCE_ID, 'original_text': body}
    assert [f['code'] for f in video_src.findings(body, src)] == ['video_verbatim']
    assert video_src.findings('先示弱再沟通往往更顺。', src) == []
    kept, dropped = video_src.clean_units([unit('作者说要先听完。')])
    assert dropped == 1
