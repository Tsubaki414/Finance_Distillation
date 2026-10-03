# CLAUDE_AUDIT — 独立取证审计（Phase 0）

审计人：Claude Code 接手方。审计时间：2026-09-06。
根目录：`/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`，非 Git 仓库（`git rev-parse` 返回 fatal），branch/commit/dirty_files 均为 null。

## 0. 本次审计的方法与边界

本文件不采信 `docs/` 下任何交接文档、README、文件名或页面数字。所有结论来自：直接读 JSONL/JSON、以 `mode=ro` 读 SQLite、读源码、统计 `runs/model_calls` 原始请求响应、解压只读检查 ZIP/XLSX。

审计期间**未执行**：任何采集、任何生成、任何付费 API、任何写入业务文件、任何重跑会覆盖失败记录的脚本、任何服务启动。唯一执行的既有脚本是 `sh scripts/verify_handover.sh`（其自述只写 `handover/verification.json`）。本文件与 `handover/` 下同名结论冲突时，以本文件的实测证据为准。

**总体结论**：前一位 Agent 的交接文档在诚实度上远高于预期。我逐项复核后，**没有发现任何一处把未达成的能力说成已达成**；偏差全部是另一个方向 —— 若干处**把问题的严重程度说轻了**，另有几块产品范围**整块未提及**（见 §3.1、§3.3、§3.8、§3.9）。我自己在 §3.2 上先出过一次错误判定，已在该节更正并保留过程。

真实状态是：一个高质量的单事件事实包 + 一份真实但规模不足的 X 语料 + 一套设计合理却从未跑通的实验框架；**没有 pipeline，没有有效稿件，没有传播图谱，没有 evergreen 层**。

## 1. 核验脚本实测输出

```
DATA raw=2647 clean=1825 authors=12 human_labels=0
CLEAN_LANGUAGES {"en": 510, "et": 1, "ja": 10, "zh": 1304}
DRAFTS valid=0 legacy_invalid=45 human_reviews=0
VIDEO_READY {"youtube": 3} segments=149
MODEL_CALL_RECORDS {"completed": 722, "failed": 2, "started": 3}
ENV_PRESENT 全部 false（7 个 key 均未注入当前进程）
COUNTS {"FAIL": 8, "PASS": 7, "UNKNOWN": 3}   EXIT_CODE 2
```

以上每一项我都独立复算过，数字全部对得上。

## 2. Claim vs Evidence Matrix（独立复核）

状态词沿用交接约定。"复核"列写我的独立结论，与交接自述不同处标 **⚠**。

