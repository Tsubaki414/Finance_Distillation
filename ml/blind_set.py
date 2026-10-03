"""Build a blind human-vs-machine set for an outside model to judge.

Items are shuffled behind opaque ids and the answer key is written to a separate file, so a judge
— and the assistant that built the generator — sees the text and nothing else. Scoring is a
later pass over the recorded judgements, in ml/blind_judge.py.

Fairness matters more than difficulty here. Human posts are length-matched to the generated
pieces, drawn in the same language, and filtered to analytical ones, because a one-line market
reaction against an eight sentence analysis tests format recognition, not quality.

Run: .venv/bin/python -B ml/blind_set.py [--seed=13] [--include-blocked]
"""
from pathlib import Path
import sys, json, glob, random, re, hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))
import style as style_mod

OUT = ROOT / 'ml/blind'

# A post has to be making an argument, not reacting. Without this the human side is dominated by
# one-liners and the test measures length.
ANALYTICAL = re.compile(r'因为|所以|如果|但是|意味着|说明|逻辑|判断|风险|预期|原因|机制|'
                        r'because|therefore|however|means|implies|suggests|risk|reason|'
                        r'the point|which is why')


def generated(include_blocked=False):
    """Generated pieces, optionally including the ones the gates refused.

    Queue-eligible drafts alone answer "would what we publish pass as human". They cannot answer
    it for English, because every English draft is currently held by the figure-density gate, so a
    set built from passing drafts only is silently a Chinese-only set that reports nothing about
    two of the four accounts. Blocked pieces are carried with `gate` recorded, so the two strata
    are scored apart and a blocked item is never counted as publishable output.
    """
    out = []
    for p in sorted(glob.glob(str(ROOT / 'live/store/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        ok = d.get('status') == 'ready_for_queue'
        if d.get('text') and (ok or include_blocked):
            out.append({'text': d['text'], 'lang': d['lang'], 'origin': 'machine',
                        'gate': 'candidate' if ok else 'blocked',
                        'writer': d.get('writer_model') or 'local',
                        'detail': f"live/{d['account_id']}/{d['entity']}",
                        'donor': d.get('language_donor')})
    for p in sorted(glob.glob(str(ROOT / 'content/drafts/*.json'))):
        d = json.loads(Path(p).read_text())
        ok = d.get('content_status') == 'ready_for_pipeline'
        if d.get('text') and (ok or include_blocked):
            out.append({'text': d['text'], 'lang': 'zh', 'origin': 'machine',
                        'gate': 'candidate' if ok else 'blocked', 'writer': 'local',
                        'detail': f"curated/{d['persona_id']}",
                        'donor': d.get('language_donor')})
    return out


def _same_language(post, lang):
    pl = (post.get('lang') or '').lower()
    return pl.startswith('en') if lang.startswith('en') else not pl.startswith('en')


def humans(gen, seed):
    """One real post per generated piece: same donor where possible, same language always.

    Pairing used to walk a flat donor list against sorted lengths, which crossed the languages —
    an English generated piece could be set against a Chinese real post. A judge separates those
    two on script alone, so every such pair tested nothing.
    """
    by = style_mod.corpus()
    rnd = random.Random(seed)
    all_posts = [(d, p) for d, ps in by.items() for p in ps]
    picked, used = [], set()
    for g in sorted(gen, key=lambda g: len(g['text'])):
        want, lang = len(g['text']), (g.get('lang') or 'zh')
        # the piece's own donor first, then anyone writing that language
        pools = [[(g.get('donor'), p) for p in by.get(g.get('donor')) or []], all_posts]
        pick = None
        for pool in pools:
            cand = [(d, p) for d, p in pool
                    if _same_language(p, lang) and p['text'] not in used
                    and 0.6 * want <= len(p['text']) <= 1.7 * want
                    and ANALYTICAL.search(p['text'])]
            if not cand:
                cand = [(d, p) for d, p in pool
                        if _same_language(p, lang) and p['text'] not in used
                        and len(p['text']) >= 120]
            if cand:
                pick = min(cand, key=lambda dp: abs(len(dp[1]['text']) - want))
                break
        if not pick:
            continue
        donor, post = pick
        used.add(post['text'])
        picked.append({'text': post['text'], 'lang': lang, 'origin': 'human', 'gate': 'real',
                       'detail': f'real post by {donor}', 'donor': donor, 'writer': 'human'})
    rnd.random()
    return picked


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    seed = int(args.get('seed', 13))
    gen = generated(include_blocked='include-blocked' in args)
    hum = humans(gen, seed)
    items = gen + hum
    random.Random(seed).shuffle(items)

    OUT.mkdir(parents=True, exist_ok=True)
    blind, key = [], []
    for i, it in enumerate(items, 1):
        iid = 'X' + hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:6].upper()
        # Strip nothing from the text itself; hiding wording would change what is being judged.
        blind.append({'id': iid, 'lang': it['lang'], 'chars': len(it['text']),
                      'text': it['text']})
        key.append({'id': iid, 'origin': it['origin'], 'gate': it.get('gate'),
                    'writer': it.get('writer'), 'detail': it['detail'],
                    'donor': it.get('donor')})

    (OUT / 'items.json').write_text(json.dumps(
        {'seed': seed, 'n': len(blind),
         'instruction': ('judge each item: human or machine, and why. Record judgements before '
                         'reading answers.json'),
         'items': blind}, ensure_ascii=False, indent=2))
    (OUT / 'answers.json').write_text(json.dumps(
        {'seed': seed, 'key': key}, ensure_ascii=False, indent=2))
    import collections
    mix = collections.Counter((k['gate'], b['lang']) for k, b in zip(key, blind))
    print(f"blind set: {len(blind)} items  ({sum(1 for k in key if k['origin']=='machine')} machine, "
          f"{sum(1 for k in key if k['origin']=='human')} human)")
    for (gate, lang), n in sorted(mix.items()):
        print(f"    {gate:10} {lang:3} {n}")
    print(f"  ml/blind/items.json   ← 判断用这个")
    print(f"  ml/blind/answers.json ← 判断写完再看")
    return blind


if __name__ == '__main__':
    main()
