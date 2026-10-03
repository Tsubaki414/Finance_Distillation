from pathlib import Path
import sys,json,datetime,hashlib,shutil
R=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation');sys.path.insert(0,str(R/'scripts'))
from handover_checks import collect,read,rows,sha
s=collect();now=s['generated_at']
def put(n,t):
 p=R/n;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():raise RuntimeError('Refusing overwrite '+n)
 p.write_text(t.strip()+'\n')
def js(n,o):put(n,json.dumps(o,ensure_ascii=False,indent=2))
js('handover/state-snapshot.json',s);js('handover/api-evidence.json',s['api']);js('handover/runtime-versions.json',s['runtime_versions'])
put('handover/requirements.freeze.txt','\n'.join(k+'=='+v for k,v in s['runtime_versions']['packages'].items()))
request_paths=[('01-original-project-brief.txt','/Users/fionama/.codex/attachments/7f55ba7a-0568-48da-9f97-2cfd535a03d4/pasted-text.txt'),('02-visual-brief.txt','/Users/fionama/.codex/attachments/16b0ed3d-0550-4379-8769-138281ac381b/pasted-text.txt'),('03-real-vertical-slice-correction.txt','/Users/fionama/.codex/attachments/340fb293-8145-4769-a7ac-a17343e934b7/pasted-text.txt'),('04-handover-request.txt','/Users/fionama/.codex/attachments/c279ddde-892e-4b89-8f00-595d8f20594b/pasted-text.txt')]
requirements=[]
for name,src in request_paths:
 dest=R/'handover/requirements'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(src,dest)
 requirements.append({'file':str(dest.relative_to(R)),'original_path':src,'sha256':sha(dest),'verbatim_copy':True})
