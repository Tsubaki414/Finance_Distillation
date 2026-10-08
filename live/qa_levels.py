"""QA never stalls on source numbers: number/period/metric/number_words,
no_judgment, data_list, no_disagreement and view_number_unbound are SOFT.
Trusted sources skip number checks. HARD: position_claim, trade_reco_specific,
self_contradiction, licence_tier_not_allowed, d_tier_source_leak, quote_not_exact,
missing_attribution_frame, provenance without a frame, the live/editorial_style.py HARD_CODES and the
live/span_grounding.py HARD_CODES (ungrounded_number / ungrounded_quote), the live/risk_rules.py HARD_CODES. Unknown codes
fail closed. Style and placement checks (incl. editorial_style.SOFT_CODES) are SOFT.
"""
from __future__ import annotations

import json
import re

from live import registry
from live.editorial_style import HARD_CODES as _STYLE_HARD, SOFT_CODES as _STYLE_SOFT
from live.span_grounding import HARD_CODES as _GROUND_HARD, SOFT_CODES as _GROUND_SOFT
from live.risk_rules import HARD_CODES as _RISK_HARD
from live.hook_voice import HARD_CODES as _HOOK_HARD, SOFT_CODES as _HOOK_SOFT, FIXES as _HOOK_FIXES

HARD = frozenset({
                  'licence_tier_not_allowed', 'd_tier_source_leak', 'quote_not_exact',
                  'missing_attribution_frame', 'position_claim', 'trade_reco_specific', 'self_contradiction', 'wrong_date_fact',
                  # fix26 (Oct 7): Sirius editorial-style blocks + Fiona's review; one targeted rewrite, then HOLD
                  *_STYLE_HARD,
                  # Oct 7 Sirius borrow item 2: a number / same-language quote no source span holds
                  *_GROUND_HARD,
                  # Oct 8 (36 accounts): contract addresses, guaranteed returns, scam-shaped calls, referral codes
                  *_RISK_HARD,
                  # Oct 8 evening (live/hook_voice.py): source forecast as own call, stale 'new high'
                  *_HOOK_HARD,
                  # Oct 7: inspiration_only sources (Delphi digest) are never cited, quoted or counted
                  'inspiration_only_number', 'inspiration_only_text', 'inspiration_only_cited'})
SOFT = frozenset({'stale_time_word', 'stale_number_as_current', 'number_not_in_units', 'period_not_in_units', 'number_metric_binding', 'number_words', 'no_judgment', 'data_list', 'no_disagreement', 'view_number_unbound', 'template_phrase', 'length_out_of_range', 'attribution_outside_frame',
                  'trade_reco_soft', 'author_identity', 'code_fence', 'translated_quote', 'exemplar_phrase_copied', 'research_summary', 'certainty_overreach', 'contradicts_prior_view', 'ignores_prior_view', 'view_not_recorded', 'cross_persona_claim_duplicate', 'thesis_grounding', 'emotion_drop', 'emotion_overfire', 'thin_judgment_pack', 'stylistic_repeat', 'judgment_label', 'phrase_ban', 'duplicate_topic', 'verify_source', 'info_dump', 'stance_cadence', 'verbatim_line1',
                  'direction_drift_unmarked', 'generic_credit_in_body',
                  'structure_repeat', 'shape_mismatch', 'number_run', 'internal_contradiction', 'hedged_opener',
                  'zh_register', 'market_feeling', 'thread_padding', 'revise_off_topic',
                  'phrase_repeat', 'theme_repeat', 'filler_closer',
                  'opener_move', 'length_band', 'zh_sentence_length', 'stance_copy',
                  'ai_template', 'zh_line_breaks', 'missing_why', 'missing_implication', 'zh_awkward_time',
                  'zh_intensifier', 'zh_translationese', 'speaker_first_person', 'connective_repeat',
                  'hedge_only', 'catchphrase_repeat', 'template_ending',
                  *_STYLE_SOFT, *_GROUND_SOFT, *_HOOK_SOFT})   # Oct 7 relax: question opener, emphasis, research cadence warn only