| 能力声明 | 我的判定 | 关键证据（我实测） | 复核 |
|---|---|---|---|
| X/KOL 真实采集 | partial | 2647 raw 真实 provider 记录，12 作者，字段齐整；新请求 0 | 与自述一致。是历史文件导入，不是本轮采集 |
| 翻页/回填/定期更新 | not_implemented | 无游标、无调度器；`collected_at` 缺失 2527/2647（95.5%） | 一致 |
| 引用/回复/传播关系 | **not_implemented（数据层不可建）** | 1510 帖有 `quoted_post`，仅 98 个知道被引作者；1219 个被引 post_id 只有 672 在库内。52 条 `reply_to` 的 `post_id` **全为 null**，可解析父帖 0。`thread_id` 2647 帖有 2502 个不同值，>1 帖的 thread 仅 103 个 | **⚠ 交接文档仅说"不证明完整"，实测是根本无法建。见 §3.1** |
| YouTube/Bilibili 字幕 | partial | 3 YT `transcript_ready`（均 auto_caption），149 segments；3 Bili 仅 metadata + 音频，transcript 0；`speaker_status: not_run` | 一致 |
| 财报/权威来源 | **partial（但这是全库最强资产）** | BLS packet 51 typed facts，每条带 `source_span` 精确字符偏移 + `source_block_ids`，616 blocks，39 页全文保留，`methodology` 写明 CES/CPS 不可相减 | 一致，且质量被交接文档低估 |
| 清洗/去广告/去重 | partial | `text_processing.excluded_spans` 真实记录赞助商尾巴并保留原文；同作者精确去重真实 | 一致。跨作者语义去重缺失 |
| 五轴 donor profile | partial | 12 个有样本 donor 的 871 个特征，**全部带 `denominator_post_ids` + `support_post_ids`**（871/871）；另 46 个 `candidate_no_real_posts` 空壳 | 溯源硬指标**已达标**。缺陷在自然区间口径，见 §3.2 |
| ML 分类实验 | **broken（方法循环）** | rules macro-F1 = **1.000**，因为参照标签就是规则自己的输出（`training_labels: rules-v2 weak labels`） | **⚠ 见 §3.6** |
| ML 作者归因 | partial（真实可信） | 6 作者、within-author 时间切分、清除整线程与完全重复，combined macro-F1 0.7595 | 一致。这是全库方法论最扎实的实验 |
| multi-donor 检索组合 | **broken（组合无区分度）** | 三个 persona 的首选 donor **都是 qinbafrank**；language/knowledge 角色权重全部约 0.33 均匀 | **⚠ 见 §3.3** |
| 实际 LLM 调用 | verified_working | 727 个 attempt 文件，722 完成，全部本地 MLX，含完整 prompt/temperature/seed/usage | 一致 |
| 独立分析计划 | broken | 4/15 格被尝试：3 格 `JSONDecodeError`，1 格冻结在 `running`。有效新稿 0 | 一致，根因见 §3.5 |
| 逐句引用 / donor influence | broken | 新 case 无 `sentence_to_source_ledger`；代码写好了但从未执行到 | 一致（`lineage broken` 属实） |
| 跨语言蒸馏 | broken | 旧稿基于 4-fact 摘要；韩文全库 **1 条**帖 | 一致，韩文缺口见 §3.7 |
| 热点/叙事/首发传播 | not_implemented | 无 Claim Card、无 Event Graph 执行产物 | 一致，且受 §3.1 数据层阻断 |
| Evergreen / 交易原则 | **not_implemented（且原料从未接入）** | `Reads 2.zip` 467MB / 286 MD / 42 PDF，全库 grep **零引用** | **⚠ 见 §3.8** |
| 图片与图表 | partial | `chart_svg()` 只对 `id` 以 `payroll` 开头的 fact 画图，其余事件必空图 | 一致，硬编码程度比自述更严重 |
| 前后端连接 | partial | 前端仍是 4 页（corpus/persona/studio/handoff）；后端 persona 白名单 `['macro','industry','risk']`，新协议用 `trading` | **⚠ 前后端与 evidence_loop 是两套互不相通的系统，见 §3.4** |
| 自动化 pipeline | not_implemented | `start_local.py` 只起服务；`main()` 是顺序批处理 | 一致 |
| 评测 / 真人审核 | **broken（接口不可用）** | `/api/blind` 在 app.py:224 无条件 return，225–235 行**死代码**；且 `blind-cases.json` 不存在 → 恒返回空 → `/api/blind-review` 恒 422 | **⚠ 见 §3.9。不是"0 人提交"，是提交不进去** |

## 3. 交接文档未写或低估的发现

### 3.1 传播层没有数据底座（最严重）

产品一级要求是首页回答"谁最早提出／谁在传播／共识与分歧"。实测：

- `reply_to` 存在于 52 帖，**`post_id` 全为 null**，只有 handle/user_id → 可解析回复父帖 **0 条**。
- `quoted_post` 只存 `{post_id, author:null}`，**被引作者 98/1510 已知**，被引正文**一条都没抓**。
- `thread_id` 实为逐帖 ID（2502 个值 / 2647 帖），不是会话分组。

结论：originator/amplifier、叙事加速、共识分歧、跨语言首发对比，**当前语料无论写多少代码都算不出来**。这不是"未实现"，是采集契约本身缺字段。任何新采集必须把"抓取被引/被回复的父帖正文与作者"写进硬性字段要求，否则整条 Hot Signal 内容线不成立。

### 3.2 特征溯源已达标；缺陷在自然区间口径

**本节的初版结论是错的，此处更正。** 我最初按字面查找 `post_ids` 键，得到"871 个特征全为 null"，并据此判定 CLAUDE.md 的溯源硬指标未达成。实际字段名是 `denominator_post_ids`（该特征的分母帖集合）与 `support_post_ids`（命中该特征的帖子），**871/871 个特征两个字段都完整存在**，且 `handover/test_invariants.py:28-36` 有断言校验 `support ⊆ denominator ⊆ clean` 且 `sample_n == len(denominator)`。溯源要求**已达标**，交接文档在这一点上表述准确。