js('handover/requirements/index.json',{'files':requirements,'precedence':'Later user corrections supersede earlier workflow/navigation/baseline wording; original product objectives remain. See CLAUDE.md and ACCEPTANCE_TESTS.md for subsequent chat corrections.','original_files_modified':False})
put('CLAUDE.md',r'''
# Finance Distillation — 接手入口

当前任务是完整项目交接，功能开发、UI 美化、内容生成均已暂停。接手先读此文件、`docs/CURRENT_STATE_AUDIT.md`、`docs/KNOWN_FAILURES.md`、`handover/verification.json`。没有用户恢复实施的指令，不启动生成或新采集。本文件记录用户要求，不能用旧 README、文件名或模型自评推翻它。

## 实际位置与冻结状态

项目根目录为 `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`，源码直接在本目录。不是 Git 仓库，branch/commit/dirty_files 均为 null；不要据此声称工作区干净。用户授权迁移所有项目文件，已保留完整模型、环境、数据及失败记录。`handover/migration.json` 有迁移前后 SHA-256 清单。旧 `outputs/vertical-slice` 仅是指向此目录的兼容链接，用于旧运行记录和 venv shebang；不要直接删掉旧链接后假设环境仍可用。

`historical_workspace/` 保留早期工作目录、Phase 0、旧交付 ZIP 和资源方案。旧 ZIP 不是本次交接包。原始 `Finance_Stocks_KOL` 工程、其 `.env`、用户原始 Excel/Reads ZIP 和全局 skills 没有移动。不能改写/删除用户原始输入。交接前的业务文件未修改，新增交接文件除外。

后端 :8680 和本地模型服务 :8683 已停止；旧浏览器标签可能显示缓存页面。`freeze.json` 覆盖展示状态，不改原始 case 的 running/started 记录。当前只能称为 `Corpus Import + Rule Filtering + incomplete evidence-loop experiments`；不是蒸馏 pipeline、ML persona 或已实现 multi-donor system。

## 产品真实目标

这是多语言金融内容情报与蒸馏系统，不是两个中英文账号生成器或静态文章生成器。汇聚中文、英文、韩文等金融、科技内容；来源包括 X、其他社交平台、YouTube、Bilibili、金融群、财报、电话会、机构研究、宏观数据和权威资料。保留原始文本/字幕、作者、时间、语言、平台、URL、来源 hash、证据和完整 provenance。

分别学习 Knowledge、Reasoning、Style、Content Habit、Visual Profile；特征必须有样本量、计算方法、支持 post IDs、版本和可观察范围。将 2–4 位互补 donor 的知识、推理、表达、习惯、视觉角色分别加权，不能把名单标签当组合证据。权重、真实检索 ID、profile version 和选择理由必须可见。

同一事件由不同 persona 独立提出问题、制定研究计划、取证、写作、配图；禁止先写母稿再换词/翻译。持续识别热点、计划事件、叙事加速/衰减/反转、共识、分歧、立场变化、首发与传播及跨语言信息差。自动运行到人工审核与内容交接；不包括自动发帖、账号设备/IP、互动、养号、流量运营或增长。

## 人设、内容线、语言、格式独立

初始 seeds：宏观数据与资金流观察者；个股及产业链硬核研究者；交易系统与市场心理教练。只是验证不同分析的首轮测试组，不是三个固定模板或最终账号数。跨语言能力不是第四个人设。

六条内容线：Hot Signal、Scheduled Catalyst、Evergreen Trading Principles、Prediction Ledger & Review、Cross-language Information Gap、Deep Research。系统以机会评分和 persona relevance 选择 `Content Lane × Persona × Language × Format`，不机械生成全部排列；允许不发、观察或等待确认。

## 产品入口与审核

一级入口为 Today / Intelligence Desk、Events & Opportunities、Accounts / Personas、Drafts & Visuals、Library & Updates。二级为 Sources & Corpus、Pipeline Runs、Quality & Evaluations、Settings。

首页回答 KOL database 现在说什么、叙事变化、谁最早提出/谁传播、共识分歧、CN/EN 信息差、未来催化事件、值得生产的内容、待审核稿件及来源/pipeline 失败。Corpus 属于二级审计。不要把 ETL 阶段设计成用户必须逐项推进的任务。

Persona Lab 使用滑杆、标签、donor 组合器、真实样本和同事件比较。每项显示自然区间、样本量、计算方法、post IDs 与当前值。Expert JSON View 只在高级设置。视觉必须依据问题选择原始截图、确定性数据图、结构图或不配图；宏观时间序列、产业收入桥/供应链、交易情境矩阵只是可用语法，不是强制模板。

## 事实、视频与实验纪律

- 完整原文→完整事实包→事实/观点/推断分离；Yahoo 只能补充，不能替代 IR、SEC、电话会原文。BLS 工资、参与率、兼职、行业贡献、历史均值、修订均不可被摘要裁掉。
- 每篇保留 source URLs/time/hash、事实包、donor/角色/权重/版本/真实 exemplars、prompt/model/temperature/seed/run ID、逐句 claim ledger 和 donor influence ledger。显示的是实际输入和声明使用，不应冒充模型内部因果证明。
- `legacy_invalid_output` 45 篇（另有 37 条 quarantined-generation）不得进入稿件库、待审核数、训练、few-shot 或正式评估。只留带标签的失败回归案例。目录名含 baseline 的旧生成记录也无效；不要重写或删除历史记录。
- 真正五组 baseline 必须在同一完整事实包、同批真实事件、同模型设置、同评估规则下新建。当前 15 格协议只有 4 格被尝试，3 格失败、1 格中断；有效新稿 0，真人标签和审核 0。
- 视频保留完整 transcript 和 segment，human_caption → auto_caption → ASR，之后说话人分离、金融实体/数字日期校正、分类、跨平台去重、统一 corpus。视频主要进入知识/推理/框架/预测/Evergreen，不直接学习 X 短帖 Style/Habit。
- 每段事实和 donor influence 可反查原帖或视频说话人/时间戳。多来源独立综合；除短句且明确署名引用，禁止复制表达、近义词洗稿、固定推广/导流/订阅/邀请码。
- 模型输出自评、规则银标、HTTP 200、文件数量、截图和安装 skill 都不是验收完成。必须保留失败、样本量、指标、盲测和人工修改量。

## 技能与资源约束

官方 jupyter-notebook/playwright/screenshot 已在全局安装；项目本地 `.agents/skills` 有审计后的选定 Xquik、金融补充、Trackio 和专属 financial-persona-distillation。锁定与产物对应见 `skill-audit/skills.lock.json` 和 matrix。新 X 采集只选 Xquik；kohoj 未运行，不混用。Xquik 未配置可用凭证/成本估计，不能拿 RapidAPI key 调它。既有 Apify/RapidAPI 是历史导入，不是新 Xquik 已运行。

train-sentence-transformers、huggingface-community-evals 已评估；LoRA/SFT 不启动，除非真实数据、基线、消融证明必要。writer-persona/Bespoke 只借鉴 stylometry、blind backtest、self-similarity、AI-pattern 机制，不照搬最终人设。SEC EDGAR MCP 仍禁用，需真实联系 User-Agent，不能编造身份。

只能使用用户指定的现有 Chrome window；ambient in-app browser 不构成授权。不得导出 Cookie、读取浏览器凭证库或绕过登录/锁屏。不得暴露 API key/token。禁止未经明确授权 push、部署、发布、购买套餐或批量付费调用。

## 接手次序

1. 运行 `sh scripts/verify_handover.sh`；以实测输出定位冻结状态、无效稿件残留接口及 source→plan→draft 的断点。
2. 用户恢复实施后，先修复全链路隔离和完整事实包审核，单格通过结构约束、预算、逐句引用与失败恢复，再扩到同证据五组实验。不要重新执行会覆盖失败记录的旧脚本。
3. 补足合格真人 donor/人工标注、Bilibili ASR/说话人和校正；用真实热事件与 Evergreen 完成图谱、自动更新和前端回放。完整标准在 `docs/ACCEPTANCE_TESTS.md`，不得因交接缩减。

四份原始任务文本逐字保存于 `handover/requirements/`；后续术语纠正、视频/六内容线、证据闭环和产品纠偏以本入口及验收文件补充。早期“四页”“旧 baseline”“先做 Phase 0”等表述已被后续用户要求覆盖。
''')
counts='\n'.join('| '+a['donor']+' | '+str(a['raw'])+' | '+str(a['clean'])+' | '+str(a['clean_original_rule_financial'])+' | '+', '.join(k+':'+str(v) for k,v in a['languages'].items())+' | '+a['oldest'][:10]+' → '+a['newest'][:10]+' |' for a in s['dataset']['authors'])
put('docs/CURRENT_STATE_AUDIT.md',r'''
# 实际状态审计

核验根目录为 `Finance_Distillation`。依据代码、JSON/JSONL、只读 SQLite、原始响应和当前核验，不依据旧 README/报告自称的完成度。`verified_working` 只适用于具体已执行子能力，不等于产品验收。全面机器统计见 `handover/state-snapshot.json`，API 证据见 `handover/api-evidence.json`；最新复核见 `handover/verification.json`。

下表“复跑命令”中 V = `sh scripts/verify_handover.sh`；其余命令仅供用户恢复实施后使用，副作用在 RUNBOOK 中。不能在交接期执行采集、生成或重建历史数据。

| 能力声明 | 实际状态 | 代码位置 | 数据证据 | 可复跑命令 | 结论 |
|---|---|---|---|---|---|
| X/KOL 真实采集 | partial | scripts/import_corpus.py；backend/app.py:47 | raw 2647，clean 1825，12 donor；5 份外部历史输入 | V；python scripts/import_corpus.py（会重写） | 真实导入；仅早期另有 6 次 RapidAPI 单页探测，新 Xquik 请求 0 |
| 翻页、回填、定期更新 | not_implemented | import_corpus.py 仅按已有记录截取；Xquik 仅文档 | complete_180d 全 false | V；无已实现新采集命令 | 最多 500 条限额不等于完整回填；无调度器或持久游标 |
| YouTube/Bilibili 采集与字幕 | partial | evidence_loop/discover_video.py、acquire_video.py、acquire_audio.py、transcript_pipeline.py | 7 metadata；3 YT/149 segment；3 Bili 音频/0 transcript | V；python evidence_loop/transcript_pipeline.py | 字幕分段运行过，ASR/说话人没有运行 |
| 财报与权威来源 | partial | fetch_primary.py、finance_supplement.py；evidence_loop/build_event.py | BLS 39 页文本衍生件，51 fact/616 block；NVIDIA 10-Q PDF；Yahoo 3 补充操作 | V；python scripts/fetch_primary.py | BLS 二进制 403；完整表格未逐格规范；SEC MCP 禁用 |
| 清洗、推广去除、去重 | partial | import_corpus.py、promotion_policy.py | raw/clean、raw_source_ref、runs/promotion-cleanup.json | V；python scripts/audit_promotions.py（写报告） | 同作者精确去重、规则过滤真实；跨作者语义去重/完整 thread 重构不足，非真人金标 |
| 五轴 donor profile | partial | evidence_loop/build_profiles.py | 12 个有样本/46 个仅候选，feature n/method/post IDs/versions | V；python evidence_loop/build_profiles.py（写） | 表层经验统计，非已验证知识能力或推理习惯；23 帖阅读样本、24 图目检均为 AI 检视 |
| ML 分类/聚类/attribution | partial | scripts/run_ml.py、classify_comparison.py | A/B 指标、真实 embedding、topic_clusters | V；python scripts/run_ml.py（写） | 训练/推理真实；规则银标和 6 作者时间划分结果，不是蒸馏效果 |
| multi-donor 检索组合 | partial | evidence_loop/prepare_experiments.py | routing/retrieval：3 persona×3 donor×2 exemplars、角色权重、版本 | V；python evidence_loop/prepare_experiments.py（写） | 真实检索已完成；multi-donor 条件尚未调用，未证明成稿效果 |
| 实际 LLM 调用 | verified_working | scripts/model_client.py | 727 attempt 文件：722 completed/2 failed/3 started，722 响应 | V；只读 model_calls | 是本地 MLX 真调用；completed 仅表示收到响应，含不合法 JSON 和无效旧稿 |
| 独立分析计划 | broken | evidence_loop/run_experiments.py | 4 新 plan 响应；3 length 截断，1 JSON 可解析；0 新完成稿 | V；生成命令当前暂停 | 每格独立调用设计存在；未完成三 persona 的有效独立研究 |
| 证据引用/donor influence | broken | run_experiments.py 后半段；backend 旧 F1–F3 路径 | 无新完成句级 ledger；旧稿全部无效 | V；无完整链路复跑成功证据 | 实際输入追踪和自报使用不同于因果 attribution；lineage broken |
| 跨语言蒸馏 | broken | scripts/run_generation_experiments.py、backend/guarded.py | cross_language_tests/* 历史调用 | V；旧流程不得再作基准 | 用旧不完整事实包，无真人评审；新完整证据跨语言尚未执行 |
| 热点/叙事发现 | not_implemented | 现有固定事件 registry；embedding 聚类 | 无执行的 Claim Card/Event Graph | V | 主题聚类不等于共识、分歧、首发或动量 |
| Evergreen 提取/冲突图 | not_implemented | 历史 knowledge enrichment 仅局部框架 | 无 Atomic Principle/Conflict Graph/resurfacing run | V | 视频摘要/框架候选不满足交易原则系统 |
| 图片与图表 | partial | backend/app.py chart_svg/diagram_svg；build_profiles.py | 真 PDF 截图、SVG、24 原图（22 eligible） | V；已有图函数仅旧稿 | 确定性渲染有证据；统一图形、缺 persona grammar/更新闭环 |
| 前端后端连接 | partial | frontend/app.js；backend/app.py | runs/live-api-verification.json 等历史结果；可静态追 routes | V；python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680 | 曾连接真实导入与模型；新 evidence_loop 未接 UI；迁移后停止服务，未浏览器验收 |
| 自动化 pipeline | not_implemented | start_local.py 仅启动服务器；新 main() 为手工批脚本 | 无 source→opportunity→review→update 定时/事件 run | V | 顺序 CLI 不是后台事件调度；无失败重试和证据触发回放 |
| 评测/真人审核 | partial | A/B 脚本、review API；新协议 | 517 规则复核中 300 scored/217 abstained；human=0；新 15 格未完成 | V；只读评测 JSON | 存在真实 ML 诊断，产品盲测、事实忠实度、编辑成本未验证 |

## 逐作者规模

“原创”列按现存 provider 的 `post_type=original` 和规则金融标签保守计数，不代表真人确认。大量 quote 可能含有原创评论，应人工核验字段含义后单独报告，不能把所有 clean 当原创或臆改标签。仅 2 人达到该严格计数 150；所有人 180 天完整性均未证实。目标语言名单不能覆盖实际语言：alea 主要 en，部分 ja/et 标签可能错误。

| donor | raw | clean（含 quote/reply） | 严格原创金融规则计数 | clean 语言 | raw 时间覆盖 |
|---|---:|---:|---:|---|---|
'''+counts+r'''

原始 URL/ID/作者 ID/时间/hash 字段当前非空；`collected_at` 缺失 2527/2647，`provider_run_id` 缺失 120。thread_id 非空仍不能证明父帖、quote 对象和传播关系齐全。raw 是继承的 normalized provider payload，不是所有原始 HTTP 响应。

## API 请求实证与未知项

| 对象 | 已记录数量与结果 | 分页 | 保存位置/限制 |
|---|---|---|---|
| RapidAPI twitter241 早期探测 | 6 HTTP，6×200；PhyrexNi、vikramskr、fi56622380 各 profile+timeline | 3 timeline pages；每人 1 页 | historical_workspace/outputs/architecture-review/evidence/rapidapi_probe.json；保存 preview/metadata，完整 wire body 未保留；费用 unknown |
| 现有 corpus 历史 Apify/RapidAPI | 5 输入文件、6 次本地 import，新增网络请求 0 | 原始采集请求数/pages unknown | data/corpus_manifest.json、data/imports、api_run_ledger；不能从 2647 条反推请求数 |
| 新 Xquik | 0 请求、0 pages | 0 | 已选定但缺 key/可审计成本；不是 RapidAPI 的别名 |
| 本地 MLX | 727 attempt 文件，722 成功响应、2 调用失败、3 started | 不适用 | runs/model_calls；ledger 重复同 run ID 不再累加；started 不能证明 dispatch；API 费 0，不含硬件 |
| 旧 BLS 抓取 | 3 次操作失败，日志未存具体 HTTP status | 不适用 | runs/api_run_ledger.jsonl；没有补造 403 |
| 新完整 BLS | 2 HTTP：原 PDF 403、Jina 文本 200 | 39 页源文，非 39 请求 | evidence_loop/sources/acquisition.json；hash 是衍生文本，不是 PDF |
| NVIDIA 官方链接 PDF | 2 HTTP：302、200 | 1 文件 | runs/official-pdf-capture.json 与原 PDF |
| Yahoo NVDA | 3 operation 成功，各 4 rows | wire 请求数 unknown | earnings_history/earnings_estimate/revenue_estimate；库缓存可复用 HTTP，不把 operation 数当请求数 |
| X 图片 | 24 HTTP 200 | 不适用 | evidence_loop/visual/assets.json；并非新增 X timeline |
| 视频发现 | 3 YT CLI 查询，各最多 5 条；2 Bili search HTTP 200 | Bili 各 page=1；YT 内部 HTTP unknown | transcripts/discovery/runs.json 和响应 |
| Bili metadata/player | 3 视频×3 HTTP，9×200；无匿名字幕 | 不适用 | transcripts/acquisitions/BV*.json 保存每个请求状态与 hash |
| YT 字幕/音频与 Bili 音频 | 3 YT 字幕成品；4 YT 音频失败；3 Bili 音频成功 | wire 总数 unknown | acquisition/audio logs；部分重试覆盖之前文件，完整尝试次数已无法证明 |
| SEC EDGAR MCP | 0 调用，禁用 | 0 | runs/sec-mcp-preflight.json |
| 其他公共研究/权重下载 | 总请求数 unknown | unknown | 审计文件和模型锁证明现存文件，不证明完整网络账本 |

不能因为累计 API 操作多就声称有效蒸馏。模型调用中的绝大多数来自旧生成和分类诊断，新闭环有效稿仍为 0。
''')
# Repository map generated from actual AST and migration inventory
routes='\n'.join('| '+q['method']+' | `'+q['path']+'` | `'+q['function']+'` | backend/app.py:'+str(q['line'])+' |' for q in s['routes'])
put('docs/REPOSITORY_MAP.md',r'''
# 仓库地图

实际根目录 `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`。无 .git。`historical_workspace` 是迁移保留的旁支材料，不能从中启动“产品”。旧路径兼容链接是本机迁移支持，不是可移植部署方案。

| 路径 | 实际用途与有效性 |
|---|---|
| frontend/index.html、app.js、style.css | 原四页 UI，默认 corpus；app.js fetch 本地 API。没有新 Desk、滑杆、Claim Graph 或 evidence_loop 前端 |
| backend/app.py | FastAPI 入口，挂载前端，读取静态 corpus/registry/旧 profiles，SQLite CRUD；通用生成被 acceptance gate 关闭 |
| backend/guarded.py | 旧生成/验证器，仍有可调用旧逻辑；不是有效生成基准 |
| scripts/ | 原采集导入、清洗、ML、模型、财务补充、生成、报告工具；handover_checks/verify_handover 为本次只读审计新增 |
| evidence_loop/ | 后续真实事实包、五轴画像、检索、协议、未完成生成、视频/视觉新工作；尚未整合前后端和调度 |
| data/raw_posts.jsonl、clean_posts.jsonl | 当前唯一 X 原始导入/清洗主文件；每行真实来源记录；不要把同一数据在 imports 的多版本相加 |
| data/corpus_manifest.json、imports/ | 输入文件 hash、导入 run、覆盖；旧导入快照保留 |
| data/lab.sqlite | 一个 records 表（下文）；无 normalized Event/Claim Graph schema |
| data/post_classification_review.csv | 517 规则银标复核，human_label 0；不是人工标注数据 |
| data/evidence/ | 旧 BLS 摘要 web-capture/registry、NVIDIA 原 PDF 与截图；固定 snapshot，旧 F1–F3 不能满足完整事实 |
| data/finance_supplement/ | Yahoo 和 NVIDIA 官方来源补充，外部第三方数据角色有限 |
| knowledge_profiles/、style_profiles/、content_habit_profiles/ | 旧画像版本，API 当前仍读这里；部分 LLM/规则局部提取，不能代表新五轴全部生效 |
| evidence_loop/profiles/、versions/ | 12 真实观测 donor，46 空语料候选，特征 n/method/post IDs/版本；index/reading-notes 非 donor |
| evidence_loop/experiments/ | protocol、routing、retrieval、4 cases；3 failed/1 interrupted，15 格计划未完成 |
| evidence_loop/sources/ | 原完整文本 acquisition/current/versioned packets，51 facts/616 blocks |
| evidence_loop/transcripts/ | 7 metadata、原始 VTT、完整文本、cue IDs、149 segments、Bili m4a/wav、发现/采集/失败 logs、audio model locks |
| evidence_loop/visual/ | 24 真实图片 .img（实际 JPEG/PNG）和 hash/像素/AI 目检；不是 24 张生成图片 |
| evidence_loop/quarantine/ | 45 无效稿 registry/排除策略；baseline-registry.json 已为 tombstone |
| personas/ | 旧 macro/industry/risk JSON；新 protocol 第三个 key 为 trading，不能直接当旧 risk API 已升级 |
| generated_samples/ | 45 旧无效稿件 JSON 原样保留，严禁训练/评估/产品计数 |
| ml_experiments/ | 真实 A/B 分析、embedding 缓存、银标预测、Trackio、notebook；D generation 和旧 blind 数据无效 |
| topic_clusters/、donor_compatibility_matrix.json | embedding 聚类及 donor 分布/相似度；非事件/立场/传播图谱 |
| cross_language_tests/ | 旧双向生成和自动评审；不完整事实包/无人审核，不合格 |
| runs/model_calls/、api_run_ledger.jsonl | 实际本地模型请求/响应、运行记录；失败/started 保留；API ledger 不能与 model_calls 重复计数 |
| runs/ 其余 | 旧测试/截图/自动审稿/更新回放；时间与输入各自冻结，不证明当前验收 |
| skill-audit/、.agents/skills/ | 锁定审计及六个项目 skill；安装证据≠对应产品能力完成 |
| .runtime/ | 模型权重/缓存，约 10.4 GB；模型锁在根目录和 transcripts；本机版本已保留 |
| .venv/ | Python 3.12.14 的本机环境，约 1.6 GB；console script 可能引用旧绝对路径；跨机器需重建 |
| historical_workspace/work/ | 原 scratch、repo-audit、npm/uv cache、临时依赖等，约 1.4 GB；有审计的未执行上游仓库 |
| historical_workspace/outputs/ | Phase 0 架构评审、静态 demo、旧 38 MB ZIP、早期资源方案；全部历史，不是新产品 |
| handover/、docs/、CLAUDE.md | 本次交接：来源、要求、事实状态、迁移哈希、运行手册、机器核验，不增加产品功能 |

## API routes（AST 读取，未启动服务）

| 方法 | 路由 | 函数 | 位置 |
|---|---|---|---|
'''+routes+r'''

## 数据库与调用

```sql
CREATE TABLE records (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
```

当前 kind：legacy_invalid_output 45、quarantined-generation 37、evidence 2、edit 2、diagram 3。draft/human-review 都为 0。payload 是 JSON，无数据库外键强制 provenance。`get(rid)` 不限制 kind，因此隔离存在旁路。审计用 SQLite `mode=ro`；不要 import app 作为“只读测试”，它的 db() 会建表。

模型调用统一位置 `scripts/model_client.py:call`，POST localhost `/v1/chat/completions`。三个模型角色 baseline/comparison/modern 只是旧运行时命名；其中 baseline 字样不能使旧稿成为实验基准。System prompt 在同文件；旧 prompt 在 backend/app.py、guarded.py、scripts/run_generation_experiments.py；新 prompt 在 evidence_loop/run_experiments.py。精确调用 prompt、temperature、seed、max_tokens、model revision 和响应在每个 runs/model_calls JSON。

## 固定值、fixture 与重复路径

- historical_workspace/outputs/architecture-review 中 review-demo 等是 Phase 0 static concept；以前报告与 ZIP 原样保留，不能用作现阶段验收。
- data/evidence/registry.json 和 scripts/build_evidence.py 有手填事件/摘要；固定 July→August replay 不等于自动更新。
- evidence_loop/build_event.py 固定本次 BLS 标题、月份措辞及 next_update；prepare_experiments.py 固定 embedding cache 文件名及初始三个问题。事件真实来源与硬编码解析逻辑必须分开描述。
- backend 图表针对固定 payroll/旧稿布局；app.js 默认 corpus/JSON 编辑；新文件的存在不代表前端使用。
- ml_experiments/baseline-v*、旧 D/blind/evaluation_report、generated_samples、cross_language_tests 中的生成结论全部依 `legacy_invalid_output` 政策处理；历史分类/attribution 原始预测可供诊断，不可混成新 generation baseline。
- 同一 post 在主文件、imports、model prompt 中重复保存不增加语料量；相同事件五组才可比较，而不是跨旧版本比指标。

原始迁移合计 81,389 文件、129 symlink、13,557,049,648 bytes（包含本机环境、缓存）。细到每文件 bytes/SHA-256 的 inventory 在 handover/migration.json。不要发布或上传整个目录：原始媒体元数据可能带已过期签名 URL，且模型/环境不是代码交付必需文件。本次仅本地迁移，没有对外传输。
''')
# Literal real lineage includes actual model input, not invented joins.
put('docs/DATA_LINEAGE.md',r'''
# 真实样本链路：lineage broken

样本事件 `bls-employment-2026-08`，version `75155f58f5a995e3`。该事件是真实获取的原文衍生件；以下仅证明存储及转换，未声称金融语义已经真人验证。取宏观 persona 的计划与真实 qinbafrank 检索样本；**没有完整 source→donor→draft→citation 成功链路**。

| 步骤 | ID / 文件 | 输入→输出 / 转换代码 | 时间、版本、模型、prompt | 状态 |
|---|---|---|---|---|
| 事件来源 | https://www.bls.gov/news.release/pdf/empsit.pdf；sources/acquisition.json | 原 PDF 403；Jina derivative 200→完整原文文本 | published 2026-09-04 08:30 −04:00；fetch 2026-09-06T04:36:38.223742Z | 衍生文本，不是原 PDF 二进制 |
| 事件 raw | evidence_loop/sources/bls-full-reader.txt | 163478 bytes，完整 39 页文本；SHA `23717afd4e5677deebb8fd19ff24e330756eef18aacd8f0d71f07957b74088d6` | acquisition 保存 URL/status/hash；无模型 | verified hash |
| fact | payroll；packet 75155f58f5a995e3.json | raw characters [600,653) → 162000 persons, 2026-08 CES，block B0012；build_event.py regex/单位换算 | 51 facts/616 blocks；processing observed_at 2026-09-06T04:58:36.271245Z | span 可逐字符复核；observed_at 误用处理时间，不是重新抓取时间 |
| donor source/raw | qinbafrank post `2072665494768021550`；data/raw_posts.jsonl | X 原帖 https://x.com/qinbafrank/status/2072665494768021550 → inherited provider source_record/hash | created 2026-07-02T12:55:36Z；import-794f061e4f6d；collected_at 以原行字段为准，缺失不补 | 历史 donor 表达，不是本次 Aug 数据证据 |
| donor clean | 同 post ID；data/clean_posts.jsonl raw_source_ref | promotion_policy + import_corpus.classify、同作者精确去重；原 raw 不改 | rules-v3-commercial-cleanup；无 LLM | clean 可回 raw payload SHA；语言/原创分类未真人审核 |
| donor quantification | qinbafrank profile `a8e2585d5d288be0` | 312 clean 帖 → knowledge/ reasoning/style/habit/visual；每项 n、公式、support/denominator IDs | empirical-five-profile-v1；profile window 2026-07-01→09-05 | 表层统计；全语料回顾画像含事件后帖子，不是 point-in-time backtest |
| retrieval | experiments/retrieval.json results.macro[0] | 真实 query embedding→该 post cosine/排序，macro 共 3 donor×2 exemplar | MiniLM-L12-v2 rev e8f8c211226b894fcb81acc59f3b34ba3efd5f42；routing 指定版本；created protocol 2026-09-06T05:10:26.192706Z | 真实检索，历史样本均早于 event release |
| 组合决策 | experiments/routing.json macro | qinbafrank、phyrexni、michael_qqq2025；分五角色权重 | top2 cosine/主题率/样本数的人工公式；非学得最优组合 | planned route；没有被本次已运行 simple/base plan 消费 |
| 实际 neutral plan | case-3805e3a232c8；model call local-a1ec004c02684efa | 同完整 narrative+51 typed facts→plan JSON；无 donor/persona（控制组设计） | 2026-09-06T05:12:37.545840Z；modern 锁定 Qwen3.5-4B、temp .2、seed42、max_tokens650 | finish_reason=length，650 tokens；JSONDecodeError，未到 draft |
| 实际 persona plan | case-21b8d4f70185；local-e34f0c6259364bd3 | 同事实+macro name/question→独立计划；没有 donor profile/exemplar | 2026-09-06T05:15:30.679265Z；temp .2、seed42、650 budget；532 output tokens；stop | JSON 可解析；无真人研究质量认证 |
| draft | local-0538caa511c642cf；task evidence_loop_draft | 请求文件记录新事实和独立计划，max_tokens2400；响应未保存 | 2026-09-06T05:16:25.719936Z，started；之后用户要求停止 | 中断；case 未保存 generation_run_id，只有时间/task/context 关联，不伪造直接外键 |
| citation/influence/QA | 当前新 case 无 sentence_to_source_ledger / sentence_to_donor_ledger | run_experiments.py 后续代码未到达成稿完成 | 无完成时间、无新稿 hash、无事实忠实度/盲测/编辑成本 | **lineage broken** |

完整模型 revision、request messages、temperature/max_tokens、输出及错误均以相应 model_calls JSON 为准。三次 neutral base 的相同输入/seed 输出重复是控制设计，不是三个 persona 研究成功。尚未执行 structured/profile+exemplar/multi-separated 格；不能将预先准备的 retrieval 拼接成“实际 donor influence”。

视频旁支例：`youtube:6weg9-YmGVs:22666-7eb1cb12` 在 transcripts/segments.jsonl，对应原 VTT、cue-1 等 IDs、22.666–69.1 秒和 timestamp URL。raw_hash 校验通过，但 speaker=null、没有 Claim Card、未合入 donor profile。该视频发表于非农之前，不能标为非农公布后的反应。此 segment 也不能补成上面断掉的 donor→draft 链。

下一次合格证据闭环必须有主键连接所有阶段，记录真实消费 ID 而非预选 ID，并将逐句引文的“ID 有效”与“事实支持该句”分别评估。缺数据时保持 null/unknown，不让提示词补造。
''')
put('docs/VIDEO_TRANSCRIPT_PIPELINE.md',r'''
# 视频语料：要求与已运行状态

要求是可检索、可追溯的视频语料蒸馏，不是视频摘要。来源全片 transcript 和 segment 永久保留；人类字幕优先→平台自动字幕→无字幕时 ASR。然后说话人分离、金融专名/ticker/数字/百分比/日期校正、segment、内容分类、统一 KOL corpus、profile 更新，再进入热点或 Evergreen。

## 上游审计

`KIRVO-REPORTING/video-to-notes` 已阅读审计，commit `aa06415ef985290398db765271d6e85a66c436db`，证据 `evidence_loop/video-audit.json`（11 文件 hash）和 `historical_workspace/work/repo-audit/video-to-notes/`。没有执行上游 installer 或摘要 pipeline。可借鉴 discovery、metadata、caption fetch、timestamp、Whisper fallback；不能复用自动摘要作为蒸馏结果。

审计发现字幕处理会丢时间结构、installer 有全局目录删除路径、可选浏览器 cookies/Notion/Obsidian 配置和媒体清理路径。项目自写 wrapper 保留原文件，匿名公开访问，不抽取账户 Cookie。Bilibili CLI 0.6.2 wheel 仅审计未安装运行，其 auth 可能读本地凭证/浏览器刷新；实际采用匿名 bilibili-api-python 获取允许的音频。具体网络/凭证/费用审计以 video-audit.json 为准。

## 当前真实数据

| 视频 ID | 平台 | 已保存 | 未完成 |
|---|---|---|---|
| 6weg9-YmGVs | YouTube 游庭皓 | metadata、auto_caption zh-TW、1172 cues、47 segments、全文/hash | speaker 未分离；该片早于 BLS 发布，不能当事后观点 |
| VFPlA2c5MfI | YouTube Brian Shannon | metadata、auto_caption en-orig、2761 cues、75 segments、全文/hash | speaker/金融语义校正/原则提取未完成 |
| tOk7gGe_jj0 | YouTube The Quant Brief | metadata、auto_caption en-orig、1037 cues、27 segments、全文/hash | 没有进入热点 Claim Graph |
| 01s3YdYUCcU | YouTube 美投讲美股 | metadata | 无字幕；音频 403，未 ASR |
| BV1eubj6GEaV | Bilibili 川叔叔Chris | metadata/player 响应、m4a/16k WAV/hash | 匿名字幕为空；ASR/说话人未运行 |
| BV1qMt26hEGs | Bilibili 笨鸟不会飞怎么飞 | 同上 | 同上 |
| BV1xS4y1x7Tp | Bilibili Jim做交易 | 同上；2022 历史交易知识视频 | ASR/原则/反例/冲突图未运行 |

目前共 149 segments，规则标记 knowledge_eligible=108；这不是通过真人审核的 108 条知识。没有 Bilibili transcript，未满足 3+3 验收。下载 Whisper Turbo 与 diarization ONNX 权重只证明准备完成，锁在 transcripts/audio-model-lock.json；没有 ASR/diarization 输出。准备/采集脚本有部分 log 覆盖历史重试问题，不应再次覆盖。

## 必需 segment contract 与当前差距

必须包含 platform/channel/video ID/title/published_at/original URL、start/end、speaker/speaker confidence、raw caption/clean text、caption_source (`human_caption/auto_caption/ASR`)、内容类型（事实、观点、推理、预测、案例、交易规则、广告、闲聊）、公司/ticker/资产/宏观指标/数字/日期、主题/方向/周期/置信度、timestamp URL、raw_file/hash/cue IDs、提取模型/版本/run ID、纠正前后与证据。

现有 segment 已保存 metadata、raw/clean、时间/hash/cue引用和时间戳链接；speaker/confidence 是 null，分类是 provisional regex，方向/周期/置信度为 unknown。不能把字符规范化当数字事实校正；ASR 数字和名称仍需原音、官方出处校验。speaker confidence 设计为时间重叠率，不是校准概率或真人身份认证。

跨平台去重需要 title + transcript 语义/指纹、可用时音频指纹并保留两个 URL。现有代码仅对 transcript_ready 比较；3 个 ready 全来自 YouTube，实际跨平台配对 0。`cross_platform_dedup=[]` 不能解释为已验证没有重复。

视频应主要更新 Knowledge/Reasoning Profile、Framework Library、Prediction Ledger、Evergreen Library。当前尚未写入统一 corpus 或这些 profile。短帖 Style/Habit 继续主要从真实短帖学习，149 segments 均 short_post_style_eligible=false。

恢复实施后先校验 Bili 3 音频→ASR→说话人→金融数字/日期→完整 segment；原 VTT/音频不删。之后至少两个与同一真实热点有关的 segment 和五名 KOL 原帖形成 Claim Graph。保留适用范围、不能把发布前视频当事件后反应；提供完整回放和时间戳回源。
''')
put('docs/CONTENT_PIPELINES.md',r'''
# 两条生产链和六条内容线：验收合同

以下是用户要求与接手实施合同，**当前未实现的能力不得因本文件存在而被标为完成**。已运行的局部数据入口见 CURRENT_STATE_AUDIT；没有可回放的 Hot Signal 或 Evergreen 完整产物。

## Hot Signal → 多来源独立综合

真实 post/transcript segment → 金融 claim 抽取 → 同事件聚合 → Event/Claim Graph → 机会排序 → persona/donor 路由 → 各 persona 独立分析计划 → 新稿/视觉 → 来源/风格/多样性 QA → 人工审核 → 新证据触发影响检查和版本更新。

Claim Card 必须有 KOL、source ID、原文、原始时间/URL/视频时间戳、核心 claim、stance（bullish/bearish/neutral/conditional）、分析对象、horizon、evidence、conditions、invalidation、conviction、novelty、originator/amplifier/补充证据/简单转述，以及抽取模型/版本和原始支持 span。conviction 是表达强度，不冒充观点正确概率。

图谱识别 consensus/divergence/contrarian、narrative acceleration/reversal、originator/amplifier、CN/EN information gap。先保留命题、条件和时间周期，再判同意/冲突；不要把同一关键词或同一方向当相同论证。首发必须注明“当前观测来源内最早”和采集覆盖，不能声称全网第一。传播边必须有 reply/quote/link 或相应可审计证据，未知不补造。前后立场变化必须对齐对象/时间/前提，避免错判反转。

选 2–5 个互补 KOL 观点，加入至少一手宏观/公司/监管事实；先形成新的分析问题、推理大纲、反证/不确定项，然后生成。每 persona 通常 2–4 donor、角色分开。每段事实来源和 influence、每句 claim ledger、实际输入 IDs/权重/profile version 可追溯。检查句子复制、n-gram 和 embedding 语义重叠；阈值经真人校准，不能仅换词避重复。除短且明确署名的引用，不复制原表达；广告和固定交易平台推广不得进入成品。

Opportunity Card：事件、为什么现在、完整事实、共识/分歧、最早来源/传播、跨语言差、证据置信度、拥挤度、推荐 persona/格式/原因、时间窗口、next_update、已生成/待审/证据不足。评分要记录版本、分量及数据缺口；无充分价值可以不生成。

生命周期：T−7d 背景预期争议；T−24h 定价与新预期；T0 事实快报；T+30m 第一轮 KOL 反应；T+4h 共识分歧遗漏；T+1d 完整分析与价格验证；随后新证据触发 V2/V3、diff、修订原因、被影响段落和旧图失效。planned/breaking/evergreen 的 freshness 与更新策略不同。

## Evergreen → Atomic Trading Principle

来源为 KOL 历史帖、访谈/课程/视频、交易书籍/研究、金融群的有效讨论，以及中文、英文、韩文等市场框架。OCR/整理材料可以提供知识线索，不能当作者原始短帖语言。Reads 历史材料默认冷知识，缺原始出处的要标低确定性并补源。

每条原则必须保留 source IDs、原话或明确标记转述、原始时间/时间戳、核心原则、适用市场/周期/regime、前提、执行步骤、失效条件、常见误用、反例、冲突/互补原则、历史与当前案例、来源可信度、最后复核时间。不能只取金句。

覆盖仓位管理、风险收益、止损退出、入场确认、趋势/均值回归、交易纪律、回撤、情绪、信息优势、复盘、环境识别、系统构建、预测与概率。语义去重需保留各来源和差异；建立 Conflict Graph，区分有条件冲突/互补。例如快速止损与给逻辑时间要按周期、止损定义和证伪条件展开，不粗暴合并。

至少支持：原则+真实案例、金句完整上下文、常见误用、流派冲突、近期行情验证历史原则、决策树/情景矩阵、历史复盘、每周训练题、完整方法论拆解、中外框架异同。由价值选格式，不统一模板。

Resurfacing 必须由当前 regime/事件/价格结构与历史条件匹配触发，记录匹配证据、阈值、排除反例、旧源、当前源及入队时间；提供一次端到端回放，不能随机每天抽一句。

## 六内容线与自动化合同

| 内容线 | 为何此刻生产 | 主要来源/生命周期 |
|---|---|---|
| Hot Signal | 新事件/叙事加速/分歧 | 原帖、视频、官方新证据；小时→天 |
| Scheduled Catalyst | 未来事件有准备价值 | IR/官方日历、预期、背景；T−7d→后续验证 |
| Evergreen Trading Principles | 知识缺口或情境触发 | 历史原则、案例、冲突；长期，定期复核 |
| Prediction Ledger & Review | 预测条件到期/证据变化 | 原预测、条件、结果、修正；保留事前记录 |
| Cross-language Information Gap | 某语区缺框架/背景/事实 | 同命题跨语料证据，市场本地化；不能仅翻译 |
| Deep Research | 个股/产业/机构长期问题 | 财报、电话会、供应链、研究；专题版本化 |

lane/persona/language/format 是独立维度；按机会评分选择，不能扩成固定全排列。人工主要在 donor 初审、人设校准、冲突异常、最终审核和交付；日常素材发现/路由/更新不要求人工推动每一阶段。

真实后台需 source sync → pagination/backfill → normalization → thread/reply/quote reconstruction → classification/dedup → profile refresh → event/narrative clustering → opportunity scoring → routing → independent research planning → draft/visual → fact/style/diversity QA → review queue → update monitoring。每个 run 必须有触发源、开始/结束、处理数量、失败来源、重试状态、输入 hash 和产物版本。当前上述多阶段缺实现；已安装 APScheduler 依赖不等于启用调度。
''')
print('Created primary handover documents, runtime/API snapshots and original requirement copies.')
