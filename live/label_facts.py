"""Name what each extracted figure is, in both languages.

The generic extractor takes a figure's subject from the words around it, which works on an
earnings release with labelled lines and fails on flowing prose. A BOJ statement produced
"in South Korea Chart 8 units" and "April and conduct purchases 2 trillion yen", and the Chinese
branch produced no subject at all — a bare "4000 亿日元" with nothing saying what it measured.

Regex was the wrong tool. Reading a sentence and saying what a number refers to is exactly what a
language model is good at, and it is not arithmetic, so it does not cross the line this system
holds: the model never touches the digits, the scale or the unit. It supplies a noun phrase and
nothing else, and a label containing a digit is rejected.

Written back into the packet as `subject_zh` / `subject_en` per fact, so it happens once per
document rather than once per draft.

Run: .venv/bin/python -B live/label_facts.py [--packet=<id>] [--force]
"""
from pathlib import Path
import sys, json, re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))
sys.path.insert(0, str(ROOT / 'live'))
from model_client import parse_json
from content.generate_slotted import local_call
import render_slots

STORE = ROOT / 'live/store'
BATCH = 8
TOKENS = 1200

HAS_DIGIT = re.compile(r'\d')
MAX_ZH, MAX_EN = 12, 6


def prompt_for(items):
    lines = []
    for i, f in enumerate(items, 1):
        lines.append(f"{i}. 数字「{f['source_span']['quote']}」出现在这句话里：\n"
                     f"   {f['context_sentence'][:220]}")
    return (
        "下面每一条，都有一个从原文中抽出的数字，以及它所在的原句。\n"
        "请说出**这个数字衡量的是什么**，用一个名词短语回答。\n\n"
        + '\n'.join(lines) + "\n\n"
        "规则：\n"
        f"  · 中文标签不超过 {MAX_ZH} 个字，英文标签不超过 {MAX_EN} 个词\n"
        "  · **标签里不能出现任何数字**，也不要写单位（万亿、percent 这些由系统处理）\n"
        "  · 只写这个数字是什么，不要加判断、不要加时间状语\n"
        "  · 如果这个数字来自图表编号、页码、脚注或其他非实质内容，两个标签都写 SKIP\n\n"
        "只输出 JSON：{\"labels\":[{\"n\":1,\"zh\":\"...\",\"en\":\"...\"}]}")


def clean(label, max_units, is_zh):
    s = (label or '').strip().strip('。.，,；;：:')
    if not s or s.upper() == 'SKIP':
        return None
    if HAS_DIGIT.search(s):
        return None
    if is_zh:
        return s[:max_units] if len(s) > max_units else s
    words = s.split()
    return ' '.join(words[:max_units])


def label_packet(packet, force=False):
    facts = [f for f in packet['facts']
             if f.get('unit') and render_slots.label_quality(f) >= 1]
    todo = [f for f in facts if force or not f.get('subject_zh')]
    if not todo:
        return {'labelled': 0, 'skipped': 0, 'already': len(facts)}

    labelled = skipped = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        try:
            r = local_call(prompt_for(chunk), 'fact_labels', TOKENS, temperature=.1)
            out = parse_json(r['text'])
        except Exception:
            continue
        by_n = {int(x.get('n', 0)): x for x in (out.get('labels') or []) if str(x.get('n', '')).strip().isdigit()}
        for j, f in enumerate(chunk, 1):
            row = by_n.get(j)
            if not row:
                continue
            zh = clean(row.get('zh'), MAX_ZH, True)
            en = clean(row.get('en'), MAX_EN, False)
            if not zh and not en:
                f['subject_skip'] = True
                skipped += 1
                continue
            f['subject_zh'], f['subject_en'] = zh, en
            f['subject_source'] = ('model read the source sentence and named the quantity; '
                                   'it supplied no digit, scale or unit')
            labelled += 1
    return {'labelled': labelled, 'skipped': skipped, 'candidates': len(todo)}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    paths = sorted((STORE / 'packets').glob('*.json'))
    if args.get('packet'):
        paths = [STORE / 'packets' / (args['packet'] + '.json')]
    for p in paths:
        pk = json.loads(p.read_text())
        res = label_packet(pk, force=bool(args.get('force')))
        pk['fact_labels'] = {**res, 'method': 'model names the quantity; code owns every figure'}
        p.write_text(json.dumps(pk, ensure_ascii=False, indent=2))
        print(f"  {pk['entity']:14} 标注 {res.get('labelled', 0):>3}  "
              f"跳过 {res.get('skipped', 0):>2}  候选 {res.get('candidates', res.get('already', 0))}")


if __name__ == '__main__':
    main()
