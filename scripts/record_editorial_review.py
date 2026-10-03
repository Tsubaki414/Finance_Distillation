"""Persist the assistant's concrete reading notes; never label them human review."""
from pathlib import Path
import json,hashlib,datetime
ROOT=Path(__file__).resolve().parents[1]
reviews=[
 {'draft_id':'draft-352bce35ef8e','location':'analysis_plan','quote':'劳动力需求意外强劲','issue':'没有分析师预测或其他预期基准，不能据修订值声称意外强劲。','evidence':'BLS facts F1–F4 contain observations and revisions, not analyst consensus.','severity':'needs_revision'},
 {'draft_id':'draft-1a44f7244d09','location':'p1','quote':'7 月原始数据曾被大幅下调再上调','issue':'提供的来源只支持从 -23,000 上修到 +21,000；负的初值不是此前下调的证据。','evidence':'F1 source span: July was revised up by 44,000, from -23,000 to +21,000.','severity':'factual_error'},
 {'draft_id':'draft-1a44f7244d09','location':'p2','quote':'岗位增加并未同步转化为劳动力参与率的提升','issue':'失业率不变不能确定参与率方向；本证据包没有参与率，前文“隐性过热”也缺乏支持。','evidence':'F3 establishes only that the unemployment rate was unchanged at 4.1 percent.','severity':'unsupported_inference'},
 {'draft_id':'draft-0ab61ffe759b','location':'p1','quote':'indicating a delayed surge in hiring','issue':'测量修订没有确立延迟招聘的机制。应该区分对同月测量的修正与实际招聘发生时点。','evidence':'F1 is a revision to the July monthly estimate, not a new observation of delayed hiring.','severity':'unsupported_inference'},
 {'draft_id':'draft-d18b7028456e','location':'p3','quote':'a correction of prior undercounting or a genuine acceleration in hiring','issue':'两者并不互斥；修订纠正同月测量，前后月份变化属于另一比较轴。当前写法混淆了估计版本与月份。','evidence':'F1 revision vintage is distinct from F2 versus F1 month-to-month comparison.','severity':'needs_revision'},
 {'draft_id':'draft-d03dbfb89606','location':'analysis_plan','quote':'劳动力需求意外增强','issue':'证据中没有预期基准；意外增强仍是缺乏支持的说法。','evidence':'F1–F4 contain no analyst consensus.','severity':'needs_revision'},
 {'draft_id':'draft-d03dbfb89606','location':'p1','quote':'7 月非农就业数据经大幅修订后转为增加 2.1 万人，显示劳动力需求显著增强','issue':'对同一个月估计值的上修不能直接说明需求随后显著增强；需要明确比较的是估计版本，还是前后月份。','evidence':'F1 is the updated July estimate; F2 is the distinct August observation.','severity':'needs_revision'},
 {'draft_id':'draft-4dbba5ff4794','location':'p2','quote':'表明新增岗位可能更多体现在非传统就业类别或季节性调整中','issue':'失业率不变没有提供岗位类别或季调贡献的证据。“可能”应写成待检验的替代假设，不能把这一比率当作该机制的依据。','evidence':'F3 is only an unchanged unemployment rate; no job category or seasonal contribution supplied.','severity':'unsupported_inference'},
 {'draft_id':'draft-be3804a57564','location':'analysis_plan','quote':'非农仍超 10 万','issue':'模型自行提出十万人的趋势验证阈值，没有校准或引用依据。该计划不能作为已验证判定规则。','evidence':'Neither the evidence bundle nor the persona profile establishes this threshold.','severity':'unvalidated_threshold'}
]
for r in reviews:
 d=json.loads((ROOT/'generated_samples'/f"{r['draft_id']}.json").read_text())
 text=d['analysis_plan'] if r['location']=='analysis_plan' else next(p['text'] for p in d['paragraphs'] if p['id']==r['location'])
 assert r['quote'] in text
 r.update(reviewer='Codex assistant close reading; not a human',human_review=False,source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),original_text_preserved=True)
out={'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Concrete findings from assistant close reading, including original v3 and repaired v4 drafts. Not exhaustive, not a benchmark accuracy estimate. Same-model semantic diagnostic accepted these drafts despite remaining content problems.','reviews':reviews}
(ROOT/'runs/automated-editorial-reviews.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'reviews':len(reviews),'drafts':len({r['draft_id'] for r in reviews}),'human_reviews_added':0}))
