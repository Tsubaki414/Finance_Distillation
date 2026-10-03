"""Prompt artefacts that reached the finished text.

Found by reading eighteen pieces blind, not by any gate. Every one of these shipped as
`ready_for_queue`:

    "Buy Japanese Yen (JPY) $5[figure withheld] bil."
        — the masking marker used to hide off-table figures, printed in the article

    "A threshold in the invalidation sentence is the only figure allowed outside the table."
        — a rule from the prompt, copied into the piece as if it were a sentence

    "价格与工时这条线显示平均时薪环比上涨 0.3%"
        — a heading from the generation skeleton, used as prose, in all three curated drafts

    "失效条件：若私人非农平均周工时变化 0."
        — the last sentence cut off mid-figure

The numeric audit could not catch any of them: none is a wrong number. They are the scaffolding
of the machine showing through, which is a different failure and needs its own check.
"""
from __future__ import annotations
import re

BLOCKING = 'blocking'
WARNING = 'warning'

# Markers this pipeline itself inserts. Any of them in the output is a leak by definition.
#
# The list is kept past the life of each marker on purpose. When the bracketed `[figure withheld]`
# leaked, it was replaced by the plainer "a figure" and this list was not updated, so the next
# round of leaks — "touching a figure per dollar", "as suggested by Chart a figure", and
# "$5a figure bil." inside a quotation — shipped as `ready_for_queue` and were found by an outside
# judge instead. A detector that only knows the marker it was written for is worse than none: it
# reports clean while the same failure walks past in new clothes.
MASKS = ('[figure withheld]', '〔数字略〕', '[redacted-local-path]', '某个数值')

# "a figure" is ordinary English, so it is flagged only where a number belongs: glued to digits or
# currency, or followed by a unit. That covers every observed leak without touching real prose.
FIGURE_MARKER = re.compile(
    r'(?:[\d$€£¥]\s*a figure)'
    r'|(?:\ba figure\s+(?:per|a|an|%|percent|bps|basis points|billion|million|trillion|'
    r'dollars?|yen|euros?|points?|times|x)\b)', re.I)

# Furniture from the prompt: the slot table, and a chart that exists only as an instruction. The
# finished piece is read by someone who has neither.
FURNITURE = re.compile(
    r'\b(?:the|this|that|a)\s+table\b|\bin the table\b|\bChart a\b|\bsee (?:the )?chart\b'
    r'|下表|上表|表中|表内|表格中', re.I)

# Instruction language. These read as sentences, so only a literal match is used — a piece may
# legitimately discuss thresholds or invalidation.
RULE_PHRASES = (
    'the only figure allowed outside the table',
    'must match the table',
    'word for word, including unit',
    '与下表一字不差', '一字不差，包括单位', '只输出 JSON', 'return json only',
    'set kind to interpretation', 'kind 字段', 'kind 必须写',
    '只挑 3 到 4 个最能支撑判断的数字', 'place it verbatim',
)

# Skeleton headings. They were section labels in the prompt and are not how anyone writes.
# Example sentences the prompt used to quote as illustrations of a short sentence. The writer
# pasted them instead of writing its own: all fifteen drafts in the store carried one, including
# every queue-eligible piece, which means part of the measured gain in sentence-length variation
# was the model inserting a canned line rather than changing its rhythm. The prompt no longer
# quotes them; these stay so the regression is visible if anyone quotes an example again.
PROMPT_EXAMPLES = (
    'That is the whole story.', 'I do not buy it.', '这才是关键。', '我不这么看。',
)

SKELETON = (
    '价格与工时这条线', '修正与参与率改变读法', '修正与参与率改变了前面的读法',
    '结构层面来看，哪些行业在增', '把它放进更长的时间尺度看',
    'the strongest reading against you', 'what would make you wrong and what to watch',
    # The Chinese half of that same English entry, missing until a draft used it. The prompt
    # listed the four obligations by name — 「最强的相反读法」 among them — and two of three
    # drafts opened a paragraph with 「最强的相反读法是」, using the prompt's noun phrase as a
    # section heading. The English string had been caught and listed here long before; nobody
    # added the translation, so the same leak ran undetected on the language that matters most.
    '最强的相反读法', '相反的读法是', '什么情况会证明你错',
)

SLOT_LABEL = re.compile(r'\b[LES]\d{2}\b')
# A sentence that stops on a bare figure, or on a scale word with nothing after it.
TRUNCATED = re.compile(r'(?:^|[。！？.!?])\s*[^。！？.!?\n]{4,}?'
                       r'(?:\d+(?:\.\d*)?|万|亿|万亿|trillion|billion|million)\s*[。.]\s*$')