真实缺陷是另一处：`natural_range` 对二值特征无意义。`knowledge.macro` / `reasoning.causal_cue` 这类是逐帖 0/1 指示量，其 p10/p50/p90 恒为 0/0/1。Persona Lab 若照此渲染"自然区间"滑杆，知识与推理两轴会全是无信息刻度 —— 这些轴需要改用 bootstrap 置信区间或跨 donor 分位数，而不是逐帖分位数。

同时成立的限制（交接文档已承认，我复核属实）：knowledge/reasoning 轴是**正则词频**，`method` 字段自己写明"Explicit surface reasoning cue, not a proof of reasoning quality"。它可以作为可审计的表层观测，但不能被称为已验证的知识能力或推理习惯。

### 3.3 三个 persona 的 donor 组合几乎相同

`experiments/routing.json`：macro / industry / trading 的**首选 donor 全部是 qinbafrank**；language 角色权重 macro 为 0.340/0.339/0.321，knowledge 为 0.377/0.337/0.286 —— 接近均匀。权重是人工公式产物，非学得。

即便把 12 格补跑完，`multi_donor_separated` 与 `structured_profile` 的差异也极可能落在噪声内，因为三个 persona 拿到的是**几乎同一批 donor、几乎同一组权重**。消融实验在这种配置下无法证伪任何假设。donor 选择公式必须先改成带互补性/去冗余约束，再谈五组消融。

补充事实核正：`post_type=quote` 的 `text` 字段确实是 donor 本人的原创评论（我逐条读过 18 个检索样本），所以"1825 clean 里只有 708 original"**不能**解读为"只有 708 条是本人写的"。真正的问题不是原创度，而是 §3.1 的被引对象缺失。

### 3.4 后端与 evidence_loop 是两套系统

- 后端 `persona()` 白名单写死 `['macro','industry','risk']`（app.py:33），新协议第三人设叫 `trading` → 后端无法加载新人设。
- 后端 `context()` 的"检索"是：按硬编码正则 `就业|非农|宏观|利率|流动性` 过滤，然后取**时间最早**的一条（app.py:98–100）。既不是 embedding 检索，也与事件无关。真正的 embedding 检索只存在于 `evidence_loop/prepare_experiments.py`，**从未接入后端或前端**。
- 前端 4 页读的是 `knowledge_profiles/` 等旧目录，`evidence_loop/profiles/` 的五轴新画像**没有任何 UI 路由**。

所以"前后端连接"为真，但连的是旧系统；新证据环的全部产物在 UI 上不可见。

### 3.5 三格失败的根因是一个 token 预算常量

`evidence_loop/run_experiments.py:33` 给 plan 调用 `650`，给 draft 调用 `2400`。实测 model_calls：

```
local-a1ec004c02684efa  plan  max_tokens=650  finish=length  out=650  → JSON 截断
local-c0e9e6ecc18e4adb  plan  max_tokens=650  finish=length  out=650  → JSON 截断
local-fe12c820ba964ad9  plan  max_tokens=650  finish=length  out=650  → JSON 截断
local-e34f0c6259364bd3  plan  max_tokens=650  finish=stop    out=532  → 解析成功
```

三次失败精确卡在 650/650。且 plan 调用**没有重试或修复循环**（旧 `guarded.py` 反而有）。这是单行常量问题，不是设计缺陷 —— 但**修好它只解决"能跑完"，解决不了 §3.3 的"跑完也无区分度"**。

另：`material()` 在 `base_model` 模式下不注入 persona，因此三个 base 格的输入包**逐字节相同**，三格恒等。protocol 的 `base_control` 已声明这是有意设计，但意味着 15 格里实际只有 13 个独立观测。

### 3.6 分类实验是循环论证

`ml_experiments/A_finance_classification.json`：`reference` 为严格规则复核行，`training_labels` 为 `rules-v2 weak labels`，而 rules 得分 accuracy/precision/recall/F1 **全为 1.000**。规则在用自己的输出给自己打分。该 1.0 会经 `/api/status` → `ml_experiments/run_summary.json` 进入前端。文档里承认了局限，但指标本身仍在对外供给。实验 A 必须用真人金标重做，否则不能进入任何验收陈述。

