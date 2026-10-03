"""Source-specific judgment with silent evidence checks; no writing-action template."""
from live.distillation_prompts import DATA_RULE
VERSION = 'editorial-completion-prompts-v5-domain-policy'

PLAN = DATA_RULE + '''
Edit for the actual target account/audience/language. The original remains primary.
Select a worthwhile coherent excerpt or content unit for this audience, not a tour of every
interesting section. Keep the explanations, observations, examples, instructions or argument
that make it useful. Preserve the premises, conditions and tradeoffs its meaning needs. A cut should not leave
an opening promise unanswered. Do not impose one thesis, a length, a structure or an action label.
If a short post already works, select it whole and give little or no guidance. Do not restate its
logic or explain how its author must have calculated something. An available calculation is not
permission to add it. Repetition may be cut; a vivid example may be the point of carrying it.
Author experience, research, published work and firsthand access belong to that
speaker. Ordinary opinion, hypothetical and rhetorical first person need not become attributed
reporting. Choose treatment from this source, not a uniform account voice.
Missing quote/reply/thread/image context is not evidence the author omitted a claim. Select an
independent complete passage if possible; if essential context is unavailable, return needs_source
and a specific source_request. Never fabricate chart contents or silently complete a teaser.
Necessary linguistic explanation can use existing context. Request external background only if
these readers cannot understand this passage without it, with a concrete why_needed and a known
independent URL or catalog evidence_id. Do not manufacture a background request for every article.
You may request a necessary explicit calculation using kind=calculation, expression with named
Decimal operands, each {value, source_quote}, and why_needed. This is an editorial addition,
not an original-author claim. Usually leave arithmetic exactly as the source presented it.
Return JSON {"paragraph_ids":["P1"],"guidance":"brief source-specific advice, or empty",
"background_requests":[]}. If essential context is missing also return "needs_source":true,
"source_request":{"kind":"body/media/thread/reply/quote/context","reason":"specific need"}.
Selected IDs must be real and in source order. Quote and escape JSON strings correctly.
'''

ADAPT = DATA_RULE + '''
Produce this account's target-language adaptation from the selected original passages.
The full source is context; editorial advice is subordinate to it. Preserve meaning, reasoning,
emphasis and texture. Use the original lead and progression when they work. A natural faithful
translation may already be final. Edit what this source needs: remove genuine redundancy,
adjust syntax or briefly clarify a term; do not reconstruct it from a thesis or explain its logic.
Do not soften strong judgments, erase useful examples, add concluding lessons or impose a template.
Do not add a new percentage, causal explanation or arithmetic derivation just because the numbers
can be combined. Carry the author's existing calculation as written. Only explicitly requested,
evidenced background/calculations in factual_context can support an addition; do not attribute
those additions to the original author. If no addition is needed, add none.
Speaker ownership matters: past writing/research, job, experiments, private estimates
and firsthand contacts cannot become this account's experience. Use necessary
attribution locally or a clearly attributed quote. Merely mentioning an author somewhere does not
license first-person biography elsewhere. Ordinary I think / let's imagine / rhetorical we can read
naturally without repeatedly naming the author.
Treat quoted speakers and institutions separately from the post author. Keep personal predictions
as predictions and official company statements as attributed statements.
Keep QA and editing explanations private. Actual caveats and uncertainty in the source remain
content; do not add explanations about missing support or what would be a new opinion.
Return JSON {"segments":[{"text":"public paragraph","source_paragraph_ids":["P1"]}],
"editor_notes":"private actual editing notes","additions":[],"needs_source":false}.
For each actual external/derived addition, additions contains {output_quote,evidence_id,evidence_quote}
with exact quotes. Evidence is backstage, not an automatic provenance footer. Source-evidence links
can be retained when they carry meaning. Use only selected paragraph IDs; many-to-many alignment
is allowed and is not a paragraph template. If context is indispensable and missing, report
needs_source:true instead of guessing. Do not silently import claims from excluded sections.
'''

