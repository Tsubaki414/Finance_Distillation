"""Write one piece for one account from a live fact pack.

Each account writes on its own. The English macro account is not handed the Chinese macro
account's draft to translate — it gets the same fact pack and its own question, and reasons from
there. That is the rule the product was specified on, and it is also the only way the two
accounts are worth following separately.

The slot discipline from the curated pipeline carries over unchanged: figures arrive pre-rendered
from live/render_slots.py, and every number in the finished text must match one of them exactly.
What is new is that a generic pack has no mandatory-fact list, so coverage is not enforced —
selection is the writer's job here, and the gates check what was written rather than what was
required.

Run: .venv/bin/python -B live/write.py --account=zh_industry --packet=<id>
"""
from pathlib import Path
import sys, json, re, datetime, hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'evidence_loop'))
sys.path.insert(0, str(ROOT / 'live'))
from model_client import parse_json
from qa.gates import evaluate, layer3_entailment
from qa.status import classify
from content.generate_slotted import local_call
from ml.writer_api import writer as pick_writer
from evergreen.output_gate import assert_exportable
from content.leak_check import check as leak_check, faults as leak_faults
from content.tells import check as tell_check, faults as tell_faults
from content.originality import check as orig_check, faults as orig_faults
# The reader's own list of what is wrong with the output, which outranks every measure invented
# here: a human caught 100% of these drafts twice, then wrote down why. See content/reader_spec.py.
# Regex and model, unioned. Measured on 22 drafts: the model caught 13 the regex missed
# (including 「当成数据层…政策层」, which the reader called out by hand) and the regex caught 2
# the model missed. Neither subsumes the other; see content/reader_spec_llm.check.
from content.reader_spec_llm import check as reader_check, faults as reader_faults
import render_slots
import style as style_mod

STORE = ROOT / 'live/store'
OUT = STORE / 'drafts'
TOKENS = 2400
# Four was enough when the gates were looser. With the sentence-length floor in place, three of
# four pieces still carried the tell on their last allowed attempt, and the one that cleared it
# did so on attempt 4 — the loop was being cut off mid-improvement rather than converging. The
# temperature schedule below rises with the attempt, so later attempts are also the varied ones.
MAX_ATTEMPTS = 7

# A draft's primary document must be the issuer, a wire, or a regulator — 2.0 and above in
# live/resolve_event.py's ranking. See the check in build() for why.
PRIMARY_SOURCE_FLOOR = 2.0

# A digit glued to a letter is part of a token, not a figure: 3D NAND, 5G, HBM3. Without the
# guard the "3" in "3D NAND" was reported as a number the writer invented.
NUM_TOKEN = re.compile(r'[-+]?[$€¥£]?\d[\d,]*(?:\.\d+)?\s*'
                       r'(?:万亿|亿|万|个百分点|个基点|%|percent|percentage points?|'
                       r'basis points|trillion|billion|million|bn|mn|tn|[KMBT])?'
                       r'\s*(?:韩元|美元|日元|欧元|元|人|股|台|片|吨|won|dollars?|yen|euros?)?'
                       r'(?![A-Za-z0-9])',
                       re.I)
DURATION = re.compile(r'\d+\s*(?:个月|个季度|天|周|年|季度|months?|quarters?|weeks?|days?|years?)')
CALENDAR = re.compile(r'(?:20\d{2}\s*年)?\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|\bQ[1-4]\b|\b20\d{2}\b')
# Two different jobs, and conflating them meant "需警惕 AI 需求放缓 … 否则不可持续" — a perfectly
# good invalidation condition — was reported as having none.
#   THRESHOLD_SCOPE  narrow: inside this clause a figure is a proposal, not a claim
#   HAS_CONDITION    broad: did the writer say what would make them wrong at all
THRESHOLD_SCOPE = re.compile(r'(?:若|如果|一旦|除非|失效条件|更新条件|\bif\b|\bunless\b|'
                             r'\bshould\b|invalidat\w+)(?:[^。！？.!?]|\.(?=\d))*', re.I)
HAS_CONDITION = re.compile(r'若|如果|一旦|除非|否则|失效|需警惕|需要看到|才能确认|前提是|'
                           r'\bif\b|\bunless\b|\bshould\b|invalidat\w+|would be wrong|'
                           r'watch for|no longer holds', re.I)
CONDITIONAL = THRESHOLD_SCOPE


UNIT_CLASS = [
    ('percentage_points', r'个百分点|percentage points?'),
    ('percent', r'%|percent'),
    ('basis_points', r'个基点|bps|basis points'),
    ('KRW', r'韩元|won'), ('JPY', r'日元|yen'), ('EUR', r'欧元|euros?'),
    ('CNY', r'人民币|元(?!\s*美)|yuan'), ('USD', r'美元|dollars?|\$'),
    ('EUR', r'€'), ('JPY', r'¥'), ('GBP', r'£'),
    ('hours', r'小时|hours?'), ('persons', r'人(?!民)|persons?'),
]
_UNIT_CLASS = [(k, re.compile(p, re.I)) for k, p in UNIT_CLASS]
SCALE_WORD = {'万亿': 1e12, '亿': 1e8, '万': 1e4,
              'trillion': 1e12, 'billion': 1e9, 'million': 1e6}
_SCALE_RE = re.compile('|'.join(SCALE_WORD), re.I)
# "$96.2B" is the same figure as "96.2 billion dollars"; the renderer now writes the first because
# that is what the donors write. A suffix only counts when it sits directly on the digits, so the
# "B" in a ticker or the "M" in a model name cannot be read as a scale.
SYMBOL_SCALE = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3,
                'b': 1e9, 'm': 1e6, 'k': 1e3,
                'tn': 1e12, 'bn': 1e9, 'mn': 1e6}
_SYMBOL_SCALE_RE = re.compile(
    r'(?<=[\d.])\s?(tn|bn|mn|[TBMK]|[bmk])(?![A-Za-z0-9])')
_NUMBER = re.compile(r'[-+]?[$€¥£]?\d[\d,]*(?:\.\d+)?')


def _unit_of(token):
    for name, pat in _UNIT_CLASS:
        if pat.search(token):
            return name
    return None


def parse_amount(token):
    """(value, unit class) for a written figure, or None.

    String matching rejected "75.0%" against a slot rendered "75 percent" and "$2.46" against
    "2.46 dollars". Those are the same number in another notation, not a restatement, and the
    guarantee this audit exists for is about the *number*: comparing value and unit keeps a wrong
    figure just as invalid while letting the writer use ordinary punctuation.
    """
    m = _NUMBER.search(token or '')
    if not m:
        return None
    try:
        v = float(re.sub(r'[,$€¥£]', '', m.group(0)))
    except ValueError:
        return None
    s = _SCALE_RE.search(token)
    if s:
        v *= SCALE_WORD[s.group(0).lower() if s.group(0).isascii() else s.group(0)]
    else:
        sym = _SYMBOL_SCALE_RE.search(token)
        if sym:
            v *= SYMBOL_SCALE[sym.group(1)]
    unit = _unit_of(token)
    if unit is None:
        head = (token or '').strip()[:1]
        unit = {'$': 'USD', '€': 'EUR', '¥': 'JPY', '£': 'GBP'}.get(head)
    return (round(v, 6), unit)


