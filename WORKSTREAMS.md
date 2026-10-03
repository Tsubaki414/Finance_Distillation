# 并行工作流计划

三条内容能力线并行，前置一个数据与实验完整性修复。本文件是执行契约，不是架构文档。

**术语纪律（用户 2026-09-06 指令）**：`financial-persona-distillation → USE` **只是方法决策**。它不得被记作 "Skill 已执行" 或 "ML 已完成"。该 skill 的唯一脚本 `stylometry.py` 是 45 行纯 `re`+`numpy`，零模型；USE 的含义是在代码中强制执行其方法契约。

---

## W0 — 数据与实验完整性（Tier 1 的硬前置）

Tier 1 不得在这四项修完前开始。

| # | 问题 | 实测证据 | 修复动作 | 完成判据 |
|---|---|---|---|---|
| W0.1 | **画像时间泄漏** | `profiles/*.json` 的 `window` 为 07-01→09-05，覆盖 BLS 事件（09-04）之后的帖子；检索侧已按 `test_invariants.py:37-42` 做时间过滤，画像侧没有 | 引入 point-in-time 画像：以事件发布时刻为 cutoff 重建，旧画像保留为独立 version 不覆盖 | 新 profile 的 `window.end < event.published_at`；断言进测试 |
| W0.2 | **无最低样本门槛** | `citrini` 用 **1 条帖**生成 72 个特征，含 `sentence_std`/`p25`/`p75` 这类单样本下无意义的量 | 设 `min_sample_n`；低于门槛的特征置 null 并标 `insufficient_sample`；加分块 bootstrap 区间 | 全部特征带 `sample_n` 与区间或 null；n<门槛者不得进入 routing。**部分缓解已存在**：routing 公式含 `.15*min(n/150,1)` 项，但**特征本身无门槛**，问题仍在 |
| W0.3 | **Trackio 与已发布结果脱节** | DB 只有 `ml-20260906T014631`/`ml-20260906T021854`（clean 1876/1840）；权威 run `ml-20260906T025040`（clean 1825）**无记录**；`artifacts` 表 0 行 | 补登权威 run；此后每次 run 落 config/metrics/split ids/artifact hash | `run_summary.json` 的 run_id 能在 Trackio 查到且 artifact 已登记 |
| W0.4 | **compatibility matrix 无效** ✅**已完成** | 其依据 `topic_clusters/clusters.json` 的 **`silhouette_cosine = 0.0719`**，几乎无簇结构 | 已标 `validity: invalid` 并保留原 66 条 pairs；重做见 T1.3 | 已完成。**更正**：grep 证明它**不供给 routing** —— 只被 `backend/app.py:69 /api/experiments` 读去前端展示。routing 的 donor 选择用的是 `prepare_experiments.py:31` 的 `.55*top-2 cosine + .30*topic incidence + .15*min(n/150,1)`，与本矩阵无关 |

---

## WS-1 — 七层 QA 闸门（热点与事件事实线）

依你上一轮的七层定义执行，此处只记与 S1 实测的绑定关系。

| 层 | 对应 S1 实测缺陷 | 关键判据 |
|---|---|---|
| 1 Source→Fact Pack Fidelity | 未测过 | 分别报 `source_fact_accuracy` / `source_fact_coverage` / `source_methodology_coverage` / `source_to_fact_lineage`；不得用"稿件符合事实包"替代"事实包符合一手来源" |
| 2 Typed Numeric Semantics | **H1**：`revision_previous`=44,000 被写成 `0.44 万`（差 10 倍） | 万/亿、thousand/million 换算交确定性 formatter；量级/单位/期间/level-change 错误**零容忍**，直接阻断 |
| 3 Claim-level Entailment | **H2**：事实包 methodology 明写不含 consensus，稿件仍写"高于通胀预期" | 受控关系词表（高于/低于预期、beat/miss、加速、导致、创纪录…）；无已验证 consensus 源时该类表达**硬失败** |
| 4 Citation Precision | **H3**：断言"周工时微增"却引用 `workweek`=34.4 而非 `workweek_change`=0.1 | `citation_id_validity` **改名** `citation_reference_integrity`；新增 entailment / span_precision / relation_match / claim_support_coverage / unsupported_claim_rate |
| 5 Fact Selection Policy | **H5**：漏 `part_time_decline`（CLAUDE.md 点名不可裁掉）等 4 项 | 三层集合：`must_include` / `plan_required` / `available`；前两者覆盖率硬性 = 1.0；`all_fact_coverage` 降为诊断指标 |
| 6 Atomic Claim 与子句归属 | **H4**：3.1 万（整体非农均值）紧邻"信息业"，读成信息业均值 | 先生成 structured claims 再渲染语言；一个 claim 不得混入不同实体/期间的数字 |
| 7 Pipeline Status 门禁 | 现状只有单一 `status` | `run_status` / `qa_status` / `content_status` 分离；统一 `get_qa_passed` 门禁覆盖 active/review/visual/export/package 全部读写路由 |