def check(text: str, sentences=None):
    """Findings for one finished piece. Blocking: none of these may ship."""
    t = text or ''
    f = []

    hit = [m for m in MASKS if m in t]
    hit += [m.group(0).strip() for m in FIGURE_MARKER.finditer(t)]
    if hit:
        f.append({'code': 'mask_marker_in_output', 'severity': BLOCKING,
                  'detail': (f'the masking marker used to hide off-table figures is in the text: '
                             f'{hit}')})

    furniture = [m.group(0).strip() for m in FURNITURE.finditer(t)]
    if furniture:
        f.append({'code': 'prompt_furniture_in_output', 'severity': BLOCKING,
                  'detail': (f'the piece refers to the slot table or to a chart that exists only '
                             f'in the prompt: {sorted(set(furniture))}')})

    low = t.lower()
    rules = [p for p in RULE_PHRASES if p.lower() in low]
    if rules:
        f.append({'code': 'prompt_rule_in_output', 'severity': BLOCKING,
                  'detail': f'instruction text copied into the piece: {rules}'})

    ex = [p for p in PROMPT_EXAMPLES if p in t]
    if ex:
        f.append({'code': 'prompt_example_sentence', 'severity': BLOCKING,
                  'detail': (f'a sentence the prompt gave as an illustration was used as '
                             f'writing: {ex}')})

    sk = [p for p in SKELETON if p in t]
    if sk:
        f.append({'code': 'skeleton_heading_in_prose', 'severity': BLOCKING,
                  'detail': (f'section headings from the generation skeleton used as writing: '
                             f'{sk}')})

    ids = SLOT_LABEL.findall(t)
    if ids:
        f.append({'code': 'slot_label_in_output', 'severity': BLOCKING,
                  'detail': f'system slot labels in the text: {sorted(set(ids))}'})

    rows = sentences or []
    last = (rows[-1].get('text') if rows else t).strip() if (rows or t) else ''
    if last and TRUNCATED.search(last):
        f.append({'code': 'truncated_ending', 'severity': BLOCKING,
                  'detail': f'the piece stops mid-figure: "{last[-42:]}"'})
    elif last and not re.search(r'[。！？.!?」”）)]\s*$', last):
        # Warning, not blocking. Measured against 1,255 real posts by these donors it fired on
        # **32.9%** of them — one in three. Ending a post without terminal punctuation is ordinary
        # on X, not evidence that generation was cut off. The check that actually detects
        # truncation is `truncated_ending` above, which stops on a bare figure and fires at 0.2%.
        # A gate that rejects a third of the corpus it is imitating is enforcing a rule the
        # authors do not follow. See content/gate_calibration.py.
        f.append({'code': 'unterminated_ending', 'severity': WARNING,
                  'detail': (f'the last sentence has no ending: "{last[-42:]}" — '
                             f'reported, not blocked: 32.9% of these donors own posts end this '
                             f'way')})

    blocking = [x for x in f if x['severity'] == BLOCKING]
    return {'findings': f, 'blocking_count': len(blocking),
            'status': 'failed' if blocking else 'passed',
            'check_version': 'leak-v3'}


FAULT_ZH = {
    'mask_marker_in_output': '正文里出现了系统的遮蔽标记。那是给你看的占位，不能写进稿子；'
                             '需要那个数字就换一种说法，不要保留标记。',
    'prompt_rule_in_output': '正文里抄进了这份指令本身的句子。指令不是稿子的一部分。',
    'skeleton_heading_in_prose': '正文里出现了结构提示词（如「价格与工时这条线」）。'
                                 '那是写作提纲的小标题，不是人会写的话。',
    'slot_label_in_output': '正文里出现了系统编号（L01 这类）。',
    'prompt_furniture_in_output': '正文提到了「表」或某张图。读者手上没有表也没有图，'
                                  '把那个数字直接写出来。',
    'prompt_example_sentence': '上一稿直接用了指令里举例的那句话。那只是示意，不是可以搬的句子。'
                               '短句要写你自己的话。',
    'truncated_ending': '最后一句在数字处断掉了，把它写完。',
    'unterminated_ending': '最后一句没有结束标点，把它写完。',
}
FAULT_EN = {
    'mask_marker_in_output': 'The masking marker appears in the text. It is a placeholder for '
                             'reading, not something to print; rephrase instead of keeping it.',
    'prompt_rule_in_output': 'A sentence from these instructions was copied into the piece.',
    'skeleton_heading_in_prose': 'A section heading from the outline was used as prose.',
    'slot_label_in_output': 'A system slot label appears in the text.',
    'prompt_furniture_in_output': 'The piece refers to the table or to a chart. The reader has '
                                  'neither; state the figure instead.',
    'prompt_example_sentence': 'A sentence the instructions gave as an illustration was used as '
                               'writing. Write your own short sentence instead.',
    'truncated_ending': 'The last sentence stops on a figure. Finish it.',
    'unterminated_ending': 'The last sentence has no ending punctuation. Finish it.',
}


def faults(result, lang='zh'):
    tbl = FAULT_ZH if lang == 'zh' else FAULT_EN
    out, seen = [], set()
    for x in result.get('findings', []):
        c = x['code']
        if c in tbl and c not in seen:
            seen.add(c)
            out.append(tbl[c])
    return out