def audit(text, slots, is_condition_ok=True):
    """Every figure must be one of the rendered slot values, by value and unit.

    A range is matched whole before anything else: the text "1.1 percent to 2.5 percent" is the
    slot, and tokenising it into two figures rejected a correctly written range — the very defect
    the paired extraction was added to prevent.
    """
    body = text or ''
    scoped = CONDITIONAL.sub('', body) if is_condition_ok else body
    ranges = [s for s in slots if ' to ' in s['value_rendered'] or ' 至 ' in s['value_rendered']]

    def scan(s):
        stripped = CALENDAR.sub('', DURATION.sub('', s))
        used, other = [], []
        # Whole ranges first, then blank them so their bounds are not scanned again.
        for slot in ranges:
            v = slot['value_rendered']
            if v in stripped:
                used.append(slot['slot_id'])
                stripped = stripped.replace(v, ' ')
        want = [(slot, parse_amount(slot['value_rendered'])) for slot in slots
                if slot not in ranges]
        for m in NUM_TOKEN.finditer(stripped):
            tok = m.group(0).strip()
            if not re.search(r'\d', tok):
                continue
            got = parse_amount(tok)
            if got is None:
                other.append(tok)
                continue
            hit = next((slot for slot, w in want
                        if w and w[0] == got[0] and (w[1] == got[1] or got[1] is None)), None)
            if hit:
                used.append(hit['slot_id'])
            else:
                other.append(tok)
        return used, other

    used, invented = scan(body)
    _, outside = scan(scoped)
    proposed = [x for x in invented if x not in outside]
    return sorted(set(used)), outside, proposed


SLOT_ID_LEAK = re.compile(r'\b[LES]\d{2}\b')


SHAPE = {
    'zh': {
        # The old scaffold dictated a sentence for each move, and produced uniform long
        # sentences opening with 核心判断 — the two features that separated it from every human
        # post. The obligations stay, the shape is the writer's.
        #
        # The sentence-length instruction that used to sit here — 「把其中两三句改短」 — is gone,
        # and it is worth saying why rather than just deleting it. It was written to satisfy a
        # coefficient-of-variation gate, and the cheapest way to satisfy that gate is to drop a
        # four-character sentence between two long ones. Sixteen drafts written under it contain
        # 29 of them: 费用在抬头。需求还在。 The reader read the output, listed 刻意的短句 among
        # the things that give it away, and asked for the opposite: 「允许多写几句解释，不要把
        # 解释压缩成术语、口号或刻意的短句」. What replaces it is that instruction, close to
        # verbatim, because it came from the person the writing has to survive.
        # The obligations are described, never named. An earlier version listed them as
        # 「你的判断、支撑它的数字、最强的相反读法、以及什么情况会证明你错」 and two of three
        # drafts opened a paragraph with 「最强的相反读法是」 — the model took the prompt's noun
        # phrase and used it as a section heading, which is the same failure as the example
        # sentence it used to paste. A checklist of four named parts also produces four parts in
        # that order, every time, which is 机械周全 with different labels on it.
        'ask': ('写一段中文分析，6 到 10 句。\n'
                '文章里要有：你认为会发生什么；让你这么认为的那几个数字；一个认真的人'
                '看着同样的数字可能得出的不同结论，以及你为什么没被它说服；还有什么情况'
                '会让你承认自己错了。\n'
                '**这四件事不要分成四段、也不要按这个顺序写。** 它们应该混在论证里，'
                '像你边想边写那样。不要用上面这几句话里的词当小标题。\n'
                '**不要写「这个数字表明／显示出／反映出……」。** 这些作者自己 97.7% 的帖子里'
                '一次都没有这种说法。直接写你据此预期什么会发生、或你因此改变了什么判断。\n'
                '**把推理写出来。** 一句判断，要让人看清它是怎么从前面那个事实推出来的——'
                '中间那一步不要省。允许为此多写几句，句子长一点没关系。\n'
                '**不要把解释压缩成术语、口号或刻意的短句。**「费用在抬头。」「需求还在。」'
                '这种四五个字的断言是压缩掉的解释，不是风格。'
                '写成「费用抬头是因为……，所以我认为……」这样能顺着读下来的句子。\n'
                '读者应该能顺着读懂，无须反复翻译你的措辞。\n'
                '以下几种写法一律不要：\n'
                '  · 预告自己要说重点：「真正值得关注的是」「很多人不知道的是」——直接说那件事。\n'
                '  · 模板式转折：「不是……而是……」「问题不在于……而在于……」——两边分开说清楚。\n'
                '  · 假装有分量的结尾：「这值得深思」「时间会给出答案」——结尾写判断或失效条件。\n'
                '  · 把普通意思抽象化：「价值重构」「深度协同」「底层逻辑」——用普通说法。\n'
                '  · 机械周全：每段都写优点、风险、建议再补一句总结——只写你真正要说的那条。\n'
                '  · 数字排得很密、关系交代得很少——数字之间怎么连起来的，比数字本身重要。\n'
                'kind 字段：引用了表内数字的句子写 fact，判断与推论写 interpretation，'
                '讲失效条件的写 condition。\n'
                '**只挑 3 到 4 个最能支撑判断的数字，不要把表里的数字都用上**；'
                '一句话最多用两个数字。\n'
                '**大约一半的句子里不要出现任何数字**——那些句子用来说明数字之间的关系、'
                '为什么重要、以及你据此认为会发生什么。真人写的分析大约只有四成句子带数字，'
                '其余是推进论证的话。'),
        'rules': ('**数值、单位、量级必须与下表一致**：不要换算、不要四舍五入、不要改变量级。'
                  '这一条由审计逐个核对，写错会被直接打回。\n'
                  '**但句子怎么写是你的事。** 数字要嵌进你的句子，'
                  '不要每句都用「指标名 数字，」开头——真人从不这么写，'
                  '而这恰恰是读者一眼认出机器稿的地方。'
                  '「毛利率还稳在 75%」「75% 的毛利率还撑着」「把定价权放在供给一侧，'
                  '是因为毛利率仍有 75%」都可以，前提是数值和单位没动。\n'
                  '事实包里没有市场预期或共识预测，不得写「超预期」「预期差」「与预期背离」。'
                  '只有失效条件里可以出现表外的阈值。'),
        'json': '{"title":"...","sentences":[{"text":"...","kind":"fact 或 interpretation 或 condition","slot_ids":[]}]}',
    },
    'en': {
        # The Chinese branch stopped dictating a sentence per move some time ago, for a reason
        # recorded there: a scaffold that assigns one job to each sentence produces sentences of
        # one length. The English branch kept the scaffold — "1 states your call; 2-5 support it
        # with figures" — and it shows in both measurements that matter. English figure density
        # runs 78-89% against a donor median of 33%, because the prompt asks for four consecutive
        # figure sentences; and its sentence-length variation sits below the donors' 10th
        # percentile, because every sentence has the same job to do. The obligations below are
        # the same as before. The shape is the writer's.
        'ask': ('Write a short English piece, 7 to 9 sentences. It must contain: your call, the '
                'figures that support it, the strongest reading against you, and what would make '
                'you wrong. The order is yours.\n'
                'kind: a sentence quoting a figure from the table is a fact; a judgement or '
                'inference is interpretation; the one stating what would falsify you is '
                'condition.\n'
                '**Use only the 3 or 4 figures that carry your argument — not the whole table**; '
                'at most two figures in any one sentence.\n'
                '**About half your sentences should contain no figure at all.** Those are the '
                'ones that say how the figures relate, why they matter, and what you expect '
                'because of them. Real analysis by these authors carries a figure in roughly a '
                'third of its sentences; the rest is the argument.\n'
                '**Take a position in the first person.** These authors put themselves in the '
                'text — roughly one sentence in ten says what they think, expect or would do. '
                'Say "I read this as", "my worry is", "I would want to see", not only what the '
                'data "suggests".\n'
                '**Do not write that a figure "highlights" or "is a key factor".** 99.5% of these '
                'authors\' posts contain no such phrase. Write what you expect to follow from it.\n'
                '**Vary sentence length sharply.** In real writing the longest sentence is often '
                'three or four times the shortest, and some run to only a few words. Those short '
                'sentences have to be your own and specific to this argument, not a stock line. '
                'Read it back: if every sentence is about the same length, cut two or three of '
                'them short — by deleting the run-up, not by padding the others.'),
        'rules': ('**The value, the unit and the scale must match the table.** Do not convert, '
                  'round, or change the magnitude. An audit checks each figure and a wrong one '
                  'is rejected outright.\n'
                  '**How the sentence is built is yours.** Work the figure into your prose. Do '
                  'not open sentence after sentence with a metric name followed by its number — '
                  'no real writer does that, and it is the single thing that gives a machine '
                  'draft away. "Gross margin is still holding at 75%", "a 75% gross margin '
                  'still covers it", "pricing power sits upstream while margin holds 75%" are '
                  'all fine, as long as the value and unit are untouched.\n'
                  'The pack contains no consensus forecasts, so never compare against '
                  'expectations. A threshold in the invalidation sentence is the only figure '
                  'allowed outside the table.'),
        'json': '{"title":"...","sentences":[{"text":"...","kind":"fact|interpretation|condition","slot_ids":[]}]}',
    },
}