**对抗性回归测试**：按你列的 11 条先写测试再改实现，**不得对当前稿件、BLS 文件名或具体中文短语硬编码**。第 11 条（构造当前 case 中不存在的新错误）是泛化性判据，必须通过。

---

## WS-2 — Tier 1 ML（KOL 原帖的人设、语言与习惯线）

W0 完成后开始。共用：dataset_sha256 `c7447fe5ce4df96b16c92373db52dc3f93e5009911b7f9d793a9aa3aea756d5e`；6 个 n≥149 的 donor；先按 `duplicate_group`+thread 分组再时序切分；分块 bootstrap；全部落 Trackio。

- **T1.1 语义去重**：现 `duplicate_group` 是 SHA256 精确哈希，跨作者搬运/改写/跨语言重复一条抓不到
- **T1.2 检索质量**：现 18 条 exemplar 零相关性标注；且检索跑在 **2647 raw** 而非 1825 clean，被规则排除的帖子可能被检出（需确认修正）
- **T1.3 donor 互补性**：替换失效的 compatibility matrix；须按 SKILL.md:29 检查**共享上游 URL**
- **T1.4 风格归因**：`B_authorship` 已可信（combined macro-F1 0.7595），补 language-only / majority 对照与混淆作者对

### 标注任务拆分（先 pilot，不预设 520）

不把 520 当既定需求。先做 **pilot 100 条**，用 pilot 结果反推正式量：

| 任务 | pilot 量 | 标注单元 | 标签集 | 预估耗时 | 用途 |
|---|---:|---|---|---|---|
| P1 语义去重 | 60 对 | 帖子对 | same_claim / paraphrase / same_upstream_source / unrelated | ~50 分钟 | 定阈值、算 IAA |
| P2 检索相关性 | 40 条 | (query, post) | 0–3 级 | ~35 分钟 | Recall@K / nDCG@K |

pilot 交付：标注指南、分层抽样脚本、**双标注者一致性（Cohen's κ）**、边界争议案例集。

**决策规则**：κ ≥ 0.6 才扩量；κ < 0.6 说明标签定义有歧义，先改指南重跑 pilot，不扩量。正式量由 pilot 的类别不平衡与目标置信区间宽度反推，届时给你一个带依据的数字，而不是现在拍 520。

---

## WS-3 — Evergreen 语料线（Reads 2.zip）

**Phase 1 已完成**（只读解包 + manifest）。产物：`evergreen/raw/`、`evergreen/corpus_manifest.json`、`evergreen/survey_corpus.py`。ZIP SHA-256 `49e6dc7e4e2662bbd3c2f5ef59357edcf01b3a4dc3a7dbd7ed1159d6b8ff73a2`，原件未改。

### Phase 1 实测结论

| 项 | 值 |
|---|---|
| 实质文件 | 192（143 md / 42 pdf / 3 docx / 1 doc / 1 ppt / 2 jpg），467 MB |
| Markdown 正文 | **1,821,399 字** |
| **人物线** | 54 文件 **1,615,656 字（占正文 89%）—— 真正的 Evergreen 语料在这里** |
| 书籍线 | 58 个 MD 仅 128,882 字，**62% 不足 1000 字（占位 stub）**；真正书籍内容锁在 42 个 PDF |
| 索引线 | 19 文件 42,009 字 → **仅作 ontology/weak label，永不作为事实或作者原话** |

**转换来源（文件自带 provenance 头，比启发式可靠）**：`pdftotext` 68、**`tesseract-ocr` 29（高 OCR 风险）**、`textutil` 6、`manual-review-needed` 1、无头 39。人物线中高风险文件合计 **511,384 字（占人物线 32%）**。

**四个决定后续设计的硬约束：**

