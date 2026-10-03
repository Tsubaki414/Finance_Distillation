"""Build a blind review packet for a person, and score it once they have filled it in.

Every quality number this project has is `model_reviewed`. The acceptance contract is explicit
that this is not the same thing — 「同模型自评分不能当真人」 — and that until a person submits,
human metrics stay `null` with status `pending`. So the only way that field ever becomes a number
is a packet like this one.

Design decisions, all aimed at the reviewer's time rather than at a tidy dataset:

  short        Sixteen items. A reviewer who runs out of patience halfway gives you eight
               judgements and a selection bias, which is worse than eight judgements honestly
               collected.
  one file     The items and the blanks are in the same markdown file, so reviewing is reading
               top to bottom and typing on one line per item. No switching windows.
  key apart    `answers.json` is written to a sibling directory and is not read by anything until
               `--score` runs. The reviewer never sees it, and neither does the model that wrote
               the pieces.
  five fields  human-or-machine, which persona, grounded, natural, how much editing. The contract
               asks for exactly these plus the reviewer's identity, and nothing more is collected
               because every extra field costs attention that the first five need.

Run:
    .venv/bin/python -B ml/human_review.py --build [--n=16]
    # ... a person fills in ml/blind/human/REVIEW.md ...
    .venv/bin/python -B ml/human_review.py --score --reviewer='<name>'
"""
from __future__ import annotations
from pathlib import Path
import sys, json, re, random, hashlib, datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
OUT = ROOT / 'ml/blind/human'
FORM = OUT / 'REVIEW.md'
KEY = OUT / 'answers.json'
RESULT = OUT / 'scored.json'

PERSONAS = {'macro': '宏观数据与资金流观察者', 'industry': '个股与产业链研究者',
            'trading': '交易系统与市场心理教练', 'unknown': '说不上来'}

# The whitespace either side of the colon must not cross a line. Written with \s* it did: an
# item left blank as "H72167: " let the match run past two newlines and capture the `---`
# separator as the answer, so an unanswered item was recorded as answered-but-unparseable.
ANSWER_LINE = re.compile(
    r'^[ \t]*(?P<id>[A-Z0-9]{6,8})[ \t]*[:：][ \t]*(?P<body>\S.*?)[ \t]*$', re.M)


def _machine_items(since=None, arms_only=False):
    """Gated drafts, optionally only those written after a cutoff.

    A second round exists to measure whether a change worked, so it must not contain drafts
    written before the change. Mixing them would average the old and new together and the
    comparison with round 1 would mean nothing.
    """
    import style as style_mod  # noqa: F401  (kept for parity with the corpus loader)
    rows = []
    for f in sorted((ROOT / 'live/store/drafts').glob('*.json')):
        d = json.loads(f.read_text())
        if d.get('status') != 'ready_for_queue' or not d.get('text'):
            continue
        if since and str(d.get('finished_at') or '') < since:
            continue
        # `finished_at` is UTC and a cutoff typed from a local clock silently excludes
        # everything — a --since=19:00 against drafts stamped 12:02Z returned zero items and
        # looked like "no drafts qualify". Selecting by arm says what is actually wanted.
        if arms_only and not (d.get('opinions_shown') or {}).get('arm'):
            continue
        # The arm is what the A/B turns on. Without it on the key a packet containing both
        # arms yields one detection rate and no attribution, which is how the third round came
        # to report 8/8 against a pipeline whose output was not in the packet at all.
        arm = (d.get('opinions_shown') or {}).get('arm')
        rows.append({'text': d['text'], 'lang': d.get('lang') or 'zh', 'truth': 'machine',
                     'persona': d.get('persona_id'), 'writer': d.get('writer_model') or 'local',
                     'mode': d.get('generation_mode') or 'profile_exemplars',
                     'arm': arm,
                     'opinions_seen': len((d.get('opinions_shown') or {}).get('posts') or []),
                     'detail': f"{d['account_id']}/{d.get('entity')} arm={arm}",
                     'draft_id': d['id']})
    return rows


def _seen_before():
    """Texts a reviewer has already been shown. Showing one twice tests memory, not writing."""
    seen = set()
    dirs = [OUT / 'round1', OUT] + sorted(OUT.glob('archived-*'))
    for d in dirs:
        form = d / 'REVIEW.md'
        if not form.is_file():
            continue
        body = form.read_text(encoding='utf-8')
        # Only a form somebody actually filled in counts. Generating a packet is not showing it
        # to anyone, and counting it as such made each rebuild eat its own candidates: a second
        # `--build` found one machine item left, a third would have found none.
        answered = [m for m in ANSWER_LINE.finditer(body)
                    if m.group('body').strip() not in ('', '---')]
        if not answered:
            continue
        for block in body.split('```')[1::2]:
            s = block.strip()
            if len(s) > 60:
                seen.add(s)
    return seen