FIXES = {
    'template_ending': ('Do not close on "the market has not priced it" (市场还没充分定价 / 定价还不够充分 / 没有被充分计价 / '
                        '尚未反映在估值 / 后知后觉的资金 / not yet priced in). Replace the last line with a concrete consequence, '
                        'a condition, or what to watch next, from the units (收在具体后果、条件或接下来要盯的东西上).'),
    'hedge_only': ('Delete the hedge-only sentence(s) quoted in the detail - disclaimers, generic caveats, generic caution '
                   'advice, or a closing condition or 反过来说 / 换句话说 line that only restates the call in reverse (删掉只为防质疑的句子). Do not '
                   'replace them with another hedge; end on the call or its consequence. Keep a caveat only if it states a '
                   'concrete new fact or condition from the units that advances the argument.'),
    'catchphrase_repeat': ('Drop or rephrase the donor catchphrase(s) named in the detail: at most one per post and not one '
                           'already used in the recent drafts (口头禅一篇最多一个，最近用过的这篇不用).'),
    'stylistic_repeat': 'Vary the repeated stylistic phrase and closing; retain source facts.',
    'judgment_label': 'Drop the 「我的判断：」/「以我个人判断，」/「个人判断：」 label; state the judgment directly as a plain sentence.',
    'phrase_ban': 'Rephrase without the flagged filler or stylistic template.',
    'duplicate_topic': 'Continue the prior thread with a new beat, or switch subject/ticker.',
    'verify_source': 'Check the original source number and period with a human before publishing; do not invent a replacement.',

    'thin_judgment_pack': 'Lead with stance.account_view; do not invent non-fact units.',
    'author_identity': 'Rewrite in third person or credit the source author inside the frame; '
                       'never present the author\'s experience, holdings or returns as the account\'s.',
    'provenance_in_body': 'Drop the source name / link from the body; the frame already credits it.',
    'template_phrase': 'Rephrase without the listed template phrase.',
    'certainty_overreach': 'Match the stance and units: keep their hedges, do not add absolutes or forecasts.',
    'contradicts_prior_view': 'Stay consistent with the account\'s earlier call, or revise it explicitly with new evidence.',
    'ignores_prior_view': 'Continue or update the account\'s earlier call on this subject; do not invent a one-shot take.',
    'cross_persona_claim_duplicate': 'Another persona already owns this same-conclusion claim for the topic lane; keep as HOLD or reassign.',
    'thesis_grounding': 'Rewrite per the fixed repair instruction for the reason code (consensus needs consensus evidence; analogies are not evidence; drop ungrounded claims / off-thesis lines).',
    'emotion_drop': 'Put a real reaction in the first two lines and hold the brief\'s emotion register; do not soften into a calm recap.',
    'info_dump': 'Judgment post reads as a data dump: keep the call, cite at most 3 numbers, leave surplus units unused.',
    'stance_cadence': 'Rewrite account_view as one plain committed sentence without banned filler or meta-labels.',
    'verbatim_line1': 'Paraphrase line 1; keep the same call; do not copy thesis_lock verbatim.',
    'structure_repeat': 'Change the structure, not just the words: different opener and ending family than recent drafts '
                        '(no conditional falsifier ending again); follow composition_shape.',
    'shape_mismatch': 'Follow composition_shape: unconditional line 1, its ending_rule (no if / unless / 只要 / 除非 '
                      'ending unless the shape is falsifier) and its max_number_lines.',
    'hedged_opener': 'Open with the call said flat - drop 我觉得 / 我个人觉得 / I think / IMO from line 1 '
                     '(opinion markers are fine later in the body).',
    'number_run': 'At most 2 lines with numbers (unless composition_shape is data_punch); replace the extra number '
                  'line with one mechanism sentence (why / how it works).',
    'internal_contradiction': 'Make every line agree with line 1 (direction, timing and sequence); remove the line '
                              'that reverses the call.',
    'generic_credit_in_body': 'Drop the generic credit (券商研报 / 某投行 / "sell-side research" / "a big bank"); '
                              'say the adopted view as the account\'s own call - the frame credits the source.',
    'direction_drift_unmarked': 'The call changed direction vs the account\'s earlier view without marking a revise: '
                                'confirm the revise and say why, or keep the earlier direction.',
    'zh_register': ('Rewrite in the account\'s spoken Chinese: replace the research-note words listed (意味着 / 而非 / '
                    '以…为主 / 基准路径 / 结构性 / 实质性 / 显然 / 注定 …) and AI template phrases with plain short '
                    'sentences (把研报书面词换成口语短句，长句拆短); keep the same call, facts and numbers.'),
    'market_feeling': ('Drop what the market / many people supposedly think (很多人认为 / 市场普遍认为 / 大家都觉得); '
                       'state the account\'s own call directly (直接说自己的判断).'),
    'thread_padding': ('Cut the paragraph that restates an earlier one; every paragraph must add new information '
                       '(每段都要有新信息); if there is nothing new, write it shorter.'),
    'revise_off_topic': ('The revise link pointed at a prior call on a different subject; it was dropped - revise '
                         'only the earlier call on the same subject.'),
    'phrase_repeat': ('Reword the phrase this persona already used in a recent draft (cross-batch repeat); '
                      'keep the call and facts, say it in new words.'),
    'theme_repeat': ('Same theme / entity as a recent draft of this persona: pick a fresh source or add a clearly '
                     'new beat; flagged for the editor, no rewrite can fix the topic choice.'),
    'ai_template': 'State the call directly; no question-form "not X but Y" ("Just X? No, it\'s Y").',
    'zh_line_breaks': '长版按段落写：每段两三句连着写、句末带标点，段与段之间空一行；不要一句一行。',
    'opener_move': ('Open with zh_register.opening_move (or a different move than your recent drafts); '
                    'no 别… / 不要… / don\'t imperative opener.'),
    'length_band': ('Match composition_shape.length_target: a long shape gets a second paragraph with new evidence '
                    'or a new mechanism step; an over-long draft gets cut.'),
    'zh_sentence_length': '句子改短：一句一件事，按 zh_register.sentence_length 的中位数（约 18-23 字），最长别超过 35 字。',
    'missing_why': ('ZH: add one short sentence saying WHY the call holds - which supplied fact / number / event '
                    '(a fact or mechanism unit, not somebody\'s statement 表态/表示) causes it - in your own words '
                    '(一句说清原因：哪个事实/数字导致了这个判断); no stock lead-in; keep sentences short.'),
    'missing_implication': ('ZH: add one short sentence on what it means for markets/readers - who gains or loses, '
                            'what to watch next (一句说清影响：对市场/读者有什么后果) - in plain words, phrased '
                            'differently from recent drafts; no fixed connective (not 这意味着 every time).'),
    'zh_awkward_time': ('ZH: replace the awkward colloquial time / policy-path phrase (随后就会直接停手 / 走过场 / '
                        '直接放话 / 打没了) with plain neutral time words (之后 / 12月之后 / 下次会议前).'),
    'zh_intensifier': ('ZH: 去掉强化词/态度词（直接 / 纯粹 / 根本 / 完全 / 走过场 / 打没了 / 放话 …），情绪靠判断动词带出来；'
                       '原来用态度顶替的地方换成一句理由（units 里的事实）。'),
    'zh_translationese': ('ZH 翻译腔：照 register_anchors / style_exemplars 里中文博主说话的方式重写这几句——长定语拆开'
                          '（一个分句里「的」不超过两个），英文名词串改成主谓短句（「…的改善」→「…好转了」），少用「被」字句；'
                          '事实、数字和判断不变。'),
    'speaker_first_person': ('ZH: 讲话人（官员 / 分析师）的观点不能用他们的第一人称写：改成第三人称转述（「鲍曼的意思是…」'
                             '「她认为…」）或者当成本账号自己的判断用本账号口吻说；正文不出现「我们」。'),
    'connective_repeat': ('ZH: 换掉重复的连接词/副词（其实 / 这意味着 / 本质上 / 换句话说 …）：同一篇最多一次，最近几篇'
                          '用过的这篇不用；影响换个说法自然带出（后果是… / 接下来… / 影响到… / 直接说结果）。'),
    'stance_copy': '不要搬 thesis_lock 的原句和书面词（核心变量、叠加……），用自己的口语重说。',
    'filler_closer': ('Replace the empty closer (Carry on. / Stay tuned. / 拭目以待) with a last line that says '
                      'something: the implication, a verdict, or a pointed question.'),
    'research_summary': 'Write it as a post, not a research note: one call, one or two numbers, no lists.',
    'length_out_of_range': 'Trim or extend toward the post type length range.',
    'exemplar_phrase_copied': 'Rephrase: style exemplars are for voice only, never for wording.',
}
FIXES.update(_HOOK_FIXES)   # live/hook_voice.py
from live.editorial_style import FIXES as _STYLE_FIXES  # noqa: E402
FIXES.update(_STYLE_FIXES)
from live.span_grounding import FIXES as _GROUND_FIXES  # noqa: E402
FIXES.update(_GROUND_FIXES)
from live.risk_rules import FIXES as _RISK_FIXES  # noqa: E402
FIXES.update(_RISK_FIXES)
# D tier (source_expansion.md §6): never in the publishing chain, never named in a post.
D_TIER_NAMES = ('ReportGem', '环球报告', '慧博', '发现报告', '洞见研报', '三个皮匠', '进门财经', 'Alpha派', 'Scribd')


def level(finding, *, frame_found):
    code = finding.get('code')
    if code == 'provenance_in_body':
        return 'soft' if frame_found else 'hard'
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