MASK_NUM = re.compile(r'[-+]?\$?\d[\d,]*(?:\.\d+)?')


CLAUSE_SPLIT = re.compile(r'(?<=[,;，；、])\s+|(?<=[，；、])|\s+—\s+|\s+--\s+')


def _on_table(m, text, keep):
    tok = m.group(0).replace(' ', '')
    tail = text[m.end():m.end() + 12].replace(' ', '')
    return any(k.startswith(tok) and (k == tok or tail.startswith(k[len(tok):])) for k in keep)


def mask_context(sentence, slots, lang, unit='clause'):
    """Keep off-table figures out of the prompt by removing the text that carries them.

    Three prompt fields leaked off-table figures in turn — the plausibility warning, the source
    context sentences, the slot labels — so every fact-bearing string now goes through here and no
    field can leak by being added later.

    What changed is the removal itself. This used to substitute a marker in place of the digits,
    which failed twice for the same underlying reason: a hole inside a sentence is an invitation
    to fill it. The bracketed `[figure withheld]` came back glued into a quotation as
    "$5[figure withheld] bil."; replacing it with the plainer "a figure" only made the leak read
    naturally — "touching a figure per dollar", "as suggested by Chart a figure" — and, because
    content/leak_check.py was still looking for the bracketed form, silently undetectable. That
    was a worse failure than the one it fixed.

    So nothing is substituted. The clause holding an off-table figure is dropped, and a context
    sentence is dropped whole, because a fragment with a gap is what the writer patches over. A
    prompt that says less is recoverable; a prompt that hands the writer a blank to fill is not.
    """
    text = sentence or ''
    if not text.strip():
        return ''
    # A collection slot has no source quote — its figure is counted from our own records rather
    # than lifted from a document — so the set is built from whatever each slot actually carries.
    keep = {(s.get('source_quote') or '').replace(' ', '') for s in slots}
    keep |= {(s.get('value_rendered') or '').replace(' ', '') for s in slots}
    keep.discard('')

    if unit == 'sentence':
        return '' if any(not _on_table(m, text, keep)
                         for m in MASK_NUM.finditer(text)) else text

    out = []
    for clause in CLAUSE_SPLIT.split(text):
        if clause is None or not clause.strip():
            continue
        if any(not _on_table(m, clause, keep) for m in MASK_NUM.finditer(clause)):
            continue
        out.append(clause.strip())
    return ' '.join(out).strip()


# The five generation modes the evaluation contract asks to be compared on identical evidence
# and budget: 「no persona; text description; profile; profile plus retrieved exemplar;
# separated multi-donor profile」. Only what reaches the prompt differs — same fact pack, same
# rendered slots, same attempt budget, same writer model, same gates.
MODES = ('none', 'description', 'profile', 'profile_exemplars', 'multi_donor')