_EN_FUNCTION = re.compile(r'\b(?:the|and|of|to|is|that|for|in|it|this|with|are|was|has|but|on)\b',
                          re.I)


def _really_english(text):
    """A Latin-script post is not necessarily an English one.

    The third blind round opened with a Danish post by AndreasSteno — a Danish macro analyst on
    the watchlist who sometimes writes in his own language. It carried `lang: en` because the
    declared field follows script, and it burned one of sixteen items: the reader's answer was
    「这不是英语也不是中文，what tf is this」.

    Counting English function words catches it and generalises past Danish, where a list of
    Nordic characters would not. Three of 5,206 posts are affected, which is small and still
    worth a guard — a blind item is expensive and there are only sixteen of them.
    """
    return len(_EN_FUNCTION.findall(text or '')) >= 3


def _human_items(machine, seed, exclude=()):
    """Real posts by the donors, length-matched and in the same language."""
    import style as style_mod
    by = style_mod.corpus()
    rnd = random.Random(seed)
    pool = [(donor, p) for donor, ps in by.items() for p in ps
            if len(p['text']) >= 200
            and (str(p.get('lang') or '').startswith('en') is False
                 or _really_english(p['text']))]
    used, out = set(exclude), []
    for m in machine:
        want = len(m['text'])
        zh = not str(m['lang']).startswith('en')
        cand = [(d, p) for d, p in pool
                if (not str(p.get('lang') or '').startswith('en')) == zh
                and p['text'] not in used and 0.6 * want <= len(p['text']) <= 1.7 * want]
        if not cand:
            continue
        d, p = min(cand, key=lambda dp: abs(len(dp[1]['text']) - want))
        used.add(p['text'])
        out.append({'text': p['text'], 'lang': 'zh' if zh else 'en', 'truth': 'human',
                    'persona': None, 'writer': 'human', 'mode': None,
                    'detail': f'real post by {d}', 'draft_id': None})
    return out


def _archive_if_filled():
    """Move a form that already has answers in it out of the way before writing a new one.

    `--build` wrote straight over `REVIEW.md`. On 2026-09-24 that destroyed sixteen completed
    answers — the only human verdicts this project has ever collected — and they survived solely
    because the mapping had been printed to a terminal minutes earlier. The answers took a person
    fifteen minutes to produce and no model can regenerate them.
    """
    if not FORM.is_file():
        return None
    answered = [m for m in ANSWER_LINE.finditer(FORM.read_text(encoding='utf-8'))
                if m.group('body').strip() not in ('', '---')]
    if not answered:
        return None
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    dest = OUT / f'archived-{stamp}'
    dest.mkdir(parents=True, exist_ok=True)
    for f in (FORM, KEY, RESULT):
        if f.is_file():
            f.rename(dest / f.name)
    return {'archived_to': str(dest), 'answers_preserved': len(answered)}