### 3.7 韩文实质为零

全库 2647 raw 中 `language == "ko"` 的帖子 **1 条**；transcript segment 的 language 全为 null。韩文在 v2 任务书中是一等语言（schema/路由/评测/缺口状态），当前连 schema 位都靠 language 自由字符串字段兜着，没有任何韩文 donor、样本或审阅能力。

### 3.8 Reads 2.zip 从未被任何代码读取

467MB、286 个 Markdown、42 个 PDF、总解压 467MB。在 `scripts/`、`evidence_loop/`、`data/` 中 grep "Reads" **零命中**。这意味着 Evergreen Trading Principles 与 Knowledge Products（"交易心法合集"）两条内容线，**既无实现也无原料接入**。这是被交接文档完全跳过的一整块产品范围。

### 3.9 真人评审接口物理上无法接收提交

`backend/app.py:224` 是无条件 `return`，其后 225–235 行为**不可达死代码**（原本的合格稿筛选与跨语言样本装配逻辑全在死代码里）。且它要读的 `evidence_loop/experiments/blind-cases.json` **不存在**。因此 `/api/blind` 恒返回 `{'cases': []}`，`/api/blind-review` 的 case_id 校验必然失败并抛 422。"0 条真人审核"的真实原因是**通道断了**，不是没人来审。

### 3.10 旧 45 篇无效的根因已实测确认

抽查 `generated_samples/draft-00e6e3e62d80.json`：`facts` 只有 4 条（`payroll_2026_06/07/08` + `unemployment`）。对照新 packet 的 51 条 typed facts —— 工资、参与率、兼职、行业贡献、历史均值、修订**在旧证据快照里根本不存在**。所以旧稿"遗漏 BLS 关键指标"不是模型问题，是**证据包只有 4 个数字**。这条根因交接文档描述正确，我实测确认。

### 3.11 遗留稿件隔离的旁路是具体的

`get(rid)` 无 kind 过滤（app.py:26–29），因此以下路由可直接触达 45 个 `legacy_invalid_output` ID：
`/api/chart/{rid}.svg`、`/api/diagram/{rid}`、`/api/diagram-image/{rid}.svg`、`/api/editorial-reviews/{rid}`、`/api/export/{rid}?audit=true`、`/api/drafts/{rid}?audit=true`。
`/api/drafts` 与 `/api/export` 已加 audit 门禁，但 chart/diagram/editorial-reviews **完全没有门禁**。

## 4. 真实数据规模（逐作者，实测）

`original` 与 `quote` 均为该 donor 本人撰写的正文；`quote` 仅表示该帖同时引用了另一条帖子。

| donor | clean | original | quote | 时间跨度 |
|---|---:|---:|---:|---|
| aleabitoreddit | 404 | 240 | 164 | 06-07 → 09-05 |
| PhyrexNi | 357 | 13 | 344 | 07-22 → 09-05 |
| Michael_QQQ2025 | 338 | 182 | 156 | 06-08 → 09-04 |
| qinbafrank | 312 | 12 | 300 | 07-01 → 09-05 |
| kovainvest | 226 | 99 | 127 | 06-07 → 09-03 |
| xingpt | 149 | 131 | 18 | 06-09 → 09-05 |
| Beth_Kindig | 18 | 15 | 3 | 08-30 → 09-05 |
| GlobalMktObserv | 10 | 7 | 0 | 09-04 → 09-05 |
| TradexWhisperer | 4 | 3 | 1 | 09-05 |
| ericjackson | 3 | 3 | 0 | 09-04 → 09-05 |
| RJCcapital | 3 | 2 | 0 | 08-19 → 08-30 |
| citrini | 1 | 1 | 0 | 09-04 |

6 个英文种子只有 20 条 raw 上限的探测量级。达到 Gate B「每人 150 条」的仅 5 人（4 中文 / 1 英文）。**没有任何一个 donor 的 180 天窗口是完整的**。

候选池方面：`Mango_Finance_KOL_and_Institution_List.xlsx` 含 101 个非机构账号（53 Creator Approve）、47 个机构（30 Approve）、12 个 Proxy Root。`evidence_loop/profiles/` 里 46 个 `candidate_no_real_posts` 空壳即来自此。候选充足，采集能力缺失。