def prompt_for(account, persona, opp, packet, slots, faults=None, style_target=None,
               style_examples=None, cross=None, mode='profile_exemplars', opinions=None):
    lang = account['lang']
    sh = SHAPE[lang]
    voice = ''
    if mode == 'none':
        style_target, style_examples = {}, []
    elif mode == 'description':
        style_target, style_examples = {}, []
    elif mode == 'profile':
        style_examples = []
    # Voice comes from the posts, not from a description of the posts.
    #
    # Published comparisons of style imitation put few-shot at up to 23.5x the style-matching of
    # zero-shot, with abstract style descriptions scoring under 7% — and continuation framing,
    # where the model carries on after real text rather than being told to write "in the style
    # of", reaching 99.9% agreement with the original author. Five excerpts is where the gain
    # stops; more stops carrying signal.
    #
    # This project had it backwards. Style was enforced through numeric bands — a description —
    # while the real posts came wrapped in 「只学表达方式与节奏，不要抄内容」, an instruction that
    # argues with the example it is attached to. The five-mode ablation already showed what that
    # was worth: a piece written with no persona at all passed the donor's own style bands, which
    # is the same finding from the other direction. The bands stay as a diagnostic and stop being
    # the mechanism.
    #
    # Copying is still forbidden and is still checked — by content/originality.py, against the
    # donors' own overlap baseline, after the text exists. Verified, not prevented.
    if style_examples:
        head = ('\n下面是这位作者最近写的几段，按他平时的写法接着写下一段。\n'
                '不要解释你在模仿谁，也不要复述这些内容——它们是给你定调子的，不是素材。\n'
                if lang == 'zh' else
                '\nA few things this author wrote recently. Carry on in the same register.\n'
                'Do not explain whose voice this is and do not restate their content — these set '
                'the tone, they are not material.\n')
        voice = head + '\n'.join('  ———\n  ' + e[:700].replace('\n', ' ')
                                  for e in style_examples[:5]) + '\n  ———\n'
    if style_target and style_target.get('usable') and mode in ('profile', 'multi_donor'):
        # Kept only for the ablation arms that exist to measure a description against examples.
        voice += '\n' + style_mod.instructions(style_target, lang) + '\n'
    m = lambda s: mask_context(s, slots, lang)
    # `place_verbatim` asked the writer to drop a finished phrase into the sentence whole. That
    # was necessary when the audit compared strings: any rewording read as an invented figure. The
    # audit now compares value and unit — "毛利率还稳在 75%" and "75% 的毛利率" both verify, and a
    # wrong number or unit still fails — so the guarantee no longer needs the placement rule.
    #
    # The rule outlived its reason and nobody noticed, and it is what shaped every figure-bearing
    # sentence this system writes: 毛利率 75%，… / 运营支出 92 亿美元，… / 稀释每股收益 2.46美元，…
    # eight out of eight, while the donors never write that way once. A human reviewer rated the
    # result 0.17 out of 5 for naturalness and marked every piece 重写.
    #
    # So the table now offers the figure and what it measures, and leaves the sentence to the
    # writer. The digits are still not the writer's to touch.
    def row(s):
        subj = s.get('translate_subject') or s.get('label_en') or ''
        if subj:
            return f"  · {s['value_rendered']}   ← {subj}"
        return f"  · {s['value_rendered']}"
    table = '\n'.join(row(s) for s in slots)
    # A context sentence is supplementary, so it is dropped whole rather than pruned: the slot row
    # already states what its figure is, and a sentence with a clause cut out of it reads as a gap.
    ctx_lines = [mask_context(s['context_sentence'][:180], slots, lang, unit='sentence')
                 for s in slots[:5]]
    ctx = '\n'.join(f'  · {c}' for c in ctx_lines if c.strip())
    fix = ''
    if faults:
        head = '\n这一稿要修正的问题：\n' if lang == 'zh' else '\nFix from the last attempt:\n'
        fix = head + '\n'.join('  - ' + x for x in faults) + '\n'
    if mode == 'multi_donor':
        # The separated roles as recorded in roles_v2.json: which donor carries which axis, the
        # metric that put them there, its value and sample size. A role with no evidence stays
        # unassigned and is shown as such rather than filled in with the nearest candidate.
        rows = []
        for axis, r in (persona.get('roles') or {}).items():
            if not isinstance(r, dict) or not r.get('donor'):
                rows.append(f"  · {axis}：未指派（没有足够证据）")
                continue
            rows.append(f"  · {axis}：@{r['donor']}（依据 {r.get('metric')}={round(r.get('value') or 0, 3)}，"
                        f"样本 {r.get('sample_n')}，领先次席 {r.get('margin_over_next')}）")
        voice = ('\n这个人设由多位作者分角色组成，各轴取值与样本量如下；'
                 '你要按各自的角色分别参考，不要把某一位当成整体模板：\n'
                 + '\n'.join(rows) + '\n') + voice

    # `none` means no persona at all, not a persona with its style stripped. The first version
    # cleared the bands and kept the identity line, so `none` and `description` produced byte
    # -identical prompts — two arms of a five-arm comparison that were the same experiment run
    # twice. The contract's first mode is a bare writer given the same evidence.
    if mode == 'none':
        who = ('写一段中文分析。\n' if lang == 'zh' else 'Write a short English analysis.\n')
    else:
        who = (f"你是{persona['name']}，关心的问题是：{persona['question']}\n"
               f"读者：{account['audience']}\n" if lang == 'zh' else
               f"You are {persona['name']}. Your question: {persona['question']}\n"
               f"Audience: {account['audience']}\n")
    lead = (f"事件线索：关注的作者在讨论 {opp['entity']}。{m(opp['why'])}\n"
            f"原始文件：{m(packet['title'])}（{packet['primary_url']}）\n"
            if lang == 'zh' else
            f"Signal: the authors you follow are discussing {opp['entity']}.\n"
            f"Primary document: {m(packet['title'])} ({packet['primary_url']})\n")
    # The warning used to interpolate f0['detail'], which carries the raw unrendered figures.
    # The prompt then told the model every number had to match the slot table, having just
    # handed it two that do not. It copied them, and the audit caught it — correctly, but the
    # fault was here.
    flags = ''
    if packet.get('plausibility_flags'):
        kinds = sorted({f['kind'] for f in packet['plausibility_flags']})
        flags = ('\n⚠ 原始文件内部存在矛盾（' + '、'.join(kinds) + '）。'
                 '涉及的数字未列入下表，不得在正文中引用或据以推论。\n'
                 if lang == 'zh' else
                 '\nWarning: the source contradicts itself (' + ', '.join(kinds) + '). '
                 'The figures involved are not in the table below and must not be cited or '
                 'reasoned from.\n')
    lane_block = ''
    if cross:
        def excerpts(side, n=4):
            return '\n'.join(
                f"  · @{x['handle']}（{x['at'][:10]}）：{x['text'][:220]}"
                for x in (cross[side]['exemplars'] or [])[-n:])
        if lang == 'zh':
            lane_block = (
                '\n【跨语言信息差】这一篇写的是两个语言社区在同一件事上说了什么、'
                '在哪里分歧、谁更早提出。\n'
                '硬规则：\n'
                '  1. 关于「多少位作者」「多少帖」「领先多少小时」的数字，只能用下表里 C 开头的那几行，'
                '并且必须写明这是**我们观察名单内**的计数，不是整个中文或英文市场的计数。\n'
                '  2. 下面的原帖摘录是给你读的材料，**一句都不要搬**。'
                '中文摘录尤其不能改写——同语言搬运一律禁止。英文那侧你可以据其内容推理，'
                '但必须用你自己的中文写，并注明是英文社区的说法。\n'
                '  3. 词表差异要自己判断：一个词和它的译文会同时出现在两个单侧列表里（加息 / hike 就是同一个意思），'
                '真正值得写的是另一侧**完全没有对应物**的那些。\n'
                f"\n两侧只出现在单侧的高频词——仅中文：{cross['only_zh_vocabulary'][:8]}；"
                f"仅英文：{cross['only_en_vocabulary'][:8]}\n"
                f"\n中文侧原帖摘录（不得搬用措辞）：\n{excerpts('zh')}\n"
                f"\n英文侧原帖摘录（可据内容推理，须用中文自己写）：\n{excerpts('en')}\n")
        else:
            lane_block = (
                '\n[Cross-language information gap] This piece is about what the two language '
                'communities said about the same event, where they diverge, and who was earlier.\n'
                'Hard rules:\n'
                '  1. Any figure for author counts, post counts or hours of lead must come from '
                'the C-prefixed rows below, and must be written as a count of **this watchlist**, '
                'not of the Chinese- or English-speaking market.\n'
                '  2. The excerpts are material to read, not text to reuse. Do not lift a phrase '
                'from the English ones — same-language carrying is forbidden. You may reason from '
                'the Chinese ones and write the result in your own English, attributed.\n'
                '  3. Judge the vocabulary difference yourself: a word and its translation both '
                'appear one-sided. What is worth writing is a term with no counterpart at all.\n'
                f"\nOne-sided terms — zh only: {cross['only_zh_vocabulary'][:8]}; "
                f"en only: {cross['only_en_vocabulary'][:8]}\n"
                f"\nChinese-side excerpts (reason from, write your own English):\n{excerpts('zh')}\n"
                f"\nEnglish-side excerpts (do NOT reuse wording):\n{excerpts('en')}\n")

    # What the followed accounts are saying, on every lane rather than only the cross-language
    # one. Until 2026-09-24 this block existed solely inside `if cross:` above, so a hot-signal
    # piece — the lane whose whole purpose is reacting to what people are posting — was written
    # from a table of numbers with no opinion in front of it. See live/opinions.py.
    opinion_block = ''
    if opinions:
        import opinions as _op
        opinion_block = _op.prompt_block(opinions, lang)

    return (f"{who}{lead}{flags}{voice}{opinion_block}{lane_block}\n{sh['ask']}\n\n{sh['rules']}\n\n"
            f"可用数字（由系统从原始文件渲染，逐字使用）：\n{table}\n\n"
            f"原文相关句子：\n{ctx}\n{fix}\n"
            f"只输出 JSON：{sh['json']}")


