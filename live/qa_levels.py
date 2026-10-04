"""Two-level post QA: HARD findings block a draft, SOFT findings only warn.

HARD (draft_status needs_review) is reserved for what can make a post wrong or
unlawful to publish:
  * numbers / periods / metric bindings that do not match the source units
    (number_not_in_units, period_not_in_units, number_metric_binding, and
    number words such as 翻倍 / doubled that no source span supports);
  * licence: a tier the post type does not accept, or a D-tier source named in
    the post (d_tier_source_leak);
  * a same-language direct quote that is not an exact substring of a source
    span (quote_not_exact);
  * a required attribution frame that is missing (missing_attribution_frame),
    and the source named / linked in the body when there is no frame.
Unknown codes are HARD (fail closed): a new check must be classified here.

SOFT (warning; draft stays draft_ready) covers style and placement: template
phrases, length out of range, the source named in the body while the frame is
present, attribution phrasing outside the frame, first person / borrowed
experience (with a fix hint), code fences, translated quotes.
Fabricated facts beyond numbers are covered by the claim_ledger contract
(ContractError) and semantic QA, not by these lexical checks.
"""
from __future__ import annotations

import json
import re

from live import registry

HARD = frozenset({'number_not_in_units', 'period_not_in_units', 'number_metric_binding',
                  'licence_tier_not_allowed', 'd_tier_source_leak', 'quote_not_exact',
                  'missing_attribution_frame'})
SOFT = frozenset({'template_phrase', 'length_out_of_range', 'attribution_outside_frame',
                  'author_identity', 'code_fence', 'translated_quote'})
FIXES = {
    'author_identity': 'Rewrite in third person or credit the source author inside the frame; '
                       'never present the author\'s experience, holdings or returns as the account\'s.',
    'provenance_in_body': 'Drop the source name / link from the body; the frame already credits it.',
    'template_phrase': 'Rephrase without the listed template phrase.',
    'length_out_of_range': 'Trim or extend toward the post type length range.',
}
# D tier (source_expansion.md §6): never in the publishing chain, never named in a post.
D_TIER_NAMES = ('ReportGem', '环球报告', '慧博', '发现报告', '洞见研报', '三个皮匠', '进门财经', 'Alpha派', 'Scribd')


def level(finding, *, frame_found):
    code = finding.get('code')
    if code == 'provenance_in_body':
        return 'soft' if frame_found else 'hard'
    if code == 'number_words':
        return 'soft' if finding.get('sourced') else 'hard'
    if code in SOFT:
        return 'soft'
    return 'hard'


def classify(findings, *, frame_found):
    out = []
    for f in findings:
        row = {**f, 'level': level(f, frame_found=frame_found)}
        if row['level'] == 'soft' and row['code'] in FIXES:
            row['fix'] = FIXES[row['code']]
        out.append(row)
    return out


def draft_status(findings):
    return 'needs_review' if any(f.get('level', 'hard') == 'hard' for f in findings) else 'draft_ready'


def summary(findings):
    return {'hard': sorted({f['code'] for f in findings if f.get('level', 'hard') == 'hard'}),
            'soft': sorted({f['code'] for f in findings if f.get('level') == 'soft'})}


def _d_tier_names():
    names = list(D_TIER_NAMES)
    for source_id, entry in json.loads(registry.LICENCE.read_text())['tiers'].items():
        if entry.get('tier') == 'D':
            names += [source_id, *(entry.get('aliases') or [])]
    return names


def d_tier_findings(body):
    low = body.casefold()
    return [{'code': 'd_tier_source_leak', 'detail': name} for name in _d_tier_names() if name.casefold() in low]


QUOTE = re.compile(r'“([^”]{6,})”|「([^」]{6,})」|"([^"]{6,})"')
CJK = re.compile(r'[\u4e00-\u9fff]')


def _is_zh(text):
    return len(CJK.findall(text)) * 3 >= len(text.strip())


def quote_findings(body, spans):
    from live.content_units import fold
    folded = [fold(s) for s in spans]
    findings = []
    for m in QUOTE.finditer(body):
        quote = next(g for g in m.groups() if g).strip()
        if any(fold(quote) in s for s in folded):
            continue
        same_language = any(_is_zh(quote) == _is_zh(s) for s in spans)
        findings.append({'code': 'quote_not_exact' if same_language else 'translated_quote', 'detail': quote[:80]})
    return findings
