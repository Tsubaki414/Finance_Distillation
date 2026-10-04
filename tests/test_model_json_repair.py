import json
import pytest

from live.model_json import parse_object


def test_unescaped_inner_quotes_from_cjk_text_are_repaired():
    raw = '```json\n{"units": [{"exact_text": "美国当地时间10月1日，OpenAI"智能时代"平台发布", "n": 1}]}\n```'
    value = parse_object(raw)
    assert value['units'][0]['exact_text'] == '美国当地时间10月1日，OpenAI"智能时代"平台发布'
    assert value['units'][0]['n'] == 1


def test_valid_json_unchanged_and_structural_errors_still_raise():
    assert parse_object('{"a": "b \\"q\\" c"}') == {'a': 'b "q" c'}
    with pytest.raises(json.JSONDecodeError):
        parse_object('{"a": 1,, "b": 2}')
    with pytest.raises(ValueError):
        parse_object('[1, 2]')