## 5. 五大技术风险

1. **传播关系字段缺失（§3.1）** —— 阻断 Hot Signal 全线。必须在恢复采集**之前**改采集契约，否则会再攒一批同样不可用的数据。
2. **donor 选择无互补性约束（§3.3）** —— 五组消融即使跑完也无法证伪，等于白烧一轮实验预算。
3. **两套并行系统（§3.4）** —— 后端/前端与 evidence_loop 各有一套 persona、检索、画像。继续在任一侧加功能都会加深分裂。
4. **银标循环污染指标（§3.6）** —— 1.0 的 F1 已进入 API 供给链，任何基于它的验收陈述都是无效的。
5. **回顾性画像泄漏** —— profile 用全语料（含事件后帖子）构建，而 retrieval 已做时间过滤。两者时间基准不一致，消融结果会被 point-in-time 泄漏污染（`prepare_experiments.py` 还固定了 embedding cache 文件名，不强校验当前 dataset hash）。

## 6. 五大产品风险

1. **首页方向错误** —— 现有 4 页以 corpus/ETL 为入口，与"Intelligence Desk 优先"直接冲突；且 Desk 需要的传播/共识数据不存在（§3.1），不能先做壳子。
2. **Evergreen 与知识产品整块缺失（§3.8）** —— 467MB 冷知识原料从未接入，"交易心法合集"这一明确商业诉求零进度。
3. **韩文被永久搁置的风险（§3.7）** —— 目前连"缺口状态"都没在 schema 里显式表达。
4. **视觉层单一** —— `chart_svg` 只能画 payroll，`event_diagram` 固定取 `REGISTRY['scheduled'][:1]`。视觉语法、persona 视觉差异、更新闭环均无。
5. **真人反馈闭环断裂（§3.9）** —— 编辑接受率、修改量、盲测这些**唯一能证伪内容质量**的指标，当前物理上收不上来。

## 7. 建议保留 / 重做

**保留（有真实价值，勿推倒）**
- `evidence_loop/sources/` 的事实包构建：51 typed facts + 精确字符 span + 616 blocks + methodology 警示，是全库最强资产，直接作为 Fact 层标准。
- `evidence_loop/run_experiments.py` 的双 ledger 设计（逐句 fact_ids + donor_ids + 声明用途 + 实际输入 trace + 文本重合），设计正确，只是从未跑通。
- `ml_experiments/B_authorship.json` 的作者归因实验（时间切分 + 线程去重），方法可信，可作为 style profile 是否有效的判据。
- `scripts/model_client.py` 的调用留痕（每次调用独立 JSON，含 prompt/seed/usage/finish_reason）。
- `import_corpus.py` 的 `text_processing.excluded_spans`（保留原文的前提下标注商业片段）。
- 全部失败记录、45 篇无效稿、quarantine registry —— 按 CLAUDE.md 保持原样。

**重做**
- 采集契约（必须含被引/被回复父帖正文与作者）。
- donor 选择与角色权重公式（引入互补性与冗余惩罚）。
- 实验 A 分类（换真人金标）。
- 后端 persona/检索/画像三处，与 evidence_loop 合并为单一实现。
- `/api/blind` 死代码与 blind-cases 装配。
- `chart_svg` / `event_diagram` 改为由事实类型驱动的视觉语法。

**暂不启动**
- LoRA/SFT（v2 任务书与 CLAUDE.md 均要求先证明瓶颈）。
- 新 UI 美化（CLAUDE.md：后端证据闭环完成前不美化 UI）。
- SEC EDGAR MCP（禁用中，需真实 User-Agent 身份）。

## 8. 最小真实 vertical slice 提案（待确认，尚未执行）

目标不是补完 15 格，而是**先让一格产生可审核的内容资产，同时验证最关键的那个假设**。

建议顺序（每步都同时交付「用户能看的内容」与「可复现的验证」）：

