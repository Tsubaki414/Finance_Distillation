"""P0-3c: verify Morris archive bodies with the P0-3a capture rule.

Evidence, in order: text variants embedded in the row's x_capture_metadata, or
the raw capture referenced by raw_import_ref ("path#/index"). A checkout moved
from another machine is rebased on the repository name. The stored body must
equal the verified body. Failures keep content_complete False with a reason.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from live.xsearch import COMPLETE_BASES, LEADING_MENTIONS, _core, body_completeness

ROOT = Path(__file__).resolve().parents[1]
REPO = 'Finance_Distillation'


def _variants_from_item(item):
    variants = {k: item[k] for k in ('text', 'fullText', 'full_text') if isinstance(item.get(k), str) and item[k].strip()}
    note = item.get('noteTweet') or item.get('note_tweet') or {}
    if isinstance(note, dict) and isinstance(note.get('text'), str) and note['text'].strip():
        variants['note_text'] = note['text']
    return variants


def _resolve(ref, root):
    path, _, frag = str(ref).partition('#')
    candidate = Path(path)
    if not candidate.is_absolute():
        rel = path
    elif ('/' + REPO + '/') in path:
        rel = path.split('/' + REPO + '/', 1)[1]
    else:
        return None, None, frag
    full = Path(root) / rel
    return (full if full.is_file() else None), rel, frag


def _post_id(row):
    m = re.search(r'/status/(\d+)', str(row.get('url') or ''))
    return m.group(1) if m else (str(row['post_id']) if row.get('post_id') else None)


def _raw_item(full, frag, row):
    data = json.loads(full.read_text())
    items = data if isinstance(data, list) else data.get('items', [])
    pid = _post_id(row)
    if pid:
        hit = [x for x in items if isinstance(x, dict) and str(x.get('id') or x.get('tweetId')) == pid]
        if hit:
            return hit[0]
    m = re.fullmatch(r'/?(?:items/)?(\d+)', frag or '')
    if m and int(m.group(1)) < len(items) and not pid:
        return items[int(m.group(1))]
    return None


def verify_archive_row(row, root=ROOT):
    if row.get('content_complete') is True:
        return row
    out = copy.deepcopy(row)
    info = {'status': 'unverified'}
    variants, truncated = None, False
    for item in row.get('context_items') or []:
        if isinstance(item, dict) and item.get('kind') == 'x_capture_metadata' and item.get('text_variants'):
            variants, info['evidence'] = dict(item['text_variants']), 'embedded_variants'
            break
    if variants is None and row.get('raw_import_ref'):
        full, rel, frag = _resolve(row['raw_import_ref'], root)
        if full is None:
            info['reason'] = 'raw_ref_unresolvable'
        else:
            info.update(evidence='raw_import', raw_ref_resolved=rel)
            try:
                item = _raw_item(full, frag, row)
            except (ValueError, OSError):
                item = None
            if item is None:
                info['reason'] = 'raw_item_not_found'
            else:
                variants = _variants_from_item(item)
                truncated = any(item.get(k) is True for k in ('truncated', 'isTruncated', 'is_truncated'))
    if variants is None:
        info.setdefault('reason', 'no_capture_evidence')
        out['archive_verification'] = info
        return out
    chosen, _, basis = body_completeness(variants)
    if truncated:
        basis = 'provider_truncated'
    info['basis'] = basis
    stored = LEADING_MENTIONS.sub('', _core(str(row.get('original_text', row.get('text', '')))))
    if basis not in COMPLETE_BASES:
        info['reason'] = basis
    elif stored != LEADING_MENTIONS.sub('', _core(variants[chosen])):
        info['reason'] = 'stored_body_differs_from_capture'
    else:
        info['status'] = 'verified'
        out.update(content_complete=True, completeness_basis=basis,
                   completeness_evidence='capture_internal_consistency')
    out['archive_verification'] = info
    return out
