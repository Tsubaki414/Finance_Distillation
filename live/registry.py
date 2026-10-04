"""Post type, persona and source licence registry (P0-4b).

Loads and validates live/post_types.json, live/personas/*.json and
live/source_licence.json. Everything here is deterministic: no model calls.
Persona voices are drafts until decision D2; a draft persona is never
publishable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POST_TYPES = ROOT / 'post_types.json'
PERSONAS = ROOT / 'personas'
LICENCE = ROOT / 'source_licence.json'
OWNED = ROOT / 'owned_accounts.json'
UNIVERSES = ROOT / 'account_source_universes.json'
DONOR_ROSTER = ROOT / 'donors' / 'roster.json'

LICENCE_TIERS = ('A', 'B', 'C', 'D')
WRITABLE_TIERS = ('A', 'B')  # C is topic-lead only, D is never used
PLACEMENTS = ('lead', 'footer', 'none')
VOICES = ('persona', 'source')
STATUSES = ('draft', 'approved', 'active', 'paused', 'retired')
REQUIRED_BANNED = frozenset({'claimed_positions', 'claimed_returns', 'source_author_experience'})
MIN_EXEMPLARS, MAX_EXEMPLAR_WEIGHT = 5, 0.35


class RegistryError(ValueError):
    pass


def _fail(message):
    raise RegistryError(message)


def validate_post_types(table):
    frames = table.get('frames')
    types = table.get('post_types')
    if not isinstance(frames, dict) or not isinstance(types, dict) or not types:
        _fail('post_types.json needs frames and post_types')
    for name, frame in frames.items():
        if frame.get('placement') not in PLACEMENTS:
            _fail(f'frame {name}: bad placement')
        if frame['placement'] != 'none':
            template = frame.get('template') or ''
            if not any('{' + key + '}' in template for key in ('speaker', 'publisher')):
                _fail(f'frame {name}: template must name speaker or publisher')
            for key in frame.get('requires') or []:
                if '{' + key + '}' not in template:
                    _fail(f'frame {name}: required field {key} not in template')
    for name, spec in types.items():
        length = spec.get('length') or {}
        if length.get('follows_source'):
            if length.get('min') is not None or length.get('max') is not None:
                _fail(f'{name}: follows_source length has no fixed range')
        else:
            lo, hi = length.get('min'), length.get('max')
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi)) or not 0 < lo < hi:
                _fail(f'{name}: length range must be 0 < min < max')
        for frame in [spec.get('frame'), *(spec.get('alternate_frames') or [])]:
            if frame not in frames:
                _fail(f'{name}: frame {frame} is not defined')
        if spec.get('voice') not in VOICES:
            _fail(f'{name}: voice must be persona or source')
        tiers = spec.get('licence_tiers')
        if not isinstance(tiers, list) or not tiers or not set(tiers) <= set(WRITABLE_TIERS):
            _fail(f'{name}: licence_tiers must be a non-empty subset of {WRITABLE_TIERS}')
        if spec['voice'] == 'persona' and frames[spec['frame']]['placement'] == 'none':
            _fail(f'{name}: a persona-voiced post must carry an attribution frame')
    return table


def load_post_types(path=POST_TYPES):
    return validate_post_types(json.loads(Path(path).read_text()))


@dataclass(frozen=True)
class PersonaSpec:
    persona_id: str
    version: str
    status: str
    account_id: str
    lang: str
    voice: dict
    post_type_mix: dict
    banned: tuple
    exemplar_accounts: tuple
    source_affinity: dict
    raw: dict = field(repr=False, compare=False)
    voice_card: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def donor_weights(self):
        resolved = resolve_donors(self.raw) if not self.raw.get('exemplar_accounts') and self.raw.get('donor_cluster') else self.raw
        return {e['handle']: e['weight'] for e in resolved.get('exemplar_accounts') or []}

    @property
    def publishable(self):
        return self.status in ('approved', 'active') and not self.voice.get('draft')


def validate_persona(raw, post_types):
    for key in ('persona_id', 'version', 'status', 'account_id', 'lang', 'voice',
                'post_type_mix', 'banned', 'source_affinity'):
        if key not in raw:
            _fail(f'persona {raw.get("persona_id")}: missing {key}')
    if raw['status'] not in STATUSES:
        _fail('persona status is invalid')
    stance = raw.get('stance')
    if stance is not None:
        from live.content_units import HORIZONS
        if not isinstance(stance, dict) or stance.get('horizon') not in HORIZONS:
            _fail('stance: invalid horizon')
        for key in ('prior', 'risk_appetite'):
            if not isinstance(stance.get(key), str) or not stance[key].strip():
                _fail('stance: missing ' + key)
        for key in ('beliefs', 'rejects'):
            if not isinstance(stance.get(key), list) or not stance[key] or any(not isinstance(v, str) or not v.strip() for v in stance[key]):
                _fail('stance: missing ' + key)
    types = post_types['post_types']
    mix = raw['post_type_mix']
    if not isinstance(mix, dict) or not mix or not set(mix) <= set(types):
        _fail('post_type_mix must reference defined post types')
    if any(not isinstance(v, (int, float)) or v <= 0 for v in mix.values()) or not math.isclose(sum(mix.values()), 1.0):
        _fail('post_type_mix weights must be positive and sum to 1')
    if not REQUIRED_BANNED <= set(raw['banned']):
        _fail(f'banned must include {sorted(REQUIRED_BANNED)}')
    tiers = (raw['source_affinity'] or {}).get('licence_tiers') or []
    if not tiers or not set(tiers) <= set(WRITABLE_TIERS):
        _fail('source_affinity.licence_tiers must be a subset of A/B')
    persona_voiced = any(types[t]['voice'] == 'persona' for t in mix)
    if persona_voiced:
        exemplars = raw.get('exemplar_accounts')
        if not isinstance(exemplars, list) or not exemplars:
            _fail('persona-voiced post types require exemplar_accounts')
        for e in exemplars:
            if not isinstance(e.get('handle'), str) or not isinstance(e.get('weight'), (int, float)) or e['weight'] <= 0:
                _fail('exemplar needs handle and positive weight')
        if raw['status'] in ('approved', 'active'):
            if len(exemplars) < MIN_EXEMPLARS or any(e['weight'] > MAX_EXEMPLAR_WEIGHT for e in exemplars):
                _fail(f'approved persona needs >= {MIN_EXEMPLARS} exemplars, each weight <= {MAX_EXEMPLAR_WEIGHT}')
            if raw['voice'].get('draft'):
                _fail('approved persona cannot have a draft voice')
    return raw


def load_donor_roster(path=None):
    return json.loads(Path(path or DONOR_ROSTER).read_text())


def resolve_donors(raw, roster=None):
    """A persona naming donor_cluster gets exemplar_accounts from the donor roster.

    The cluster must exist, match the persona language, and every donor must be
    a verified voice donor of that language; weights come from the roster.
    """
    cluster_name = raw.get('donor_cluster')
    if not cluster_name:
        return raw
    roster = roster or load_donor_roster()
    cluster = roster['persona_clusters'].get(cluster_name)
    if cluster is None:
        _fail(f'persona {raw.get("persona_id")}: unknown donor_cluster {cluster_name}')
    if cluster['lang'] != raw.get('lang'):
        _fail(f'persona {raw.get("persona_id")}: donor_cluster {cluster_name} is {cluster["lang"]}, persona is {raw.get("lang")}')
    accounts = []
    for d in cluster['donors']:
        info = roster['donors'].get(d['handle'].lower()) or {}
        if not info.get('verified') or info.get('donor_fit') != 'voice' or info.get('lang') != raw.get('lang'):
            _fail(f'donor {d["handle"]} in {cluster_name} is not a verified {raw.get("lang")} voice donor')
        accounts.append({'handle': d['handle'], 'weight': d['weight'], 'use': ['voice'], 'from': 'donor_roster'})
    if len(accounts) < MIN_EXEMPLARS or any(a['weight'] > MAX_EXEMPLAR_WEIGHT for a in accounts):
        _fail(f'donor_cluster {cluster_name} needs >= {MIN_EXEMPLARS} donors, each weight <= {MAX_EXEMPLAR_WEIGHT}')
    return {**raw, 'exemplar_accounts': accounts}


def _spec(raw):
    return PersonaSpec(raw['persona_id'], raw['version'], raw['status'], raw['account_id'], raw['lang'],
                       dict(raw['voice']), dict(raw['post_type_mix']), tuple(raw['banned']),
                       tuple(e['handle'] for e in raw.get('exemplar_accounts') or []),
                       dict(raw['source_affinity']), raw)


def load_personas(directory=PERSONAS, post_types=None):
    post_types = post_types or load_post_types()
    out = {}
    for path in sorted(Path(directory).glob('*.json')):
        raw = validate_persona(resolve_donors(json.loads(path.read_text())), post_types)
        if raw['persona_id'] in out:
            _fail(f'duplicate persona {raw["persona_id"]}')
        card_path = Path(directory) / 'voice_cards' / (str(raw.get('donor_cluster')) + '.json')
        spec = _spec(raw)
        if card_path.exists():
            from dataclasses import replace
            from live.voice_cards import sanitize_card
            spec = replace(spec, voice_card=sanitize_card(json.loads(card_path.read_text())))
        out[raw['persona_id']] = spec
    return out


def persona_for_account(account_id, personas=None):
    personas = personas or load_personas()
    matches = [p for p in personas.values() if p.account_id == account_id]
    if len(matches) != 1:
        _fail(f'account {account_id} must resolve to exactly one persona')
    return matches[0]


def _licence():
    return json.loads(LICENCE.read_text())['tiers']


def source_licence_tier(source_id):
    entry = _licence().get(source_id)
    tier = entry and entry.get('tier')
    return tier if tier in LICENCE_TIERS else None


def post_types_for_tier(tier, post_types=None):
    if tier not in WRITABLE_TIERS:
        return []
    post_types = post_types or load_post_types()
    return [name for name, spec in post_types['post_types'].items() if tier in spec['licence_tiers']]


def source_no_reproduction(source_id):
    return _licence().get(source_id, {}).get("no_reproduction") is True