- **S0 修复隔离与通道**（不涉及生成）：给 `get(rid)` 加 kind 门禁并覆盖 chart/diagram/editorial-reviews；修 `/api/blind` 死代码。产出：可复跑的隔离回归测试。
- **S1 单格跑通**：仅修 plan 的 token 预算 + 加一次 JSON 修复重试，跑 `structured_profile × macro` 一格。**新建 case，不覆盖任何既有失败记录**。产出：第一份带逐句 evidence ledger 与 donor influence ledger 的稿件。
- **S2 donor 互补性修正**：在跑满 12 格之前，先用现有 embedding 做 donor 冗余/互补分析，改掉"三 persona 同一首选 donor"。产出：新 routing + 变更理由。
- **S3 补齐 5×3 消融**：同一事实包、同模型设置，跑满 13 个独立格 + donor removal/role swap 各一次。产出：五组对照 + 消融证据。
- **S4 真人盲评**：把 S3 产物送进修好的盲评通道，收 ≥1 轮真人标签与编辑量。产出：第一批非自评质量证据。

采集与视频（Bilibili ASR、说话人分离、传播字段回补）建议**在 S1 产出可审核稿件之后**再启动，因为它们成本高且当前无法验证价值。

## 9. 需要你决定的事项

1. **是否授权修改 `evidence_loop/run_experiments.py` 的 token 预算并新建 case 重跑一格。** 我不会覆盖既有 4 个 case 文件，但这属于"恢复实施"，CLAUDE.md 要求你明确指令。
2. **传播字段回补的代价。** 补齐被引父帖意味着对 1219 个 post_id 发起新采集，而 Xquik 无 key、无成本估计。要么授权配 key 并给出预算上限，要么接受 Hot Signal 内容线在本阶段降级为"无首发/传播分析"。
3. **Reads 2.zip 是否现在接入。** 它是 Evergreen 与知识产品的唯一原料，但 OCR 噪声大、来源可追溯性差，接入需要单独一轮清洗设计。
4. **韩文的处理方式。** 现在就把 `ko` 写进 schema/路由/缺口状态（但无数据），还是先只保留缺口标记。

---

## 10. S0 / S1 执行记录（用户授权后）

### S0 — 隔离与通道修复（完成）

`backend/app.py` 新增 `get_active()` 单一门禁；`chart`、`diagram`、`diagram-image`、`editorial-reviews`、`drafts/{rid}`、`export` 全部改走门禁；`edits` 与 `POST /api/diagram` 对遗留 ID **无 audit 逃生口**（不允许把新记录挂到无效稿上）。`/api/blind` 的 10 行不可达死代码替换为从 evidence_loop 已完成 case 装配盲评集，legacy 与旧 `cross_language_tests` 永不进入。

新增 `tests/test_legacy_isolation.py`，7 项断言全部通过。它是真回归测试而非声明：改动前这些路由走 `get()`，实测 `get()` 至今仍能取出遗留稿正文，而 `get_active()` 返回 409。`scripts/verify_handover.py:38` 原本是**硬编码的 FAIL 字符串**，现改为实际执行该测试并按退出码判定 —— 结论由测试挣得，不是被断言。

执行后数据库记录数 89，与执行前完全一致（45 legacy + 37 quarantined + 3 diagram + 2 evidence + 2 edit），未新增或修改任何记录。既有 8 项 `handover/test_invariants.py` 全部仍然通过。

### S1 — 首次跑通证据闭环（管道成功，内容未达标）

改动：`PLAN_TOKENS` 650 → 1600；新增 `call_json()` 一次 JSON 修复重试（两次尝试各自独立留痕，截断不会被修复结果掩盖）；`main()` 支持 `--condition= --persona=` 单格运行。既有 4 个 case（3 failed / 1 running）**未被触碰**。

实测服务端不压 max_tokens（curl 探测：max_tokens=1600 实际产出 1492 tokens，finish=stop），修复真实生效。

新 case `case-a29c6b6c0325`（`structured_profile × macro`）：**status=completed，plan finish_reason=stop，未触发修复**。这是本项目**第一份带完整逐句 evidence ledger 与 donor influence ledger 的稿件**。

自动 QA 全绿：`citation_id_validity=1.0`、`errors=[]`、`ai_surface_patterns=[]`、与全部 2647 帖的最长公共子串仅 10 字符（无抄袭）。9 个句子全部标注了 fact/interpretation/condition 类型并挂到真实 source block。

**但我逐个数字回核事实包后，发现自动 QA 全部漏掉的四类缺陷：**