1. **溯源近乎缺失**：143 个 MD 中**只有 2 个**含任何原始 URL。29 个含失效的本机绝对路径。→ 原子原则的 `source_span` 只能锚到**文件内偏移 + 页码/章节**，无法回到原帖 URL。必须如实标注，不得伪造链接。
2. **62% 人物文本是二手整理**（`精华总结`/`语录`/`整理` 等，997,675 / 1,615,656 字）。→ 直接命中你的约束：**不得把二手精华冒充作者原话**。schema 需强制 `voice: author_original | secondary_compilation | unknown`，二手件只能标注为"转述"。
3. **文件级去重几乎失效**：精确哈希 0 组；标题剥离后仅 2 组 / 81,515 字。但 `Tony语录.md` 与 `Tony笔记.md` **内容 100% 相同**（仅差 H1 一行），第三个 `Tony语录（咸鱼整理版）.md` 相似度 **0.9991** 仍逃逸。→ 必须做 **chunk/语义级**去重，文件级不够。
4. **隐私**：29 个文件内嵌第三方本机路径 `/Users/chenboyu`。→ 建 `evergreen_output_gate`，禁止该路径与用户名进入任何抽取产物或对外内容。

### Phase 2（下一步，待确认）

选小规模真实子集，抽 **80–120 条原子原则**，每条至少含：`source_span`（文件+字符偏移）、`author`、`page_or_chapter`、`voice`、`applicable_conditions`、`invalidation_conditions`、`risk`、`counterexample`、`ocr_risk`、`rights`。

优先子集建议：人物线中 **`ocr_risk=low` 且 `voice=author_original`** 的文件（约 617,981 字的非二手部分中 pdftotext/textutil 转换者），避开 511,384 字的高 OCR 风险区，避免把 OCR 错字固化成"原则"。

随后建语义去重、共识/冲突图、检索评测。**Phase 1–2 一律 RAG / Distilled Asset Bank，不得把整个 ZIP 用于 fine-tuning。**

### Phase 3 验收目标

证明**实时事件可检索并重新激活相关 Evergreen 资产**，再由不同 persona 与平台做表达适配。这是 Evergreen 线与热点线的汇合点。

**依赖决策**：42 个 PDF（书籍主体）当前无法抽取，环境缺 `pypdf`/`pdfplumber`/`pdfminer` 全部 PDF 库。是否授权安装解析依赖，需你决定（见文末）。

---

## Tier 2 拆分（不因样本量不足而推迟真实内容闭环）

依你的指令拆成两段：

- **T2-smoke（现在可做）**：单事件、A/B/C/D 四条件各 1 篇，**目的是链路验证而非效果结论**。必须产出**第一条真正读取 donor 原帖正文的 vertical slice**（C/D 条件会注入真实 post_id 与正文，补上 S1 缺失的那一环）。指标只报描述性数值与逐条人工复核，**明确标注 n 不足以支持推断**，不得报 blind-ID 显著性。
- **T2-powered（≥8 事件后）**：正式消融，含 donor removal 与 role swap，报 bootstrap 区间与 blind persona identification。

T2-smoke 的前置是 WS-1 的七层闸门到位，否则四个条件会各自复制 S1 的四类缺陷。

---

## 前端（本轮只冻结，不建设）

**本轮不写任何页面代码，不建空壳。** 只冻结三件事：

1. **IA 冻结**：一级 Today/Intelligence Desk、Events & Opportunities、Accounts/Personas、Drafts & Visuals、Knowledge Products、Library & Updates；二级 Sources & Corpus、Collector Inbox、Pipeline Runs、Quality & Evaluations、Settings。Corpus **降为二级**（现状是首页，属明确错误）。
2. **数据契约冻结**：每个区块声明其读取的后端产物与字段，标注该产物当前是否存在。
3. **页面状态冻结**：每个区块四选一 —— `live`（有真实数据）/ `gap_no_data`（能力未实现，显示原因与阻塞项）/ `gap_blocked`（缺 key/依赖）/ `deferred`。**禁止用假数据或空壳占位。**

按当前证据，几乎全部一级区块会是 `gap_no_data`（传播层无数据底座、Event/Claim Graph 未实现、Knowledge Products 待 Phase 2）。这本身就是诚实的能力地图。

**接入时机**：等 **T2-smoke 产出第一条真正读取 donor 原帖的 slice** 之后，再把真实产物接进 Drafts 与 Personas 两页。

---

## 需要你决定

1. **PDF 解析依赖**：是否授权安装 `pypdf` 或 `pdfplumber`？不装则 42 个书籍 PDF（Evergreen 书籍线主体）无法进入 Phase 2，人物线可照常推进。
2. **Evergreen Phase 2 子集范围**：我建议优先 `ocr_risk=low` + `voice=author_original`，先避开 511,384 字的高 OCR 风险区。若你希望覆盖高风险区，需要先加一轮人工校正。
3. **W0 与三条线的启动顺序**：W0.1–W0.4 会修改 `profiles/` 与 `topic_clusters/`（旧版本保留不覆盖）。确认后我即开始。
