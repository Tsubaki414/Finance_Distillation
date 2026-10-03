from pathlib import Path
import sys,json,datetime
R=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation');sys.path.insert(0,str(R/'scripts'))
from handover_checks import collect,read
s=collect()
def put(n,t):
 p=R/n;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():raise RuntimeError('Refusing overwrite '+n)
 p.write_text(t.strip()+'\n')
put('docs/KNOWN_FAILURES.md',r'''
# 已知失败与复现

本文件是失败交接，不做功能修复。所有原失败、模型响应、未完成记录和旧报告保持原样。只读复现统一使用 `sh scripts/verify_handover.sh` 或查看下列文件；标注“恢复后”的请求/运行不在交接期执行。

| 问题 | 根因与影响 | 证据 | 已修复？/如何复现 |
|---|---|---|---|
| 早期仅 6 个 API 请求 | 三账号各 profile+一页；只能证明 endpoint | historical_workspace/outputs/architecture-review/evidence/rapidapi_probe.json | 未补成新实时 collector；核对 requests/page 数 |
| 12 donor 深度不足/语言配额失真 | 6 个英文种子仅 20 raw 左右；clean 混 quote/reply；target_language 不等于真实语言 | corpus_manifest、handover/state-snapshot dataset.authors | 未修复；严格 original 计数仅 2 人≥150，全部 complete_180d=false |
| 采集时间/线程缺失 | 继承 normalized payload，2527 collected_at 缺失，原 wire 日志不齐；thread_id 非空不证明引用对象完整 | raw_posts missing_fields/source_record | 未修复；按缺失字段、quoted_post/reply_to 检查，不能伪造 |
| 页面数字被误读为新采集/有效内容 | 读取 manifest/旧统计，部分静态标签；同数据多版本易重复计数 | backend status/corpus/experiments；旧 evaluation_report | 部分暂停标签已改；旧前端“真实草稿”等措辞未清理；核对 SQL 与 API 实际来源 |
| BLS 已有工资等却声称没有 | 旧 registry 只有 F1–F3，旧 prompt/validator 仅消费摘要且将“缺工资”当正确 | data/evidence/registry.json；scripts/validate_slice.py:68；旧 generated_samples | 旧稿永久无效；新 full text/51 facts 补上，但新稿未完成 |
| 完整文本不等于完整结构事实包 | 51 typed narrative facts；表格虽全文保存，未逐格规范和校验；当前 prompt 只传 narrative+typed facts | build_event.py；run_experiments.material | 未完成完整事实闭环；查看 packet.coverage/full_narrative 与 blocks，逐字段审稿 |
| 3 个新 plan JSON 截断 | max_tokens650，finish_reason=length，三个相同 neutral control 输出 JSON 未闭合 | case-3805e3a232c8/4b1357a15932/0efa90d2caaf；各 plan model_calls | 未修复；只读 json.loads(plan_raw) 会报 JSONDecodeError；不要重新生成覆盖 |
| 第四格中断 | 用户要求交接，停止本地生成；case running、draft call started 原样保存 | case-21b8d4f70185、local-0538caa511c642cf、freeze.json | 人为冻结不是完成；generation_run_id 没有写回，不能强接因果链 |
| 独立计划语义仍可能越界 | JSON 合法不保证推理：就业量/政策路径、行业历史均值等可能超出证据；未真人评 | local-e34f0c6259364bd3 响应与完整事实对照 | 未修复；要独立事实支持审核，不只引用 ID 白名单 |
| multi-donor 未证明 | 新 routing/retrieval 实际产物存在，multi-separated 条件没有运行；旧实际 context 不合格 | experiments/routing/retrieval/protocol/cases | 未完成；逐个实际 model request 查 donor/profile/exemplar 输入，不能以预选名单替代 |
| donor 画像测量范围有限 | regex 因果词不等于 reasoning，表层词频不等于 knowledge；不完整 timeline 不能推 reaction latency | profiles method/limits/window；build_profiles.py | 未修复；每项 n/method/IDs可查，但正确性需独立评审 |
| 回顾画像泄漏/embedding cache 固定 | profile 全语料含事件后样本；prepare_experiments 固定旧 cache 文件名，未强校验当前 dataset hash 相等 | prepare_experiments.py；embedding_manifest.json | 部分：retrieval post 时间过滤已执行；point-in-time profile/cache 防错仍缺 |
| 权重/视觉解释过度 | 权重是人工公式，3 donor 所有角色复用，零视觉证据也可能平滑出权重；照片可能是上游软件配色 | routing.roles；profiles.visual；visual/assets.json | 未修复；不能声称 learned/optimal visual personality |
| 旧 45 不能叫 baseline | 事实包不全、错误检索、donor 不可追踪、无真人；另 37 条旧拒绝生成 | quarantine/registry；SQL kind；generated_samples | SQL 已标 legacy_invalid_output；旧文件保留，禁止产品/训练/few-shot/正式评估 |
| 隔离不覆盖全部接口 | get(rid) 无 kind 限制；audit=true detail/export仍把旧稿叫 baseline；chart/diagram/history/edit 可触达旧 ID | backend/app.py:26,143–210 | 未修复；恢复服务后对 registry 中旧 ID GET chart 或 audit detail 即可验证；交接期只读代码 |
| quarantine 脚本非幂等 | 首次执行将 baseline-registry 写 tombstone；二次 read 优先非空 tombstone，缺 drafts | evidence_loop/quarantine.py:6–7；baseline-registry.json | 未修复；静态数据读 `old['drafts']` 可见 KeyError；不要跑 main 作为测试 |
| 0 真人标签/评审 | 517 是严格规则复核，300 scored/217 abstained；自动评审不能算人工 | post_classification_review.csv human_label；records human-review=0 | 未修复；不能把 rules F1=1 或 LLM 自评分当产品质量 |
| 旧跨语言稿无可比性 | 使用旧事实包，包含否定/数字语义错误，缺真实信息差和编辑成本 | cross_language_tests；old model_calls | 新完整证据双向实验未运行；旧稿仅 failure_case |
| 首页暴露 ETL / JSON 人设 | default corpus；固定四页；新五轴文件未路由至 UI | frontend/app.js、index.html；backend profiles/personas | 未修复；无 Desk、滑杆自然区间/样本或新 ledger 前端 |
| 配图单一/视觉不随证据更新 | 固定 payroll SVG 与通用结构图；缺问题驱动 grammar、生命周期 | backend chart_svg/event_diagram；旧 diagrams | 未修复；新24图只是分析语料，不能计为合格原创视觉 |
| 无自动更新与事件生命周期 | main 批量脚本靠手工执行；旧 fixed snapshots 手工 POST；无 scheduler/监听/游标/重试状态机 | start_local.py、backend events/ingest、guarded-update-replay | 未实现；不能把先后运行两个脚本或按钮回放称自动化 |
| 视频 ASR/说话人未执行 | 3 Bili 字幕匿名为空，4 YT 音频失败；权重准备≠运行 | transcripts/index、audio-runs、audio-model-lock | 未修复；0 ASR/diarization 文件、Bili segment 0；只读核验 |
| 字幕优先级与财务校正不足 | build() 偏好 en-orig 文件名，不先枚举人类轨；auto_caption 数字也可能错，却仅 ASR 标 requires_numeric_review；ticker regex 输出 tuple | transcript_pipeline.py build/merge_video | 未修复；当前恰好是自动字幕，未证明 manual-first 或金融数字校正 |
| 视频跨平台去重未被测试 | 只比 ready 视频；目前 ready 全 YT，0 cross-platform pairs；audio fingerprint null | transcripts/index cross_platform_dedup=[] | 未完成；空列表不等于成功去重 |
| 视频广告漏识别 | 规则词表有限，部分听友会/订阅口语不标 advertising；数字可能落 factual_statement_unverified | segment youtube:6weg9-YmGVs:22666-7eb1cb12 | 部分该段 knowledge_eligible=false，但不能依赖偶然主题过滤；需系统广告检测，原文保留成品排除 |
| 视频未进入统一 corpus/profile | segment 单独 JSONL，未更新 donor knowledge/reasoning/预测库 | import/profile 输入仍仅 X clean | 未实现；149 segments 不等于已用于蒸馏 |
| acquisition 重试日志被覆盖 | acquire_video/audio 对固定文件名 write_text，历史失败试次被后次覆盖 | scripts与现有 acquisition/audio logs | 未修复且缺失记录不能恢复；今后 append-only，当前 unknown 完整次数 |
| 不稳健事件日期/抓取时间 | build_event 固定本次月份/措辞，next_update incomplete；observed_at 取错 acquisition 字段 | build_event.py、packet.next_update/acquisition | 未修复；下一月换原文可能解析失败；processing time 不能冒充 observed source time |
| 环境与端口迁移限制 | venv/shebang/若干锁内绝对路径；用户只授权现有 Chrome，无法完成锁屏后 UI验收 | migration.json、pyvenv.cfg、旧 browser-verification | 本机兼容链接保留；新 Python已运行；服务有意停止，不宣称当前浏览器通过 |

原 A 分类宏 F1：char TF-IDF 0.8962、embedding logistic 0.8343、7B LLM 0.8233（298/300 可评分）；全为规则银标一致度。作者 attribution 为 6 作者/360 测试帖，style 0.7163、embedding 0.6425、combined 0.7595；按时间/线程划分有证据，但语言/话题混杂与样本失衡仍在。没有 LoRA/SFT 或 sentence-transformer fine-tuning。现有 KMeans/JS distance 不证明上游首发或互补独立知识。
''')
put('docs/ACCEPTANCE_TESTS.md',r'''
# 保留的全部验收门槛

交接不取消、不缩减此前要求；下列门槛是恢复实施后的验收合同，不是已通过清单。详细原始产品与视觉要求逐字保存在 handover/requirements；后续本文件中的更严格纠正优先。机器脚本检查可证明的结构/计数，人工语义评估不得由模型代填。

## A. 真实来源与 donor

- 至少 12 名真实 donor，目标至少 6 中文、6 英文，覆盖宏观、产业、交易心理；按真实发文语言统计，不用表格主观评价或目标语言冒充实测。
- 每人最近 180 天或最多 500 timeline items（达到上限应保存游标、边界/停止原因和仍未覆盖范围），时间顺序、original/reply/quote/repost 关系完整。每人至少 150 条作者真正产生的可用金融原创内容；quote/reply 里的原创分析应单独核验，不将转述/广告充数；不足则替换。整体约 1800+；总量不能代替逐人门槛。
- raw/clean 均保留：stable_author_id、handle_at_collection、post_id、URL、created/collected、语言、媒体、thread/reply/quote/repost、engagement_snapshot、source/provider run/hash；保存分页/API 请求/响应、费用估计与实际量。新 X 只用审计后选定的 Xquik，不能同时运行 kohoj。
- 原样保留 raw，清洗移除推广/广告/生活/无依据喊单，记录 span、规则/模型/版本、置信度与理由。分类覆盖原始任务的 13 类。300 条真正人工标注的随机/分层抽样、标注人、时间、分歧处理；规则复核不能替代此后新增的人类要求。
- 新 Excel 只身份/平台/URL/发文语言/候选，禁止采纳后面对作者的主观商业评价；外平台 transcript 不直接作短帖 Style/Habit。

## B. 画像、ML 与多 donor

- 每位 donor 的 Knowledge、Reasoning、Style、Content Habit、Visual 五轴均可计算：样本量、方法、自然区间、支持与分母 post IDs、版本、时间覆盖和 unknown 范围。
- 知识框架/因果机制/风险/时间周期/立场变化/预测证实证伪/知识边界均有原始支持，不能仅让模型写人物简介。
- 风格包含句段长度、数字/ticker/link 密度、图表比例、问题/第一人称/hedge、证据开头/结论开头、列表碎句/长论证、术语解释、引用/开结尾等；习惯包括间隔/爆发沉默、工作日周末、回复引用、主题时长、反应延迟、承认错误/更新等。不完整时间序列下不可观测项明确 unknown。
- 相关性分类比较规则、传统/embedding、LLM；precision/recall/F1、置信区间、失败例、样本数/拒判。银标结果单列。
- 作者/style attribution 使用 stylometry+embedding、轻量模型，按时间和完整 thread 划分，去重/泄漏控制，报告准确率/macro-F1、语言/多数类对照和关键特征。
- 主题聚类和知识差异展示真实帖子、上游来源重复与互补依据；Jensen-Shannon/embedding 距离只作为测量之一，非互补结论。
- 每 persona 选 2–4 donor，Knowledge/Reasoning/Language/Habit/Visual 角色分别说明真实权重、profile versions、retrieved post IDs 和 exemplar、取舍理由。不同 persona 同事件独立研究；可因不相关而不生成。
- Hugging Face 三项技能有实验证据与产物对应；不启动 LoRA/SFT，除非真人数据、有效 baseline 和消融支持必要性。全局官方/项目 skill 的存在不能算模型效果。

## C. 完整事实包与五组新实验

旧 45 为 legacy_invalid_output/failure_case，另有 37 拒绝尝试；全部从产品稿件/待审/训练/few-shot/正式评估/质量统计隔离。只保留少量明确标注失败回归案例；旧目录名含 baseline 不改变其无效性质。

用同批真实事件、完全相同完整事实来源/版本/hash、同模型 revision/temperature/seed/预算策略、同语言与格式条件，重新运行：Base Model、Simple Persona Prompt、Structured Persona Profile、Profile + Retrieved Exemplars、Multi-donor Separated。预注册样本、指标、失败/重试策略、重复次数；报告分布和不确定性。单事件单 seed 的 15 格只能是试点，不是普适优越性的结论。

BLS 同一事件必须消费完整原文：工资环比同比、参与率、兼职、行业贡献、历史均值、修订及相关表格/脚注/调查口径。每个 persona 独立 Analysis Plan；禁止母稿改写。至少覆盖宏观、产业链、交易心理三组。

逐篇保存并在前端展示 event source URLs/time/hash、完整提取事实、donor 及角色、实际检索 post IDs、选择理由/权重/profile version、prompt/model/temperature/seed/run ID、逐句 claim ledger、逐句 donor influence ledger。每段可回原帖/视频说话人/时间戳。任意稿件必须完整反查：来源→语料→定量画像→实际检索→研究决策→每句依据→评估。

指标：真人盲测 persona 识别率、事实完整率/source fidelity、引用准确率、稿件跨 persona 语义重合度、与任一原源句子/n-gram/语义重合度、generic AI structure、真人修改量/时间。随机盲评，答卷/answer key 分离；ID 命中率不代替 entailment；同模型自评分不能当真人；失败计入分母，不能只报告成功稿。

双向 CN→EN、EN→CN 必须使用真实来源、补受众背景、检查信息差/框架迁移，保留数字/单位/归属/hedge/时间；至少一组真人盲测与修改记录；韩文等扩展目标不被交接取消。

## D. 视频和两个真实主题

- 至少 3 YouTube + 3 Bilibili 金融长视频、相关 KOL 真实帖子、1 当前真实热点、1 evergreen 主题；不用 fixture/模拟结果验收。
- human_caption 优先、auto_caption 兜底、无字幕 ASR；完整 metadata/raw/transcript/cues/segments 永久保存；说话人/置信度、金融术语/公司/ticker/数字/日期校正、事实/观点/推理/预测/案例/原则/广告/闲聊分类；所有观点有 timestamp URL。不能一小时先缩成几百字再只“蒸馏”摘要。
- 用重复上传真实例验证标题/音频/transcript 跨平台去重，保留双方来源；视频主要更新 Knowledge/Reasoning/Framework/Prediction/Evergreen。
- 热点：同一事件≥5 KOL 真观点、≥2 带时间戳视频 segment、≥1 权威事实；展示 consensus/divergence/originator/amplifier、立场变化、CN/EN 差；3 persona 独立成稿，各段来源/influence 与原源重合检查。
- Evergreen：≥10 条真实来源提取 Atomic Trading Principles；语义去重、适用市场/周期/regime/条件、执行/失效/误用/反例、原源/时间戳、冲突互补/历史当前案例；≥3 种不同内容形态；一次当前情境触发历史原则 resurfacing 完整回放。

## E. 自动化、产品与视觉

- source sync→pagination/backfill→normalize→重构关系→分类去重→画像→event/narrative→机会评分→路由→独立研究→稿件/视觉→QA→review→update。有定时或事件触发，不靠用户依次点击。每 run ID、start/end、处理数、失败来源、重试状态、输入/产物版本。
- 实际新事件、一个未来 scheduled catalyst、一个 KOL 主题变化、一次新证据影响旧稿/旧图→V2/V3，保留人工改动与版本差异；planned/breaking/evergreen 生命周期不同。实时/每日/每周/月画像与来源质量更新职责保留。
- Intelligence Desk 首页：今日变化、加速主题/KOL 数、共识分歧/最早源/传播、CN/EN 差、视频增量、未来 7 天催化、机会队列、推荐 persona 理由、待审/更新数、freshness/失败；数据缺失不生成假叙事。
- Opportunity 详情完整事实、Claim Graph、原帖/视频时间戳、立场变化、权威证据、组合计划、persona 为什么不同。语料/debug 为二级。
- Persona Lab 滑杆/标签/donor组合器；自然区间、n、post IDs 同屏，三个 persona 同事件真实预览；JSON 仅高级设置。
- Visual Profile 与 Visual Grammar 量化可解释。至少真实数据可复现图、官方来源截图/原图页码、可编辑产业/事件结构图；正文图表共享事实，新数据实际重算；不只换颜色，不强制配图。
- Visual Package 包含图、不同尺寸、可编辑 Chart/Diagram Spec、原数据/出处/页码、caption/署名/alt text、正文绑定、persona/语言/版本/有效期/更新条件、权限和人工审核。检查轴/单位/数字一致、日期、溢出、中文可读性、来源、重复、旧图失效。
- 不用生图生成精确金融数据、伪造新闻/人物背书、删水印、误裁来源、公开群成员身份。实际运营/发帖仍不在范围。
- 最终演示是一个真实新事件自动采集→识别→机会卡→三个独立计划/稿/不同视觉→QA→待审→加入真实新证据自动更新。不能用 hardcoded event/static arrays/预写稿掩盖任一阶段；未自动的阶段明确标注。

## 本次核验的边界

verify_handover 的 8 个安全测试验证真实文件 hash、raw-clean 关联、profile IDs、检索时间、caption hash/链接、模型请求记录和旧稿清单。通过这些只能说明交接材料完整性；不证明内容正确性、人格化效果、端到端自动化或前端可用。当前产品验收预期 FAIL/UNKNOWN 必须真实报告。
''')
put('docs/RUNBOOK.md',r'''
# 运行手册

当前为交接冻结；本轮只执行只读核验和迁移。下面含历史已执行命令和未来恢复命令，**不是要求接手立即运行整表**。除“安全核验”外，其余操作先等用户恢复实施。`python` 一律指本项目 `.venv/bin/python`，不使用系统 3.14 替代。

```sh
cd /Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation
```

## 已保留环境

Python 3.12.14；macOS Apple Silicon，本机内存限制不适合同时跑 MLX LLM、ASR、多个模型。mlx 0.32.2、mlx-lm 0.31.3、FastAPI 0.141.1、uvicorn 0.52.4、sentence-transformers 6.0.1、scikit-learn 1.9.0、torch 2.14.0、numpy 2.5.2、mlx-whisper 0.4.3；精确全量依赖见 handover/requirements.freeze.txt 与 runtime-versions.json。旧 requirements.versions.txt 不包含后来 ASR 全部依赖，不当最新锁。

ffmpeg `/opt/homebrew/bin/ffmpeg`；yt-dlp `/Users/fionama/.local/bin/yt-dlp`；字幕 JS runtime 在 `/Users/fionama/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`。它们属本机外部依赖，没有把全局软件移入工程。官方三个全局 skills 同理；项目六个 .agents/skills 已迁移。

旧根路径兼容链接保留，确保 venv console shebang 和日志/锁里历史绝对路径仍可解析。新根 `.venv/bin/python -B handover/test_invariants.py` 已执行成功。不承诺此 venv 可直接复制到 Linux 或另一台 Mac。

## 凭证名称（只检查存在，不打印值）

| 名称 | 用途/当前限制 |
|---|---|
| XQUIK_API_KEY | 唯一选定的新 X 采集 API；没有已运行采集/成本估计 |
| RAPIDAPI_KEY | 原工程授权 RapidAPI；只能使用已授权范围，不能当 Xquik key |
| APIFY_API_TOKEN | 历史导入来自 Apify；当前不混跑新的 X 采集器 |
| SEC_EDGAR_USER_AGENT | SEC 真实联系方式/User-Agent；MCP 当前禁用，不虚构身份 |
| HF_TOKEN | 公共模型下载不需要；已有工具使用 token=False/禁隐式凭证 |
| OPENAI_API_KEY / GROQ_API_KEY | 当前本地 LLM/ASR 不使用；不能自动付费兜底 |

存在性报告只针对当前进程环境，不表示 `.env` 没有 key。用户允许读取的 RapidAPI env 在原 Finance_Stocks_KOL 工程；交接不打开、不复制、更不迁移它。运行时按授权安全注入值，禁止将值写进 prompt、命令回显、代码或交接。

## 安全核验（现在可运行）

```sh
sh scripts/verify_handover.sh
.venv/bin/python -B handover/test_invariants.py
```

两者无外网、无付费、无数据修改；第一条唯一写入 handover/verification.json，第二条不写文件。SQLite mode=ro，不 import backend；前者再次全量校验迁移前 hash。exit 0=检查到的门槛全部通过，1=交接完整性失败，2=完整性通过但产品验收仍 FAIL/UNKNOWN，3=核验程序异常。Git 未初始化记录 UNKNOWN/null，不造 branch 或 clean 状态。

不要运行 scripts/validate_slice.py 作为“安全单元测试”：它 import app、发本地 POST、保存 diagram/报告；当前旧生成断言也不符合新标准。

## 恢复运行命令表

| 命令（项目根执行） | 外部 API/费用 | 写入及输入→输出 | 执行证据/限制 |
|---|---|---|---|
| `.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680` | 无外网/0 API费 | 读 corpus/personas/SQLite；app 可能建表，后续 POST 会写 DB | 迁移前真实运行；迁移时已停止，迁移后未启动 |
| 在现有 Chrome 打开 `http://127.0.0.1:8680` | localhost/0 | 前端同源由后端提供，无 npm dev server | 旧 UI，未完成新 evidence_loop 展示；不要改用 ambient IAB |
| `.venv/bin/python scripts/start_local.py` | 本地模型/0 API费 | 启动模型+后端，写 runs/start-*.log | 先前启动成功；会占内存，交接期不运行。默认 modern :8683，seed/temp 在 client |
| `.venv/bin/python scripts/import_corpus.py` | 无新 API/0 | 读原外部工程 5 snapshot →备份旧 import后重写 raw/clean/manifest，append ledger | 已运行 6 次。当前冻结不可重跑；缺外部输入则不可移植复现 |
| `.venv/bin/python scripts/audit_promotions.py` | 无/0 | 读 clean→推广检查报告 | 历史执行；会重写旧报告，不在交接运行 |
| `.venv/bin/python evidence_loop/import_sources.py` | 无/0 | 只读原 Excel 允许列→catalog | 已执行；不读主观评价，目标文件会重写 |
| `.venv/bin/python evidence_loop/discover_video.py` | YouTube/Bili 公共接口；无显式API费 | 固定 seeds/search→discovery响应/log | 已执行；不是持续发现；重跑覆盖部分日志 |
| `.venv/bin/python evidence_loop/acquire_video.py` | 公共视频 metadata/字幕；无显式API费 | 已选视频→info/VTT/acquisition | 已执行，存在 429/无字幕；先改 append-only 再复跑 |
| `.venv/bin/python evidence_loop/acquire_audio.py` | 公共视频音频；无显式API费 | metadata→m4a/WAV/audio-runs | 已执行：Bili 3 成功，YT 4 失败；不要掩盖403或取Cookie绕过 |
| `.venv/bin/python evidence_loop/transcript_pipeline.py` | 无外网；0 | 现有 VTT→cues/全文/segments/index | 已执行：3 YT/149 segments；会重写版本，后续先版本化 |
| `.venv/bin/python evidence_loop/transcript_pipeline.py --asr` | 设计为本地ASR/说话人，权重已在本地；无付费API | 音频→ASR/diarization与分段，GPU/CPU开销 | 从未运行，未知运行错误；当前4个YT缺audio，先补按视频失败隔离/跳过，不能直接宣称此命令可完成6视频 |
| `.venv/bin/python scripts/fetch_primary.py` | BLS 公共网页；0显式费 | 网络→data/evidence；错误记ledger | 曾3失败；不是完整表格抽取器 |
| `.venv/bin/python scripts/finance_supplement.py` | Yahoo/NVDA；0显式费，不保证商业授权 | NVDA历史/预期→finance_supplement和ledger | 真实3 operation成功；不能替代IR/SEC/电话会 |
| `.venv/bin/python evidence_loop/build_event.py` | 不联网/0 | 现有 BLS 全文→51fact/616block packet | 已执行；固定月份措辞、表格/时间 bug，重跑前修复并新版本 |
| `.venv/bin/python scripts/run_ml.py` | 禁网本地embedding/传统模型/0 | raw/clean→A/B/聚类/旧profile/CSV/Trackio | 真实执行；会重写当前指标甚至人工标注CSV，恢复前保护标注与输出版本 |
| `.venv/bin/python scripts/classify_comparison.py` | 本地模型 :8682/0 | 真实帖子→LLM分类请求/预测指标 | 历史已执行；新模型服务需对应启动，不能同时挤占全部内存 |
| `.venv/bin/python evidence_loop/build_profiles.py` | 本地规则/像素与现有标注/0 | clean/reading-notes/images→5轴profiles/versions | 已执行；当前不消费视频，不是端到端蒸馏 |
| `.venv/bin/python evidence_loop/prepare_experiments.py` | 本地embedding/0 | facts+profiles+固定cache→routing/retrieval/protocol | 已执行；会覆盖 protocol、需修hash绑定/时间泄漏，新建run不能覆盖失败 |
| `.venv/bin/python evidence_loop/run_experiments.py` | 本地 :8683/0API费 | 同事实/协议→plans/drafts/cases/model_calls | 实际3失败1中断，未完成；现有 main 对已存在失败/中断格直接跳过，不会自动重试；恢复后先修复并新protocol/run |
| `.venv/bin/python -m json.tool ml_experiments/A_finance_classification.json` | 无/0 | 读→stdout | 可查看真实银标指标，非真人质量 |
| `.venv/bin/python -m json.tool handover/verification.json` | 无/0 | 读最新核验→stdout | 当前验收事实入口 |

### 新 X 真实采集

当前**没有已实现、已运行的新 Xquik timeline/backfill CLI**，不能编造一个命令。审计和 API endpoint 文档位于 `.agents/skills/x-twitter-scraper/references/`，代码/网络/凭证/成本审计见 skill-audit。恢复后先在同一选定方案内做真实分页与费用估计、持久 cursor/运行账本，再在已授权预算内运行；不得改用另一套 X collector 来制造“通过”。Phase 0 RapidAPI probe 只有 6 请求，不能重跑它充当 backfill。

### 重建依赖/模型（本次未运行）

本机完整 venv 和模型已经迁移，不需要下载安装。另一台同架构环境可用下列命令新建隔离环境，不能覆盖现有 `.venv`：

```sh
python3.12 -m venv .venv-rebuild
.venv-rebuild/bin/python -m pip install --no-cache-dir -r handover/requirements.freeze.txt
```

外网 PyPI，可能下载较大 wheel、写新环境；无显式付费 API。此完整版本集合来自实际 importlib.metadata，不是经全新机器安装验证的可移植 lock；部分 macOS/MLX wheel 平台限定。原 venv 无 pip 模块，不要在其中直接 `python -m pip` 假设可用。

模型精确 revision/file hashes：model-lock.json、comparison-model-lock.json、modern-model-lock.json、transcripts/audio-model-lock.json。已有 prepare_* 脚本会查询当时远端 latest，再下载并覆盖锁，不是对旧 revision 的复现命令；当前不要重跑。恢复迁移到新机器时用已有 lock 的 repo+revision 定向下载、核对 hash，禁 trust_remote_code/隐式token。下载有带宽/磁盘成本，不能误称无成本。

## 导出与交付

本次完整本地项目目录就是可接手包。只导出交接文档（不含 raw 媒体响应、凭证、模型）可执行：

```sh
tar -czf handover-review.tar.gz CLAUDE.md docs handover
```

此命令无 API/0 API费，写项目根的新归档；未在交接运行。完整项目已在本地迁移，未上传或部署。

**当前没有合格内容可导出给运营。** backend `/api/export/{rid}?audit=true` 仍能打包旧稿，仅供失败审计。恢复服务后验证隔离旁路的只读请求示例：

```sh
curl --fail 'http://127.0.0.1:8680/api/drafts/draft-45b14189a954?audit=true'
```

无外部 API/0费，不写数据；迁移后未执行。不能把该响应/旧 ZIP 当有效内容。等新完整 source/donor/plan/draft/ledger/QA/human review 合格后再实现正式 Content Package 导出（正文、数据、图片/spec、来源、图注/alt、版本、失效条件）。
''')
manifest={'generated_at':s['generated_at'],'repository_root':str(R),'branch':s['git']['branch'],'commit_sha':s['git']['commit_sha'],'dirty_files':s['git']['dirty_files'],'is_git_repository':s['git']['is_repository'],'runtime_versions':s['runtime_versions'],'dataset_counts':{'raw':s['dataset']['raw'],'clean':s['dataset']['clean'],'video_segments':s['videos']['segments']},'author_counts':s['dataset']['authors'],'language_counts':s['dataset']['clean_languages'],'platform_counts':s['dataset']['platform_counts'],'real_vs_fixture_counts':s['dataset']['real_vs_fixture'],'draft_counts':s['drafts'],'valid_draft_count':s['drafts']['valid'],'legacy_invalid_count':s['drafts']['legacy_invalid'],'human_review_count':s['drafts']['human_reviews'],'human_label_count':s['dataset']['human_label_rows'],'actual_api_call_evidence':s['api'],'test_commands_results':[{'command':'sh scripts/verify_handover.sh','exit_code':None,'result':'pending actual execution'},{'command':'.venv/bin/python -B handover/test_invariants.py','exit_code':0,'tests_run':8,'result':'passed on migrated root; repeated inside final verification'}],'unresolved_blockers':['Donor per-author original-content/language/history coverage incomplete; missing collection provenance','No human annotations or reviews','Full table/fact semantic audit incomplete; three plan JSON truncations and one interrupted case; zero valid new baseline','Legacy isolation has route and old-tool bypasses; quarantine script not idempotent','Bilibili ASR/diarization/financial correction and actual cross-platform dedup unexecuted','No executed hot Claim Graph/Evergreen/conflict/resurfacing pipeline','No autonomous opportunity/update pipeline or new frontend integration','Xquik credentials and reviewed cost estimate unavailable; SEC MCP disabled','Historical acquisition retry logs partially overwritten; total wire requests unknown'],'next_recommended_actions':['Verify frozen handover and migration; keep all old failures isolated; wait for user to resume implementation','Then repair legacy route isolation, full fact closure and one traceable valid generation before new same-evidence five-group experiments','Complete real donor/human/video coverage, hot+evergreen update replay and corresponding Intelligence Desk audit views without relaxing acceptance'],'migration_evidence':'handover/migration.json','freeze_evidence':'handover/freeze.json','verification_evidence':'handover/verification.json','product_acceptance':'not_passed','content_generation_paused':True,'user_input_files_modified':False,'push_deploy_publish_performed':False}
put('handover/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
print('Created failures, acceptance, runbook and manifest. No business code/data changed.')
