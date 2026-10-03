# ML 能力实证审计

审计人：Claude Code 接手方。日期：2026-09-06。方法：读源码 fit/encode 调用点、读 artifact、读 `runs/model_calls` 原始请求体、只读查 SQLite 与 Trackio DB。本轮**未新增任何生成、未重算任何特征**。

## 结论先行

你的归类成立。当前**实际进入生成路径**的能力是：

> deterministic rule + descriptive statistics + LLM prompting + evidence ledger prototype

**不是 ML distillation pipeline。**

需要区分两件被混为一谈的事：

1. **仓库里确实存在真实的、训练过的 classical ML**（TF-IDF+LogisticRegression、embedding+LogisticRegression、KMeans、PCA），有 fit、有时间切分、有 bootstrap。这部分是真的。
2. **但它们全部位于离线诊断分支，没有一个进入 S1 的生成路径。** S1 那一格的 prompt 里没有任何 donor 名、post_id 或帖子正文（下方 §14 有实证）。

所以"有 ML"与"ML 参与了蒸馏"是两个命题，前者成立，后者不成立。

## 逐项盘点

标签取值：`rule`（确定性规则）、`stat`（描述统计）、`ml`（classical ML，发生 fit）、`emb`（预训练模型 inference + 检索）、`trained`（自训练/微调）、`llm`（LLM prompt）、`none`（未实现）。

### 1. 原始 KOL 帖子清洗与语义去重 → `rule`（语义去重 `none`）

| 项 | 内容 |
|---|---|
| 代码 | `scripts/import_corpus.py:109`；`scripts/promotion_policy.py` |
| 算法 | `hashlib.sha256(normalized).hexdigest()[:20]` 作为 `duplicate_group` |
| fit/train | **无**。纯哈希 |
| 输入 | 5 个历史导入文件；`data/corpus_manifest.json` 记 hash |
| 输出 | `data/raw_posts.jsonl` (2647)、`clean_posts.jsonl` (1825)，`clean_sha256` 见 `handover/state-snapshot.json` |
| 指标/baseline | 无 |
| split | 不适用 |
| 进入生成路径 | 是（clean 语料是画像与检索的输入） |

**语义/近重复去重完全未实现**：`duplicate_group` 是精确文本哈希，1825 条全部是 `str` 类型的独立哈希值。跨作者搬运、同源改写、跨语言重复**一条都识别不了**。

### 2. 主题/叙事聚类 → `emb` + `ml`（已 fit，但结果无效）