QA = DATA_RULE + '''
Compare candidate to selected source and full context. Review fidelity, not independent truth of
an author's claims. Editorial guidance can be wrong and cannot authorize an invented derivation.
Check facts, entities, conditions, causality, negation, modality/force, numerical metric bindings,
ranges, currencies, units, ratios, time periods and formulas. Numerical presence alone is not proof:
a new 'therefore 4%' or an explanation of where 4% came from is a new claim even if arithmetic works.
Distinguish a calculation already stated from a new one. Only declared, evidenced, editor-requested
additions are permitted, and their ownership must remain distinct from original-author claims.
Identity is contextual: ordinary opinion/hypotheticals/rhetoric need no automatic author label;
personal experience, experiment, job, private estimate, firsthand observation and prior
publication belong to the original speaker, including quoted
speakers. 'We explained in our previous article' is an authorship claim. Judge actual text,
not a writer's private claim that identity was handled.
Compression can omit repetition/independent sections, not necessary premises, meaningful examples,
conditions or tradeoffs. Check whether selection leaves its own opening promise unfinished.
Missing source/media/context is an unresolved dependency, not proof the author never said something.
Deterministic observations may be false positives (date spellings, code, repeated numbers). Resolve
these with evidence. Do not feed them back as prose to be inserted into the article.
All findings stay private. No suggested substitute prose, implications or repairs here.
An actual source caveat is content; newly added QA/editorial commentary is not.
Assess editorial quality separately in prose; no style score, template or minimum-edit gate.
Return JSON with:
checks: booleans facts_preserved,numeric_bindings_preserved,entities_preserved,reasoning_preserved,
stance_preserved,identity_preserved,no_unsupported_additions,no_editorial_commentary,context_complete;
identity_review: [{source_quote,output_quote,speaker,meaning,treatment,valid:true|false}];
calculation_review: [{source_quote,output_quote,kind:"existing or added",evidence_id:"or empty",valid:true|false}];
findings: [{severity:"fidelity|editorial",code,source_quote,output_quote,detail,repairable:true|false}];
numeric_notes: explanation of relevant differences; editorial_review: specific prose assessment.
Quotes must be exact substrings, or empty for additions/omissions. Treat uncertain fidelity as false.
Set repairable only for a local defect fixable by replacing the exact output_quote. Missing context,
wrong selection or a fundamental argument problem needs human review, not another writing round.
Unnecessary attribution may be a local editorial finding; rhythm/taste disagreements are not repair
instructions. A mild editorial criticism alone must not fail fidelity.
'''

IDENTITY = DATA_RULE + '''
Independently inspect speaker ownership in source and candidate. Do not rewrite.
Ordinary opinion, rhetoric and hypothetical I/we can stay natural. Do not require a byline by default.
Personal experience, experiments, employment, own estimates, firsthand contact and previously
published work cannot become the target account's biography.
Track the speaker of a quotation separately. Author name elsewhere is not enough to attribute an
unquoted first-person biographical sentence.
Return {"valid":true|false,"observations":[{"source_quote":"exact or empty",
"output_quote":"exact or empty","speaker":"who owns it","meaning":"what the first person does",
"treatment":"how ownership is carried","valid":true|false}],
"findings":[{"severity":"fidelity","code":"specific issue","source_quote":"exact or empty",
"output_quote":"exact local span","detail":"why ownership changed","repairable":true|false}]}.
No replacement prose. All analysis is private; uncertainty is valid:false.
'''

REPAIR = DATA_RULE + '''
Repair only the supplied actionable findings in the existing draft. This is not a writing task.
Return {"edits":[{"finding_id":"given ID","before":"exact flagged output_quote",
"after":"smallest necessary correction"}]}.
Only replace an exact flagged span. Keep every other character, paragraph, order and style intact.
Restore the source's numbers, bindings, modality or speaker ownership as needed. Do not add
explanations of QA, summaries, conclusions, caveats, fresh arithmetic, background or stylistic polish.
Use local necessary attribution for identity; do not delete the author's experience just to avoid I.
If a safe local fix is impossible, leave that finding unedited for human review. No new planning.
'''
