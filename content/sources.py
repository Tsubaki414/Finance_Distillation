"""One way to ask for "a draft and the fact pack behind it", whichever pipeline made it.

Two pipelines grew separately. `content/*` was built around a single curated BLS packet and has
the whole downstream — platform packages, visuals, cross-language, traceability, the frontend.
`live/*` was built for the daily loop and stops at a draft. Nineteen files hardcoded the one
curated packet id, so nothing downstream could consume a live draft: the daily system produced
text and an operator got nothing they could take away.

The fix is not a second copy of the downstream under `live/`. It is for the downstream to stop
caring where the packet came from. This module is that boundary.

Two things differ between the sources and both are handled here rather than in every consumer:

  status field   curated drafts carry `content_status == 'ready_for_pipeline'`, live drafts
                 carry `status == 'ready_for_queue'`

  slot builder   a curated packet has a hand-written Chinese frame per fact id and a mandatory
                 coverage list; a live packet is `tier: generic` with an empty `required_core_ids`,
                 and its slots come from live/render_slots. Calling the curated builder on a live
                 packet returns nothing at all, which is the concrete reason the downstream could
                 not simply be pointed at the new directory.
"""
from pathlib import Path
import sys, json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'live'))

CURATED_PACKET = 'evidence_loop/sources/packets/75155f58f5a995e3.json'
CURATED_DRAFTS = 'content/drafts'
LIVE_DRAFTS = 'live/store/drafts'
LIVE_PACKETS = 'live/store/packets'


def load_packet(ref):
    """`ref` may be a packet id, a path, or None for the curated one."""
    if ref is None:
        return json.loads((ROOT / CURATED_PACKET).read_text())
    p = Path(ref)
    for cand in (p, ROOT / ref, ROOT / LIVE_PACKETS / f'{ref}.json',
                 ROOT / 'evidence_loop/sources/packets' / f'{ref}.json'):
        if cand.is_file():
            return json.loads(cand.read_text())
    raise SystemExit(f'packet not found: {ref}')


def is_generic(packet):
    return packet.get('tier') == 'generic' or not (
        packet.get('coverage', {}).get('required_core_ids'))


def build_slots(packet, lang='zh', limit=10):
    """The right slot builder for this packet, so a consumer never has to know the tier."""
    if is_generic(packet):
        import render_slots
        return render_slots.build(packet, lang=lang, limit=limit)
    from content.fact_slots import build_slots as curated
    return curated(packet, packet['coverage']['required_core_ids'])


def _ready(d):
    return (d.get('content_status') == 'ready_for_pipeline'
            or d.get('status') == 'ready_for_queue')


def drafts(where='all', only_ready=True):
    """Normalised drafts. `where` is 'curated', 'live' or 'all'.

    `only_ready` means different things on the two sides and is deliberately applied to one:

      live      `ready_for_queue` is the daily loop's own publish decision. A blocked live draft
                is the loop choosing to hold, so it must not reach a platform package.

      curated   the three curated drafts are a fixed audit set, two of which fail their draft-level
                form gate on purpose. Their packages *are* the artifact under review and carry
                their own blocking findings to the surface, so the set is always packaged in full.
                Filtering them by draft status silently dropped two of three and, with them, ten
                of the fifteen packages `handover/verification.json` counts.
    """
    out = []
    if where in ('curated', 'all'):
        for p in sorted((ROOT / CURATED_DRAFTS).glob('*.json')):
            d = json.loads(p.read_text())
            if not d.get('text'):
                continue
            out.append({
                'draft': d, 'origin': 'curated',
                'draft_id': d['id'], 'lang': 'zh',
                'persona_id': d.get('persona_id'),
                'label': d.get('persona_name') or d.get('persona_id'),
                'event': d.get('source_id'),
                'packet_ref': None,
                'account_id': None,
            })
    if where in ('live', 'all'):
        for p in sorted((ROOT / LIVE_DRAFTS).glob('*.json')):
            d = json.loads(p.read_text())
            if not d.get('text') or (only_ready and not _ready(d)):
                continue
            out.append({
                'draft': d, 'origin': 'live',
                'draft_id': d['id'], 'lang': d.get('lang') or 'zh',
                'persona_id': d.get('persona_id'),
                'label': d.get('account_name') or d.get('account_id'),
                'event': d.get('entity'),
                'packet_ref': d.get('packet_id'),
                'account_id': d.get('account_id'),
            })
    return out


def packet_for(row):
    return load_packet(row['packet_ref'])


def args_from(argv):
    """`--source=live|curated|all`, `--packet=<id|path>`, `--draft=<id>`."""
    a = {x.split('=', 1)[0][2:]: (x.split('=', 1)[1] if '=' in x else True)
         for x in argv if x.startswith('--')}
    return {'source': a.get('source', 'all'), 'packet': a.get('packet'),
            'draft': a.get('draft'), 'raw': a}


def select(argv, only_ready=True):
    """Every draft a command should act on, with its packet already resolved."""
    a = args_from(argv)
    rows = drafts(a['source'], only_ready=only_ready)
    if a['draft']:
        rows = [r for r in rows if r['draft_id'] == a['draft']]
    for r in rows:
        r['packet'] = load_packet(a['packet']) if a['packet'] else packet_for(r)
    return rows, a