| 项 | 内容 |
|---|---|
| 代码 | `scripts/run_ml.py:119` |
| 算法 | `KMeans(n_clusters=8, random_state=42, n_init=10).fit(emb)` + `PCA(n_components=2)` |
| 模型 | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` rev `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`，384 维，**冻结推理，未微调** |
| fit/train | KMeans/PCA **有 fit**；embedding 仅 inference |
| 输入 | 全部 2647 raw，`dataset_sha256=c7447fe5ce4df96b16c92373db52dc3f93e5009911b7f9d793a9aa3aea756d5e` |
| 输出 | `topic_clusters/clusters.json`，run_id `ml-20260906T025040` |
| 指标 | **`silhouette_cosine = 0.0719`** |
| split | 无（自陈 all-corpus exploratory） |
| 进入生成路径 | **否** |

**silhouette 0.07 意味着几乎不存在簇结构。** 这 8 个"主题簇"不能作为叙事聚类证据，更不能推出 donor 互补性。当前 `donor_compatibility_matrix.json` 建立在此之上，需重做。

### 3. 跨语言语义对齐 → `none`

grep `cross_lingual|align|translat` 在 `run_ml.py` / `prepare_experiments.py` 中**零命中**。embedding 模型本身是多语言的，但**没有任何跨语言对齐、实体消歧或信息差检测代码**。`cross_language_tests/` 是旧 LLM 直接翻译产物，已判定无效。

### 4. 人设与发帖习惯量化 → `rule` + `stat`

| 项 | 内容 |
|---|---|
| 代码 | `evidence_loop/build_profiles.py`；`.agents/skills/financial-persona-distillation/scripts/stylometry.py` |
| 算法 | 正则计数 + numpy mean/std/percentile。**stylometry.py 全文无任何模型，纯 re + numpy** |
| fit/train | **无** |
| 输出 | `evidence_loop/profiles/*.json`，12 个有样本 + 46 个空壳；`method_version=empirical-five-profile-v1` |
| 指标 | 无置信区间、无最小样本门槛（见 `feature_provenance_report.md`） |
| 进入生成路径 | **部分**：S1 只用了 3 位 donor 的**平均值**（约 70 个数），不是 871 个特征 |

### 5. donor role 分离 → `rule`（人工公式）

`evidence_loop/experiments/routing.json` 的五角色权重来自人工公式，非学得。三个 persona 首选 donor 全是 `qinbafrank`，language/knowledge 权重全部约 0.33。**S1 那格 `role_weights = {}`，角色分离根本没进入生成。**

### 6. exemplar retrieval → `emb`（真实实现，但 S1 未使用）

| 项 | 内容 |
|---|---|
| 代码 | `evidence_loop/prepare_experiments.py:8-12` |
| 算法 | `SentenceTransformer.encode(normalize_embeddings=True)` → cosine → top-k。pooling = 110-token chunk 均值后 L2 归一 |
| fit/train | **无**，纯 inference；`local_files_only=True` |
| 输入 | 2647 rows / 5932 chunks，cache `embeddings-c7447fe5ce4df96b.npz` |
| 输出 | `experiments/retrieval.json`，3 persona × 3 donor × 2 exemplar = 18 条 |
| 指标 | **无 Recall@K、无 nDCG、无相关性标注** |
| 时间泄漏防护 | 有：`test_invariants.py:37-42` 断言所有 exemplar 早于事件发布 |
| 进入生成路径 | **否**。`material()` 只在 `profile_exemplars` / `multi_donor_separated` 注入 exemplar；S1 是 `structured_profile` |

### 7. 多 donor 组合 → `none`（生成路径中）

`multi_donor_separated` 条件**从未运行过**。S1 的 `structured_profile` 走的是 `material()` 里的 pooled 分支：把 3 位 donor 的特征**算术平均**成一组匿名数字。这是对照组设计，但意味着 S1 证明的恰恰是"donor 身份被抹平"。

### 8. 语言风格迁移 → `llm`（且 S1 中几乎不存在）

唯一机制是把 pooled 数值特征塞进 prompt 让 LLM 自行靠拢。无 style embedding、无 adapter、无风格损失、无 exemplar。**没有任何迁移效果的度量。**

### 9. 热点识别与更新 → `none`

无 Claim Card、无 Event Graph、无 originator/amplifier、无调度器。且如 `CLAUDE_AUDIT.md` §3.1 所述，传播层缺数据底座。

### 10. 引用蕴含验证 → `rule`（且已被证伪为不充分）

`run_experiments.py:40-44` 只做 `set(refs) - set(allowed)` 的 ID 白名单校验。`semantic_citation_accuracy` 字段**硬编码为 `None`**。S1 实证：`citation_id_validity=1.0` 与一个 10 倍量级错误同时成立。

### 11. 语义抄袭检测 → `rule`（仅逐字）

`difflib.SequenceMatcher.find_longest_match()` — 最长公共子串。**只是 verbatim overlap**。S1 的"10 字符"结论**不能**推出语义无重合、无 AI 腔或人设已建立。语义重合、跨人设自相似、AI 结构检测**均未实现**。

### 12. persona 可辨识度验证 → `ml`（但对象错了）

`ml_experiments/B_authorship.json` 是真实的、方法扎实的实验：`StandardScaler + LogisticRegression`，within-author 时间切分 80/20，整线程与完全重复清除，train≥30/test≥10，6 作者 360 测试帖，combined macro-F1 **0.7595**，含 bootstrap 区间。

**但它分类的是真人 donor 的原帖，不是系统生成内容的 persona 归属。** 它回答"6 位真人是否可区分"（可以），没有回答"三个 persona 的生成稿是否可盲辨"（未测，因为有效稿件为 0）。

## ML 实验的诚实评价

| 实验 | 是否真 fit | split | 泄漏防护 | 可用性 |
|---|---|---|---|---|
| A 金融相关分类 | 是（TF-IDF+LR、emb+LR） | 有 | 有 | **循环论证作废**：参照标签就是 rules 自己的输出，故 rules macro-F1=1.000 |
| B 作者归因 | 是 | within-author 时序 80/20 | 整线程+完全重复清除 | **可用**，是全库最扎实的实验 |
| C 聚类 | 是（KMeans） | 无 | 无 | **silhouette 0.07，无簇结构，不可用** |
| D 生成消融 | — | — | — | 旧稿无效；新协议 15 格仅 1 格完成且已判 QA failed |

`bootstrap()` 存在（`run_ml.py:28-32`），且自陈局限诚实：`"iid bootstrap of held-out rows; does not capture donor/thread dependence"`。

## Trackio 现状

**本节初版结论有误，此处更正。** 我当时只查看了 metrics 表的前 2 行，就断言"权威 run 不在 Trackio 里"。完整查询 5 行后证实**恰恰相反**：

| run_id | clean_count |
|---|---:|
| ml-20260906T014631 | 1876 |
| ml-20260906T021854 | 1840 |
| ml-20260906T022003 | 1840 |
| ml-20260906T023112 | 1827 |
| **ml-20260906T025040** | **1825 ← 权威 run，在库中** |

五个 run 全部有记录，权威 run 也在。**Trackio 的 run 级同步是完好的。**

真实缺陷只有一个：`artifacts` / `run_artifact_links` / `artifact_versions` / `traces` **四张表全为 0 行** —— 从未登记任何 artifact，所以指标虽可查、产物却无法与 run 绑定校验。已由 `ml/ledger.py` 补上带 SHA-256 的 artifact 登记（P0B-1）。

## 系统真实能力边界

**能做，且有证据：** 结构化一手事实包（51 typed facts + 精确字符 span，全库最强资产）；逐句 fact 引用 ID 追溯；本地 LLM 全留痕生成；真人作者可区分性（macro-F1 0.76）；精确文本去重；确定性表层文体统计。

**做不到，别声称：** 语义/近重复去重；跨语言对齐与信息差；叙事聚类（silhouette 0.07）；首发/传播识别（无数据底座）；donor 角色分离的生成效果；风格迁移度量；引用语义蕴含；语义抄袭与 AI 腔检测；persona 盲辨；自动更新与事件生命周期；Evergreen 与知识产品（原料 `Reads 2.zip` 从未接入）；视频 ASR/说话人（skill 未安装，见 `skill_use_decision_matrix.csv`）。

**必须撤回的旧表述：** 我在上一轮把 S1 说成"第一份带完整逐句 evidence ledger **与 donor influence ledger** 的稿件" —— evidence ledger 属实，**donor influence ledger 是空的**（`actual_retrieved_exemplars: []`，每句 `declared_donors: []`、`actual_input_post_ids: []`）。该表述在此更正。