FAULT = {
    'zh': {
        'model_wrote_a_number': '上一稿出现了表外数字。除失效条件里的阈值外，必须与表内一字不差。',
        'no_condition': '上一稿没有写失效条件。',
        'out_of_evidence_assertion': '上一稿出现了与「预期」的比较（如「不及预期」）。事实包里没有'
                                     '任何预期或共识数据，改写成具体的可观察条件，例如'
                                     '「产能扩张进度低于公司此前披露的计划」。',
        'too_short': '上一稿句数不足。',
        'no_figures': '上一稿没有用到任何表内数字。',
        'slot_id_leaked': '上一稿把系统的编号（L01 这类）写进了正文。表里的编号只是给你看的，'
                          '不要出现在文字里。',
        'unsupported_relation': '上一稿断言了事实包不支持的关系（因果、加速、纪录、证明）。',
        'unsupported_claim': '上一稿有句子标成了 fact 却没有引用任何表内数字。判断句的 kind 要写 '
                            'interpretation，只有引用了数字的句子才是 fact。',
        'unattributed_source_record': '上一稿直接断言「创纪录/历史新高」。这是原始文件自己的说法，'
                                      '要写成「新闻稿称…」这样注明出处，不要当成自己的结论。',
        'one_figure_two_metrics': '上一稿把同一个数字安在了两个不同指标上（例如营收和利润都写成'
                                  '同一个增长率），前后自相矛盾。每个数字只对应它自己的指标。',
        'figure_attached_to_wrong_metric': '上一稿把某个数字安给了错误的指标（例如把营业利润写成'
                                           '营收）。表里每行右侧标注了该数字是什么，按它来写。'
                                           '标注 growth 的是增长率，不是水平值。',
        'repeated_sentence': '上一稿有整句重复。宁可少写一句，也不要重复。',
        'contradicted_comparison': '上一稿的比较写反了：两个数字的实际大小，和你用的比较词'
                                   '（「高于」「放缓」这类）相反。按数字实际大小改写。',
        'comparison_without_baseline': '上一稿用了「超过／低于／放缓」这类比较，却没写出被比较的'
                                       '那个数。把基准数字写进同一句，或者不要下这个比较。',
        'record_relayed_from_source': '',
    },
    'en': {
        'model_wrote_a_number': 'A figure appeared that is not in the table.',
        'no_condition': 'No invalidation condition was stated.',
        'out_of_evidence_assertion': 'A comparison against market expectations was made; the '
                                     'pack contains no consensus data.',
        'too_short': 'Too few sentences.',
        'no_figures': 'No figure from the table was used.',
        'slot_id_leaked': 'A system label (L01 and the like) was copied into the text. Those are '
                          'for reading the table, not for the piece.',
        'contradicted_comparison': 'The comparison runs the wrong way: the two figures are '
                                   'ordered the opposite of what the comparative word claims. '
                                   'Rewrite it to match the figures.',
        'comparison_without_baseline': 'A comparative claim ("outpaced", "below", "slowed") was '
                                       'made without stating the figure being compared against. '
                                       'Put both numbers in the sentence, or drop the comparison.',
        'prompt_furniture_in_output': 'The piece refers to the table or to a chart. The reader '
                                      'has neither; state the figure instead.',
        'unsupported_relation': 'A relation the pack does not support was asserted (causation, '
                                'acceleration, a record, or proof).',
        'unsupported_claim': 'A sentence was labelled fact but cites no figure from the table. '
                             'A judgement is an interpretation; only a sentence quoting a table '
                             'figure is a fact.',
        'unattributed_source_record': 'A record was asserted directly. That is the source\'s own '
                                      'claim — write "the release calls it ..." rather than '
                                      'adopting it.',
        'one_figure_two_metrics': 'The same figure was attached to two different metrics, so the '
                                  'piece contradicts itself. Each figure belongs to one metric.',
        'figure_attached_to_wrong_metric': 'A figure was given to the wrong metric (for example '
                                           'operating profit written as revenue). Each row of the '
                                           'table names what its figure is; a row marked growth '
                                           'is a rate of change, not a level.',
        'repeated_sentence': 'A sentence was repeated. Write one fewer sentence instead.',
        'record_relayed_from_source': '',
    },
}


METRIC = re.compile(r'营收|收入|销售额|营业利润|运营利润|经营利润|净利|毛利|利润率|现金|'
                    r'产能|出货|占比|库存|资本开支|'
                    r'revenue|sales|operating profit|net profit|margin|cash|capacity|'
                    r'shipments?|inventory|capex', re.I)


# Order and boundaries both matter: 「营业利润率」 contains 「营业利润」, so checking
# operating_profit first classified an operating *margin* as operating profit and the gate
# reported a mismatch against its own slot. Margin is tested first, and the profit patterns
# refuse a trailing 率.
METRIC_CANON = [
    ('margin', r'利润率|毛利率|净利率|margin'),
    ('net_profit', r'净利(?:润)?(?!率)|net (?:profit|income)'),
    ('operating_profit', r'(?:营业|经营|运营)利润(?!率)|operating (?:profit|income)(?!\s*margin)'),
    ('revenue', r'营收|收入|销售额|revenues?|sales|turnover'),
    ('cash', r'现金|cash'),
    ('capacity', r'产能|capacity'),
    ('share', r'占比|份额|share|ratio'),
]
_CANON = [(k, re.compile(p, re.I)) for k, p in METRIC_CANON]


def canon_metric(text):
    for k, p in _CANON:
        if p.search(text or ''):
            return k
    return None


def wrong_metric(rows, slots):
    """A figure given to a metric the source does not give it to.

    Every number can be on the table and the piece still be wrong: one passing draft wrote
    "revenue ... 60.54 trillion won" (the operating profit) and "operating profit 88 trillion won"
    (the cash balance). The audit only checked that a figure existed in the table, never what it
    was a figure *of*.
    """
    by_slot = {s['slot_id']: s for s in slots}
    bad = []
    for r in rows:
        for sid in r['slot_ids']:
            slot = by_slot.get(sid)
            if not slot:
                continue
            src = canon_metric(slot.get('subject') or slot.get('label_en') or '')
            if not src:
                continue
            v = slot['value_rendered']
            i = r['text'].find(v.split()[0]) if v else -1
            near = r['text'][max(0, i - 26):i] if i > 0 else ''
            drafted = canon_metric(near)
            if drafted and drafted != src:
                bad.append({'slot_id': sid, 'value': v, 'source_metric': src,
                            'written_as': drafted, 'sentence_id': r['sentence_id']})
    return bad


