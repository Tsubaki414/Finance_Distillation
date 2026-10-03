"""Attribution frames per post_type (P0-4c).

A frame-bearing post names its source exactly once, in the frame (a lead
attribution or a source footer) rendered by code from live/post_types.json.
Everything outside the frame keeps the old rules: no URLs or provenance
footers, and the source author's experience or positions are never written
as the account's own first person. aphorism_translation has no frame and
keeps the original provenance_in_body rule.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from live import registry

PROVENANCE = re.compile(r'https?://|(?:^|\n)(?:来源|出处|译自|Source|Translated from)\s*[:：]', re.I)
URL = re.compile(r'https?://', re.I)
# Post-level only: a source line anywhere in the body (paragraph checks keep the line-start rule).
INLINE_PROVENANCE = re.compile(r'(?:来源|出处|译自|\bSource|Translated from)\s*[:：]', re.I)
# Identity checks that a frame never relaxes (fidelity.BIO plus first-person
# experience). Composed persona voices are first_person_rate "none" in P0.
EXPERIENCE = re.compile(
    r'\bI\s+(?:run|manage|charge|own|hold|earned|made|tested|have\s+been|\'ve\s+been|covered|worked)|'
    r'\bmy\s+(?:fund|portfolio|returns|clients|positions|book)|'
    r'我(?:自己)?(?:管理|持有|持仓|收取|赚|实测|一直|曾经|曾|在[^，。]{0,12}工作|做多|做空)|我的(?:基金|组合|客户|收益|仓位)', re.I)
FIRST_PERSON = re.compile(r'\b(?:I|my|we|our)\b|(?<!自)我(?!国)(?:们)?', re.I)
REGISTRY_FILE = Path(__file__).with_name('source_registry.json')


def publisher_name(source_id):
    for row in json.loads(REGISTRY_FILE.read_text()).get('sources', []):
        if row.get('id') == source_id:
            return row.get('name')
    return None


def _fields(source, speaker=None):
    publisher = publisher_name(source.get('source_id')) or source.get('publisher') or ''
    author = (source.get('author_name') or '').strip()
    if author.casefold() == publisher.casefold():
        author = ''  # author metadata that is really the publication (audit B7)
    # The speaker frame credits the article's author. When the unit's own
    # speaker is someone else (e.g. a CEO quoted in the article), crediting the
    # author would misattribute the view; fall back to a publisher frame.
    if speaker is not None and speaker.strip().casefold() != author.casefold():
        author = ''
    return {'publisher': publisher, 'speaker': author}


def render(post_type, source, post_types=None, speaker=None):
    """Return {'name','placement','text','names'} for the post type, or None if it has no frame.

    speaker: the chosen primary unit's speaker; the speaker frame is used only
    when it is the source's author.
    """
    table = post_types or registry.load_post_types()
    spec = table['post_types'][post_type]
    if table['frames'][spec['frame']]['placement'] == 'none':
        return None
    values = _fields(source, speaker)
    for name in [spec['frame'], *(spec.get('alternate_frames') or [])]:
        frame = table['frames'][name]
        if all(values.get(key) for key in frame.get('requires') or []):
            return {'name': name, 'placement': frame['placement'], 'text': frame['template'].format(**values),
                    'names': [v for v in (values['publisher'], values['speaker']) if v]}
    raise ValueError(f'{post_type}: no attribution frame can be rendered for {source.get("source_id")}')


def strip(text, frame):
    """Remove the declared frame from its placement; return (body, found)."""
    if not frame:
        return text, False
    marker = frame['text']
    if frame['placement'] == 'lead' and text.lstrip().startswith(marker):
        return text.lstrip()[len(marker):], True
    if frame['placement'] == 'footer' and text.rstrip().endswith(marker):
        return text.rstrip()[:-len(marker)], True
    return text, False


def strip_segments(segments, frame):
    """Paragraph-aligned chains: the lead frame lives in the first segment, the footer in the last."""
    if not frame or not segments:
        return [s['text'] for s in segments]
    texts = [s['text'] for s in segments]
    index = 0 if frame['placement'] == 'lead' else len(texts) - 1
    texts[index], _ = strip(texts[index], frame)
    return texts


def check(post_type, text, frame, licence_tier, post_types=None):
    """Post-level frame/identity/licence findings for one finished post."""
    table = post_types or registry.load_post_types()
    spec = table['post_types'][post_type]
    findings = []

    def flag(code, detail):
        findings.append({'paragraph_id': None, 'stage': 'post', 'code': code, 'detail': detail})

    if licence_tier not in spec['licence_tiers']:
        flag('licence_tier_not_allowed', f'{post_type} does not accept licence tier {licence_tier}')
    needs_frame = table['frames'][spec['frame']]['placement'] != 'none'
    body, found = strip(text, frame) if needs_frame else (text, False)
    if needs_frame and not found:
        flag('missing_attribution_frame', f'{post_type} requires its attribution frame at the declared place')
    named = [n for n in (frame or {}).get('names', []) if n.casefold() in body.casefold()]
    if PROVENANCE.search(body) or INLINE_PROVENANCE.search(body) or (frame and frame['text'] in body) or named:
        flag('provenance_in_body', 'Source named or linked outside the attribution frame')
    if EXPERIENCE.search(text) or (spec['voice'] == 'persona' and FIRST_PERSON.search(body)):
        flag('author_identity', 'Source experience/positions or first person written as the account')
    return findings