| 缺陷 | 位置 | 事实包真值 | 稿件写法 |
|---|---|---|---|
| **量级错误** | s4 | `revision_previous` = 44,000 = **4.4 万** | 写成 **0.44 万**（差 10 倍）。同句合计 5.5 万反而正确，内部自相矛盾 |
| **越界断言** | s3 | packet methodology 明写 "BLS does not contain consensus forecasts" | 写出"虽高于**通胀预期**" —— 证据中不存在的对象 |
| **引用错位** | s3 | 变化量是 `workweek_change`=0.1 小时 | 断言"周工时微增"却引用 `workweek`=34.4（水平值） |
| **子句误置** | s2 | 3.1 万是 `payroll_12m_mean`（**整体**非农月均） | 紧接"信息业"之后，读起来像信息业均值（实为 -0.8 万） |

另有事实完整性未达标：`fact_id_coverage = 0.667`，遗漏 4 个预登记必需 ID —— `part_time_decline`（41.4 万，CLAUDE.md **点名不可裁掉**的兼职）、`participation`（61.6% 参与率水平，稿件只用了"较一月降 0.5pp"）、`health`（1.3 万医疗）、`ahe_yoy`（3.1% 时薪同比）。

**这一格的真正价值不是"生成成功"，而是它用实证否掉了自动 QA 的充分性**：`citation_id_validity=1.0` 与 `errors=[]` 同时存在一个 10 倍量级错误。这正是 CLAUDE.md 所要求的"显示的是实际输入和声明使用，不应冒充模型内部因果证明"，也说明 `semantic_citation_accuracy` 这个当前为 `None` 的字段是**下一步必须实现的闸门**，不能靠 ID 白名单代替。

**因此本格不得被计为合格内容，也不得进入五组消融的有效样本。** 它是第一个可审核对象，状态为"管道通过、内容未通过"。

### 核验器状态变化（重要）

S0/S1 后复跑 `sh scripts/verify_handover.sh`：

- `legacy_isolation_all_routes`：**FAIL → PASS**（由 `tests/test_legacy_isolation.py` 实测挣得，非硬编码）
- `migration_all_file_hashes`：**PASS → FAIL**，退出码 2 → 1

第二项是迁移完整性检查在正常工作 —— 它比对的是"交接冻结时刻"的 SHA-256，而实施已在你授权下恢复，文件理应不同。**未做任何抑制。** 全部 4 处不匹配如下，逐条可解释：

| 文件 | 原因 |
|---|---|
| `backend/app.py` | S0 隔离门禁与盲评通道修复 |
| `evidence_loop/run_experiments.py` | S1 token 预算、JSON 修复重试、单格 CLI |
| `runs/api_run_ledger.jsonl` | 新增 2 次本地模型调用（append-only，设计如此） |
| `backend/__pycache__/app.cpython-312.pyc` | 导入 app 时重新生成的字节码，非源码 |

**未出现在不匹配清单中的关键项**：`data/lab.sqlite`（证明没有写库）、`evidence_loop/experiments/cases/` 下原有 4 个 case（证明失败记录未被覆盖）、`data/raw_posts.jsonl` 与 `clean_posts.jsonl`（证明未动业务数据）。

今后每轮实施都应更新此表，让 `migration_all_file_hashes` 的 FAIL 始终是**有清单的**，而不是无法解释的漂移。

### 由 S1 得到的下一步修正

1. 生成前置：把 `required_fact_ids` 做成**硬约束**（缺失则拒绝定稿并回环），而不是事后统计。
2. 新增数值蕴含校验：逐句抽取数字，与所引 fact 的 value/unit 做量级与单位比对，覆盖"4.4 万 vs 0.44 万"这类错误。
3. 引用精度校验：断言变化量时必须引用 `*_change` 类事实，而非水平值。
4. 越界检测：对 packet methodology 中显式声明"不包含"的对象（consensus forecasts、股价、FedWatch、公司盈利）做禁用词校验。
5. 以上四项落地后再跑 S2（donor 互补性修正）与 S3（补齐消融），否则会把同类缺陷复制 12 遍。

---

以上每条结论均可用本文件内引用的文件路径与行号复核。凡我未能验证的，已写明 unknown，未做推断填补。
