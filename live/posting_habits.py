"""Small observed format cards; donor text stays in the ignored corpus."""
import json
from pathlib import Path
from live.exemplars import load_posts

CARDS_DIR = Path(__file__).resolve().parent / 'personas' / 'posting_habits'
GUIDANCE = ('Alternate longer threads with shorts; for short punchy posts prefer line breaks '
            'without trailing periods on intermediate lines.')


def build_card(persona, posts_dir=None):
    posts = [p for handle in persona.donor_weights for p in load_posts(handle, posts_dir)
             if p.get('text') and not p.get('rt') and not p.get('reply')]
    sizes = [len(p['text'].strip()) for p in posts]
    n = len(posts)
    thread_rate = round(sum(bool(p.get('thread_id') or p.get('is_thread')) for p in posts) / n, 3) if n else .2
    lines = [line.strip() for p in posts if len(p['text'].strip()) < 180 for line in p['text'].splitlines()[:-1] if line.strip()]
    return {'persona_id': persona.persona_id, 'basis': 'donor observations' if n else 'Fiona Oct 5 default; donor posts missing',
            'length_mix': {key: round(sum(test(s) for s in sizes) / n, 3) if n else default
                           for key, test, default in [('short', lambda s: s < 180, .4),
                                                      ('medium', lambda s: 180 <= s < 400, .4),
                                                      ('long', lambda s: s >= 400, .2)]},
            'thread_vs_single': {'thread_rate': thread_rate, 'single_rate': round(1 - thread_rate, 3),
                                 'method': 'thread_id/is_thread metadata; no length-based thread inference'},
            'short_line_break_habit': {'prefer_no_intermediate_periods': True,
                                       'observed_share': round(sum(not l.endswith(('.', '。')) for l in lines) / len(lines), 3) if lines else None},
            'sample_ids': [str(p.get('id')) for p in posts[:12]], 'guidance': GUIDANCE}


def load_card(persona):
    try:
        return json.loads((CARDS_DIR / (persona.persona_id + '.json')).read_text())
    except (OSError, ValueError):
        return build_card(persona)


def write_card(persona):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    card = build_card(persona)
    (CARDS_DIR / (persona.persona_id + '.json')).write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    return card