def value_subject_conflicts(rows, slots):
    """One figure attached to two different metrics inside the same piece.

    A passing draft said revenue grew 257% and operating profit "also grew 257%", then two
    sentences later gave the pair as 257% and 557%. Every number matched the table and every gate
    was green; the piece still contradicted itself.
    """
    by_slot = {s['slot_id']: s for s in slots}
    seen = {}
    conflicts = []
    for r in rows:
        for sid in r['slot_ids']:
            slot = by_slot.get(sid)
            if not slot:
                continue
            v = slot['value_rendered']
            i = r['text'].find(v.split()[0]) if v else -1
            near = r['text'][max(0, i - 24):i] if i > 0 else r['text'][:24]
            for m in METRIC.finditer(near):
                subj = m.group(0).lower()
                prev = seen.setdefault(v, set())
                if prev and subj not in prev:
                    conflicts.append({'value': v, 'subjects': sorted(prev | {subj}),
                                      'sentence_id': r['sentence_id']})
                prev.add(subj)
    return conflicts


def check(rows, slots, packet, lang):
    f = []
    # Over-constrained, the model began repeating one sentence to fill the shape.
    bodies = [re.sub(r'\s+', '', r['text']) for r in rows]
    if len(set(bodies)) < len(bodies):
        f.append('repeated_sentence')
    if len(rows) < 6:
        f.append('too_short')
    if not any(r['slot_ids'] for r in rows):
        f.append('no_figures')
    if not any(HAS_CONDITION.search(r['text']) for r in rows):
        f.append('no_condition')
    if any(r['model_written_numbers'] for r in rows):
        f.append('model_wrote_a_number')
    if any(SLOT_ID_LEAK.search(r['text']) for r in rows):
        f.append('slot_id_leaked')
    for r in rows:
        for x in layer3_entailment(r['text'], [], packet):
            if x['severity'] == 'blocking':
                f.append(x['code'])
    # A sentence claiming to state a fact has to point at one — a packet fact or, in the
    # cross-language lane, a figure counted from our own collection. Both are slots.
    if any(r.get('kind') == 'fact' and not r['slot_ids'] for r in rows):
        f.append('unsupported_claim')
    if value_subject_conflicts(rows, slots):
        f.append('one_figure_two_metrics')
    if wrong_metric(rows, slots):
        f.append('figure_attached_to_wrong_metric')
    seen, codes = set(), []
    for c in f:
        if c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def build(account, persona, opp, packet, style_targets=None, writer_model=None,
          use_opinions=True,
          lane=None, mode='profile_exemplars'):
    lang = account['lang']
    donor_cfg = account.get('language_donor') or {}
    donor = donor_cfg.get('handle')
    style_target = (style_targets or {}).get(donor) or {}
    style_examples = []
    if style_target.get('usable'):
        by = style_mod.corpus()
        topic = ' '.join(filter(None, [
            opp.get('entity', '').lstrip('$#').replace('_', ' '),
            packet.get('title', ''),
            (packet.get('facts') or [{}])[0].get('context_sentence', '')[:160]]))
        style_examples = style_mod.exemplars(by.get(donor, []), k=5,
                                             lang=style_target.get('lang'), topic=topic)
    # The primary document, read once: the originality gate compares the finished text against
    # it, and against the exemplars, on every attempt.
    _art = ROOT / (packet.get('artifact_path') or '')
    raw_source = _art.read_text() if _art.is_file() else (packet.get('full_narrative') or '')

    # Ten slots for seven sentences is an instruction to stuff. The drafts that failed were
    # packing every figure into every sentence; the one that read well used four.
    slots = render_slots.build(packet, lang=lang, limit=6)

    # Cross-language lane: what each language community said, as countable slots plus attributed
    # excerpts. The excerpts are material to reason over, never text to rewrite — and because the
    # originality gate compares only against same-language sources, a Chinese draft is checked
    # against the Chinese excerpts while the English ones are allowed to inform it. That is the
    # carrying rule CLAUDE.md now states, enforced rather than trusted.
    # Gathered for every lane. A failure here must not silently produce a figures-only draft that
    # looks identical to a good one, so it is recorded rather than swallowed.
    #
    # `use_opinions=False` is the control arm of the A/B, not a fallback. The eight machine items
    # in the third blind round were all written before opinions existed, so a 100% detection rate
    # was reported against a pipeline the reader had never seen the output of. Same packets, same
    # model, same attempt budget, opinions on or off — that is the only way the result attaches
    # to this change rather than to everything that happened today.
    import opinions as op_mod
    if not use_opinions:
        opinions = {'zh': [], 'en': [], 'matched': 0,
                    'withheld': 'control arm: opinions deliberately not shown'}
    else:
        try:
            opinions = op_mod.gather(opp['entity'], packet=packet)
        except Exception as e:
            opinions = {'error': type(e).__name__ + ': ' + str(e)[:160], 'zh': [], 'en': []}

    cross = None
    crosslang_evidence = []
    if lane == 'cross_language_gap':
        import crosslang as cl
        cf = (STORE / 'crosslang' /
              (re.sub(r'[^A-Za-z0-9_]', '_', opp['entity']) + '.json'))
        if not cf.is_file():
            return {'ok': False, 'account': account['id'], 'entity': opp['entity'],
                    'reason': (f'no cross-language evidence for {opp["entity"]}. Run: '
                               f"python -B live/crosslang.py --entity='{opp['entity']}'")}
        cross = json.loads(cf.read_text())
        if not (cross['zh']['posts'] and cross['en']['posts']):
            return {'ok': False, 'account': account['id'], 'entity': opp['entity'],
                    'reason': ('one-sided coverage: this lane compares two communities and only '
                               f"{'zh' if cross['zh']['posts'] else 'en'} has posts in the window")}
        # Split rather than appended. Everything as_slots() returns is our own collection
        # bookkeeping and is marked unpublishable at the source; see the docstring there for the
        # draft that made the distinction necessary. The evidence is kept on the record so a
        # reviewer can see the sample size; the writer never sees a number it could print.
        cross_slots = cl.as_slots(cross, lang=lang)
        crosslang_evidence = [s for s in cross_slots if s.get('publishable') is False]
        slots = slots + [s for s in cross_slots if s.get('publishable') is not False]

    # A pack that has not been through live/label_facts.py carries subjects cut out of the source
    # prose by regex, and on legal or flowing text those are verb fragments rather than metric
    # names: "three-year period issued more", "to date remains elevated", "share". The writer is
    # required to place them verbatim, so it writes "I go wrong if three-year period issued more
    # $1B" — and for a Chinese draft handed the English fragment "share" it guessed, producing
    # 「每股收益占比 2.46 美元」, a proportion label on a dollar amount.
    #
    # Every draft that read badly came from an unlabelled pack and every draft that read well came
    # from a labelled one. The labeller existed and simply was never called after resolve_event,
    # so the pipeline could silently produce garbage from a perfectly good source document.
    # CLAUDE.md: 「Yahoo 只能补充，不能替代 IR、SEC、电话会原文」. The ranking in
    # live/resolve_event.py already says who is speaking — 3.0 a regulator or central bank, 2.6 an
    # issuer's IR subdomain, 2.2 a wire, 2.0 a company's own site, 1.4 a newsroom, 0.3 nothing
    # recognised. Nothing enforced it, so one draft was written off invezz.com at 0.3: an
    # aggregator restating a 13F. It was the worst English piece produced and the judge called it
    # out. A newsroom may supplement a piece; it may not be the document a piece is built on.
    rank = float(packet.get('source_rank') or 0)
    if rank < PRIMARY_SOURCE_FLOOR:
        return {'ok': False, 'account': account['id'], 'entity': opp['entity'],
                'reason': (f'primary source ranks {rank} (floor {PRIMARY_SOURCE_FLOOR}): '
                           f'{str(packet.get("primary_url"))[:70]}. A newsroom or aggregator may '
                           f'supplement a piece but cannot be the document it is built on. '
                           f'Re-resolve this event for an issuer, wire or regulator document.')}

    unlabelled = [f['id'] for f in packet.get('facts', [])
                  if not f.get('subject_zh' if lang == 'zh' else 'subject_en')]
    if len(unlabelled) > len(packet.get('facts') or []) * 0.5:
        return {'ok': False, 'account': account['id'], 'entity': opp['entity'],
                'reason': (f"fact pack {packet.get('id')} has not been labelled "
                           f"({len(unlabelled)} of {len(packet.get('facts') or [])} facts have no "
                           f"{lang} subject). Run: python -B live/label_facts.py "
                           f"--packet={packet.get('id')}")}

    if len(slots) < 3:
        return {'ok': False, 'reason': 'fewer than three usable figures in the pack',
                'account': account['id'], 'entity': opp['entity']}

    did = 'w-' + hashlib.sha256(
        (account['id'] + packet['id'] + datetime.datetime.now().isoformat()).encode()).hexdigest()[:12]
    rec = {'id': did, 'account_id': account['id'], 'account_name': account['name'],
           'lang': lang, 'persona_id': account['persona_id'],
           'entity': opp['entity'], 'lane': opp['lane'],
           'packet_id': packet['id'], 'primary_url': packet['primary_url'],
           'source_rank': packet['source_rank'], 'artifact_sha256': packet['artifact_sha256'],
           'opportunity_score': opp['effective_score'],
           'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'slots': [{'slot_id': s['slot_id'], 'fact_id': s['fact_id'],
                      'value_rendered': s['value_rendered'],
                      'char_span': s['char_span']} for s in slots],
           'attempts': []}

    # The control arm goes through the same code as the treatment arms; only the model differs.
    write_one = pick_writer(writer_model)
    rec['writer_model'] = writer_model or 'local'
    rec['generation_mode'] = mode
    rec['lane'] = lane or rec.get('lane')
    best, best_score, faults = None, -1e9, []
    for attempt in range(MAX_ATTEMPTS):
        # A call that never returns is not a verdict on the draft. The local model is a process on
        # this machine and effectively always answers; a hosted one times out and runs out of
        # credit, and letting that propagate killed four comparison arms outright — they produced
        # no draft and no line of output, which read as though nothing had been attempted.
        try:
            r = write_one(prompt_for(account, persona, opp, packet, slots, faults,
                                     style_target, style_examples, cross, mode,
                                     opinions=opinions),
                          'live_write', TOKENS, temperature=.25 + .12 * attempt)
        except Exception as e:
            rec['attempts'].append({'attempt': attempt + 1, 'run_id': None,
                                    'call_failed': type(e).__name__ + ': ' + str(e)[:200]})
            continue
        rec['attempts'].append({'attempt': attempt + 1, 'run_id': r['run_id'],
                               'latency_s': r['_latency_s'], 'usage': r['usage']})
        try:
            o = parse_json(r['text'])
            rows = o['sentences']
            for i, row in enumerate(rows):
                txt = (row.get('text') or '').strip()
                used, invented, proposed = audit(txt, slots)
                row.update(sentence_id='s' + str(i + 1), text=txt, slot_ids=used,
                           model_written_numbers=invented, proposed_thresholds=proposed)
        except Exception as e:
            rec['attempts'][-1]['error'] = type(e).__name__ + ': ' + str(e)[:180]
            continue

        codes = check(rows, slots, packet, lang)
        body = '\n\n'.join(r_['text'] for r_ in rows)
        st = style_mod.check(body, style_target) if style_target.get('usable') else {'checked': False}
        lk = leak_check(body, rows)
        tl = tell_check(body, lang)
        # The exemplars shown to this writer are exactly what it can paste instead of learning
        # from; the source document is the other thing in front of it. Both are checked here.
        og = orig_check(body, lang, exemplars=style_examples, source_text=raw_source,
                        allowed_urls=[packet.get('primary_url')])
        rs = reader_check(body, lang)
        oc = op_mod.overclaim_check(body, lang)
        style_faults = style_mod.faults(st, lang) if st.get('checked') else []
        # The reader's findings carry the heaviest weight of any gate here. Everything else in
        # this sum is a statistic computed from a corpus; this one is the person who has to read
        # the result and who rejected every previous draft.
        score = (-3 * len(codes) - 2 * len(st.get('misses') or [])
                 - 4 * lk['blocking_count'] - 3 * tl['blocking_count']
                 - 6 * og['blocking_count'] - 8 * rs['blocking_count']
                 - 8 * oc['blocking_count']
                 + len(rows) + sum(len(r_['slot_ids']) for r_ in rows))
        rec['attempts'][-1].update(codes=codes, score=score,
                                   leaks=[x['code'] for x in lk['findings']],
                                   tells=[x['code'] for x in tl['findings']],
                                   figure_density=tl.get('figure_density'),
                                   copied=[x['code'] for x in og['findings']],
                                   longest_shared_run=og.get('longest_shared_run'),
                                   reader_faults=[x['code'] for x in rs['findings']],
                                   overclaims=oc['hits'],
                                   terse_share=rs.get('terse_share'),
                                   reasoning_density=rs.get('reasoning_density'),
                                   style_passed=st.get('passed'),
                                   style_misses=[m['feature'] for m in st.get('misses') or []])
        faults = ([FAULT[lang][c] for c in codes if FAULT[lang].get(c)] + style_faults
                  + leak_faults(lk, lang) + tell_faults(tl, lang) + orig_faults(og, lang)
                  + reader_faults(rs, lang) + op_mod.overclaim_faults(oc, lang))
        if score > best_score:
            best, best_score = (o, rows, codes, st, lk, tl, og, rs, oc), score
            rec['best_attempt'] = attempt + 1
        if (not codes and lk['status'] == 'passed' and tl['status'] == 'passed'
                and og['status'] == 'passed' and rs['status'] == 'passed'
                and oc['status'] == 'passed'
                and (not st.get('checked') or st.get('passed'))):
            break

    if best is None:
        failed_calls = [a for a in rec['attempts'] if a.get('call_failed')]
        rec.update(status='failed',
                   reason=('every model call failed: '
                           + failed_calls[-1]['call_failed'][:120]) if
                   len(failed_calls) == len(rec['attempts']) else 'no parsable draft')
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / (did + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        return {'ok': False, 'reason': 'no parsable draft', 'account': account['id'],
                'entity': opp['entity']}

    o, rows, codes, st, lk, tl, og, rs, oc = best
    by_slot = {s['slot_id']: s for s in slots}
    ledger = [{'sentence_id': r_['sentence_id'], 'text': r_['text'], 'kind': r_.get('kind'),
               'slot_ids': r_['slot_ids'],
               # A collection slot has no fact in the packet to cite — its figure is counted
               # from our own records, not extracted from the source document. Emitting a None
               # here made the citation layer report an unknown fact id and then fail sorting a
               # list of Nones. The slot ids are kept alongside so the count is still traceable,
               # to live/store/crosslang/ rather than to a character span.
               'fact_ids': [by_slot[s]['fact_id'] for s in r_['slot_ids']
                            if s in by_slot and by_slot[s].get('fact_id')],
               'collection_slot_ids': [s for s in r_['slot_ids']
                                       if s in by_slot and not by_slot[s].get('fact_id')],
               'proposed_thresholds': r_['proposed_thresholds'],
               'model_written_numbers': r_['model_written_numbers'],
               'source_spans': [by_slot[s]['char_span'] for s in r_['slot_ids'] if s in by_slot],
               'primary_url': packet['primary_url'],
               'source_hash': packet['artifact_sha256']} for r_ in rows]
    qa = evaluate({'sentence_to_source_ledger': ledger}, packet, must_include=[])
    text = '\n\n'.join(r_['text'] for r_ in rows)
    assert_exportable(text, f'live draft {did}')

    style_ok = (not st.get('checked')) or st.get('passed')
    ok = (not codes and qa['status']['qa_status'] == 'passed' and style_ok
          and lk['status'] == 'passed' and tl['status'] == 'passed'
          and og['status'] == 'passed' and rs['status'] == 'passed'
          and oc['status'] == 'passed')
    # What passing the gates does and does not mean, written into every record because the
    # status name alone misled me for weeks.
    #
    # Over 79 drafts the gates blocked 79 times, almost all of it the local 4B's output. Across
    # 25 drafts written by grok they blocked once, on a factual citation — the entire style
    # apparatus (sentence-length variation, figure density, machine vocabulary, the donor bands)
    # fired zero times. A human reading six of those same drafts called all six machine-written,
    # scored them 0.17 out of 5 for naturalness and marked every one 重写.
    #
    # Gates pass, human rejects. That is not a gate being slightly miscalibrated; it means these
    # checks do not measure what a reader measures. They are a cheap pre-filter that catches the
    # mechanical failures — a wrong figure, a copied passage, a prompt artefact — and they are not
    # a quality bar. `ml/human_review.py` is the quality bar.
    quality_note = {
        'gates_passed': ok,
        'means': ('every figure traces to the source document, nothing was copied from a '
                  'same-language source, no prompt artefact reached the text'),
        'does_not_mean': ('that it reads as a person wrote it. The only human review so far '
                          'rated gated drafts 0.17/5 for naturalness and asked for a full '
                          'rewrite of all six'),
        'human_review': 'pending',
    }
    rec.update(title=o.get('title'), text=text, sentence_to_source_ledger=ledger,
               quality=quality_note,
               qa=qa, checks=codes,
               language_donor=donor, style_check=st, leak_check=lk, tell_check=tl,
               originality=og, reader_check=rs, overclaim_check=oc,
               # Computed, kept, and deliberately never offered to the writer.
               crosslang_evidence_withheld=crosslang_evidence,
               # Which opinions were in front of the writer, by id and author, so a reviewer can
               # go read them. Empty here means the draft argued from figures alone.
               opinions_shown={
                   'window_days': opinions.get('window_days'),
                   'matched': opinions.get('matched'),
                   'error': opinions.get('error'),
                   'withheld': opinions.get('withheld'),
                   'arm': 'with_opinions' if use_opinions else 'no_opinions',
                   'posts': [{'post_id': x['post_id'], 'handle': x['handle'],
                              'lang': x['lang'], 'at': x['at']}
                             for x in (opinions.get('zh') or []) + (opinions.get('en') or [])],
               },
               style_status='passed' if style_ok else 'failed',
               qa_status=qa['status']['qa_status'],
               status='ready_for_queue' if ok else 'blocked',
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    rec['delivery'] = classify({**rec, 'content_status':
                                'ready_for_pipeline' if ok else 'blocked'})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (did + '.json')).write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return {'ok': ok, 'id': did, 'account': account['id'], 'entity': opp['entity'],
            'status': rec['status'], 'checks': codes,
            'style': rec['style_status'],
            'style_misses': [m['feature'] for m in (st.get('misses') or [])],
            'qa_blocking': qa['status']['blocking_count']}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    cfg = json.loads((ROOT / 'live/accounts.json').read_text())
    roles = json.loads((ROOT / 'evidence_loop/experiments/roles_v2.json').read_text())
    opp = json.loads((STORE / 'opportunities.json').read_text())
    # One entity can have several fact packs — $NVDA resolved to both an SEC filing with 3 facts
    # and the company's own release with 40. Keying a dict on entity meant the winner was whichever
    # file `glob()` happened to yield last, so the same command could write a good draft one run
    # and report "fewer than three usable figures" the next. Pick deliberately instead: the pack
    # with more usable facts, and a higher-ranked source to break a tie.
    packets = {}
    for f in sorted((STORE / 'packets').glob('*.json')):
        pk = json.loads(f.read_text())
        cur = packets.get(pk['entity'])
        better = (len(pk.get('facts') or []), float(pk.get('source_rank') or 0))
        if cur is None or better > (len(cur.get('facts') or []),
                                    float(cur.get('source_rank') or 0)):
            packets[pk['entity']] = pk

    tpath = STORE / 'style_targets.json'
    style_targets = json.loads(tpath.read_text()) if tpath.exists() else style_mod.load_all()
    for a in cfg['accounts']:
        if args.get('account') and a['id'] != args['account']:
            continue
        persona = roles['personas'][a['persona_id']]
        for s in opp['accounts'][a['id']]['selected']:
            pk = packets.get(s['entity'])
            if not pk:
                print(f"  SKIP {a['id']:12} {s['entity']:12} 无事实包，不写")
                continue
            # `--packet` is documented at the top of this file and was never read, so a run asking
            # for #yen_fx quietly wrote #inflation instead and the two were compared as though
            # they were the same event. A flag that silently does nothing is worse than no flag.
            if args.get('packet') and pk.get('id') != args['packet']:
                continue
            r = build(a, persona, s, pk, style_targets, writer_model=args.get('writer'),
                      use_opinions='no-opinions' not in args,
                      lane=args.get('lane') or s.get('lane'),
                      mode=args.get('mode') or 'profile_exemplars')
            print(f"  {'OK  ' if r.get('ok') else 'BLOCK'} {a['id']:12} {s['entity']:12} "
                  f"{r.get('status', r.get('reason'))} {r.get('checks', '')} "
                  f"style={r.get('style')} {r.get('style_misses') or ''}")
            if args.get('account'):
                break


if __name__ == '__main__':
    main()