def build(n=16, seed=None, since=None, round_no=None, arms_only=False):
    archived = _archive_if_filled()
    if archived:
        print(f"  已归档上一轮 {archived['answers_preserved']} 条答案 -> {archived['archived_to']}")
    seed = seed if seed is not None else int(datetime.datetime.now().timestamp()) % 100000
    seen = _seen_before()
    machine = [m for m in _machine_items(since, arms_only) if m['text'].strip() not in seen]
    rnd = random.Random(seed)
    if arms_only:
        # Stratified by (arm, language). Shuffling twelve drafts and taking the first eight gave
        # three English 'with_opinions' against one Chinese, which is not a comparison — the arm
        # is the whole point of the packet and an unbalanced draw spends a reviewer's fifteen
        # minutes without being able to answer the question they were asked.
        strata = {}
        for m in machine:
            strata.setdefault((m.get('arm'), m['lang']), []).append(m)
        for v in strata.values():
            rnd.shuffle(v)
        per = max(1, (n // 2) // max(len(strata), 1))
        picked, leftovers = [], []
        for v in strata.values():
            picked += v[:per]
            leftovers += v[per:]
        rnd.shuffle(leftovers)
        machine = picked + leftovers[:max(0, n // 2 - len(picked))]
    human = _human_items(machine, seed, exclude=seen)
    items = machine + human
    rnd.shuffle(items)
    items = items[:n]

    blind, key = [], []
    for i, it in enumerate(items, 1):
        iid = 'H' + hashlib.sha256(f'{seed}:{i}:{it["text"][:40]}'.encode()).hexdigest()[:5].upper()
        blind.append({'id': iid, 'text': it['text']})
        key.append({'id': iid, **{k: v for k, v in it.items() if k != 'text'}})

    OUT.mkdir(parents=True, exist_ok=True)
    KEY.write_text(json.dumps({'seed': seed, 'round': round_no,
                               'machine_written_since': since,
                               'excluded_already_shown': len(seen),
                               'built_at': datetime.datetime.now().isoformat(),
                               'key': key}, ensure_ascii=False, indent=2))

    lines = [
        '# 人工盲评', '',
        f'{len(blind)} 条，预计 15 分钟。**答案键不在这个文件里**，'
        '在 `ml/blind/human/answers.json`，评完再看。', '',
        '## 怎么填', '',
        '每条下面有一行 `Hxxxxx:`，在冒号后面按顺序写五个值，用 `|` 隔开：', '',
        '```',
        'Hxxxxx: 机器 | macro | 4 | 3 | 中改',
        '```', '',
        '| 位置 | 含义 | 可填 |',
        '| --- | --- | --- |',
        '| 1 | 真人还是机器写的 | `真人` / `机器` / `说不准` |',
        '| 2 | 若是机器，像哪个人设 | `macro` / `industry` / `trading` / `-` |',
        '| 3 | 有据程度：说法有没有落到具体证据上 | 1–5，5 最好 |',
        '| 4 | 自然度：读起来像不像人写的 | 1–5，5 最好 |',
        '| 5 | 你要发这条的话得改多少 | `不改` / `轻改` / `中改` / `重写` |',
        '',
        '五项都填不动就只填第 1 项，空着的会被记为未作答而不是中间值。',
        '',
        '---', '',
    ]
    for it in blind:
        lines += [f"### {it['id']}", '', '```', it['text'].strip(), '```', '',
                  f"{it['id']}: ", '', '---', '']
    FORM.write_text('\n'.join(lines), encoding='utf-8')
    return blind, seed


GRADE = {'不改': 0, '轻改': 1, '中改': 2, '重写': 3}
VERDICT = {'真人': 'human', '机器': 'machine', '说不准': 'unsure'}


def _parse():
    text = FORM.read_text(encoding='utf-8')
    # Only lines that are an id followed by something other than an empty answer.
    out = {}
    for m in ANSWER_LINE.finditer(text):
        body = m.group('body').strip()
        if not body or body.startswith(('```', '#', '---', '|')):
            continue
        parts = [p.strip() for p in body.split('|')]
        # Read by meaning, not only by position. A real reviewer wrote `重写` on its own — an
        # edit grade with no verdict — and reading it positionally would have taken it as the
        # verdict, discarding both fields. The first human data this project has is not the place
        # for a parser that quietly mangles an answer it did not expect.
        rec = {'verdict': None, 'persona_guess': None, 'grounded': None, 'natural': None,
               'edit': None, 'raw': body, 'out_of_scale': []}
        nums = []
        for j, x in enumerate(parts):
            if x in VERDICT and rec['verdict'] is None:
                rec['verdict'] = VERDICT[x]
            elif x in GRADE and rec['edit'] is None:
                rec['edit'] = x
            elif x in PERSONAS and rec['persona_guess'] is None:
                rec['persona_guess'] = x
            elif re.fullmatch(r'-?\d+', x):
                nums.append((j, int(x)))
        # Two ratings in order: grounded then natural, whichever positions they landed in.
        for k, (_, v) in zip(('grounded', 'natural'), nums):
            rec[k] = v
            # The form declares 1-5. A reviewer used 0 to mean "not natural at all", which is a
            # real judgement outside a scale I chose; it is kept and flagged rather than dropped.
            if not 1 <= v <= 5:
                rec['out_of_scale'].append({k: v})
        out[m.group('id')] = rec
    return out


def score(reviewer):
    key = {k['id']: k for k in json.loads(KEY.read_text())['key']}
    got = _parse()
    # A verdict is what the detection rate needs; an answer with only a rating still carries
    # information and is counted where it applies rather than thrown away wholesale.
    answered = {i: a for i, a in got.items() if a.get('verdict')}
    rated_only = {i: a for i, a in got.items()
                  if not a.get('verdict') and (a.get('edit') or a.get('natural') is not None)}
    if not answered:
        return {'status': 'pending', 'answered': 0, 'items': len(key),
                'why': 'no item has been filled in yet; human metrics stay null'}

    mach = [(i, a) for i, a in answered.items() if key[i]['truth'] == 'machine']
    hum = [(i, a) for i, a in answered.items() if key[i]['truth'] == 'human']
    det = sum(1 for _, a in mach if a['verdict'] == 'machine')
    fp = sum(1 for _, a in hum if a['verdict'] == 'machine')
    persona_hits = [(i, a) for i, a in mach
                    if a['persona_guess'] and key[i].get('persona')]
    persona_right = sum(1 for i, a in persona_hits if a['persona_guess'] == key[i]['persona'])

    def avg(rows, field):
        v = [a[field] for _, a in rows if a.get(field) is not None]
        return round(sum(v) / len(v), 2) if v else None

    def edits(rows):
        v = [GRADE[a['edit']] for _, a in rows if a.get('edit')]
        return round(sum(v) / len(v), 2) if v else None

    by_mode, by_writer = {}, {}
    for i, a in mach:
        for bucket, k in ((by_mode, key[i].get('mode')), (by_writer, key[i].get('writer'))):
            if not k:
                continue
            b = bucket.setdefault(k, {'n': 0, 'called_machine': 0, 'natural': [], 'edit': []})
            b['n'] += 1
            b['called_machine'] += a['verdict'] == 'machine'
            if a.get('natural') is not None:
                b['natural'].append(a['natural'])
            if a.get('edit'):
                b['edit'].append(GRADE[a['edit']])
    for bucket in (by_mode, by_writer):
        for k, b in bucket.items():
            b['detection_rate'] = round(b['called_machine'] / b['n'], 3)
            b['natural_mean'] = round(sum(b['natural']) / len(b['natural']), 2) if b['natural'] else None
            b['edit_mean'] = round(sum(b['edit']) / len(b['edit']), 2) if b['edit'] else None
            b.pop('natural'), b.pop('edit')

    out = {
        'status': 'complete' if len(answered) == len(key) else 'partial',
        'reviewer': reviewer,
        'reviewed_at': datetime.datetime.now().isoformat(),
        'reference_label_type': 'human',
        'items': len(key), 'answered': len(answered),
        'machine_items': len(mach), 'human_items': len(hum),
        'detection_rate': round(det / len(mach), 3) if mach else None,
        'false_positive_rate': round(fp / len(hum), 3) if hum else None,
        'persona_identification_rate': (round(persona_right / len(persona_hits), 3)
                                        if persona_hits else None),
        'persona_guesses_made': len(persona_hits),
        'grounded_machine': avg(mach, 'grounded'), 'grounded_human': avg(hum, 'grounded'),
        'natural_machine': avg(mach, 'natural'), 'natural_human': avg(hum, 'natural'),
        'edit_burden_machine': edits(mach), 'edit_burden_human': edits(hum),
        'edit_scale': GRADE,
        'by_generation_mode': by_mode, 'by_writer': by_writer,
        'unanswered': sorted(set(key) - set(got)),
        'no_verdict_but_rated': sorted(rated_only),
        'out_of_scale_answers': {i: a['out_of_scale'] for i, a in got.items()
                                 if a.get('out_of_scale')},
        'limits': [
            'one reviewer; no inter-rater agreement can be computed from a single set of answers',
            'the reviewer built or supervised this system, so a machine item may be recognised '
            'from memory rather than from the writing',
            'sixteen items is a pilot size — a detection rate here has a wide interval',
        ],
    }
    RESULT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    if 'score' in args:
        r = score(args.get('reviewer') if isinstance(args.get('reviewer'), str) else 'unnamed')
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    blind, seed = build(int(args.get('n', 16)),
                        since=args.get('since') if isinstance(args.get('since'), str) else None,
                        round_no=args.get('round') if isinstance(args.get('round'), str) else None,
                        arms_only='arms-only' in args)
    import collections
    k = json.loads(KEY.read_text())['key']
    mix = collections.Counter((x['truth'], x.get('writer')) for x in k)
    print(f'已生成 {len(blind)} 条，seed={seed}')
    for (truth, writer), n in sorted(mix.items()):
        print(f'   {truth:8} {str(writer):14} {n}')
    print(f'\n  填这个文件： {FORM}')
    print(f'  答案键在：   {KEY}（评完再看）')
    print(f'  评完跑：     .venv/bin/python -B ml/human_review.py --score --reviewer=你的名字')


if __name__ == '__main__':
    main()
