# ML Vertical Slice 提案（待确认，未执行）

目标不是堆 ML 名词，而是回答一个可证伪的问题：

> **ML/retrieval 是否比规则与普通 prompt 更能保留真人的信息密度、推理方式和发帖习惯，同时降低抄袭、幻觉和 AI 腔？**

## 先说一个必须先解决的设计问题

你要求的 A/B/C/D 四条对比里，**C 与 D 的生成侧对比在当前数据量下无法得出结论**。

单事件 × 3 persona × 5 条件 = **15 篇稿**。用 15 个样本做 blind persona identification：随机基线 1/3，要在 α=0.05 下检出 0.33→0.60 的提升，所需样本量约 **n≥50 每组**。15 篇连区分"有效果"和"噪声"都做不到，bootstrap 区间会宽到覆盖随机基线。

**我不建议假装跑完 15 格就得到了消融结论。** 建议改成两层：

- **Tier 1 — 现有语料就能定论**（n 在百到千量级，不需新采集）：语义去重、检索质量、donor 互补性、风格归因。这四项**现在就能得出有统计意义的结果**。
- **Tier 2 — 生成侧消融**（需要 8–10 个事件才有意义）：先用 Tier 1 修好 donor 选择与检索，再扩事件数，最后跑 A/B/C/D。

下面按这个分层给设计。

---

## Tier 1：现在可定论的四项

共用设置：

- **数据快照**：`data/clean_posts.jsonl`，`dataset_sha256 = c7447fe5ce4df96b16c92373db52dc3f93e5009911b7f9d793a9aa3aea756d5e`
- **donor**：6 个 n≥149 的 —— aleabitoreddit(404)、phyrexni(357)、michael_qqq2025(338)、qinbafrank(312)、kovainvest(226)、xingpt(149)。其余 6 个（n≤18）**排除**并显式记为样本不足
- **切分**：按 `financial-persona-distillation/SKILL.md:25` —— **先按 `duplicate_group` 与 thread 分组，再按时间切分**，同组绝不跨 split
- **泄漏防护**：除精确哈希外，增加近重复隔离（见 T1.1 产出的近重复对，整簇同侧）
- **不确定性**：全部指标报 bootstrap 95% 区间，且**按 donor 分块重采样**（不是 iid），修正 `run_ml.py:32` 自陈的局限
- **ledger**：每次 run 写入 Trackio，含 run_id、seed=42、dataset_sha256、split ids、artifact hash

### T1.1 语义去重（当前完全缺失）

- **产品问题**：跨作者搬运、同源改写、跨语言重复能不能识别？现在 `duplicate_group` 是精确哈希，一条都识别不了。
- **Baseline A（rule）**：精确哈希 + 归一化后 char 3-gram Jaccard 阈值
- **Candidate C（emb）**：MiniLM 多语言 embedding cosine + 阈值扫描
- **人工标注**：分层抽 **400 对**（按 cosine 分层：0.95+/0.85–0.95/0.7–0.85/随机负例），人工标 `same_claim / paraphrase / same_upstream_source / unrelated`
- **指标**：Precision / Recall / F1 + PR 曲线 + 阈值敏感性；分中英与跨语言子集报 slice
- **成功阈值**（预登记）：跨语言改写对上 Recall ≥ 0.70 且 Precision ≥ 0.85，否则判定 embedding 方案不足，回退到规则 + 人工复核

### T1.2 检索质量（当前 0 指标）

- **产品问题**：检索到的 exemplar 真的与事件相关吗？现在 18 条 exemplar **没有任何相关性标注**。
- **Baseline A**：BM25 / TF-IDF 关键词检索
- **Candidate C**：现有 MiniLM embedding cosine（当前实现）
- **标注**：对 3 个 persona query，各取 A、C 的 top-20 合并去重，人工标 0–3 级相关性（约 120 条）
- **指标**：**Recall@5 / Recall@10 / nDCG@10**，含 bootstrap 区间
- **必查的已知问题**：当前检索跑在 **2647 条 raw**（`retrieval.json` 的 `rows: 2647`）而非 1825 clean，即被规则排除的帖子也可能被检出。需确认并修正。

### T1.3 donor 互补性（当前结论不可用）

- **产品问题**：三个 persona 的首选 donor 全是 qinbafrank、角色权重全约 0.33 —— 它们真的互补吗？
- **当前失效证据**：`topic_clusters/clusters.json` 的 **`silhouette_cosine = 0.0719`**，几乎无簇结构；`donor_compatibility_matrix.json` 建立其上，需重做
- **方案**：donor × 主题分布的 JS 散度 + 冗余惩罚；同时检测**共享上游 URL**（SKILL.md:29 明确要求"inspect shared upstream URLs before calling donors complementary"）
- **指标**：新旧 routing 的 donor 重叠率、角色权重熵；成功标准是三个 persona 的 donor 集合不再高度重合
- **产出**：新的 `routing.json`，附变更理由

### T1.4 风格/作者可辨识（已有可信实验，需扩展）

- **现状**：`B_authorship.json` 方法扎实（within-author 时序 80/20、整线程+完全重复清除、6 作者 360 测试帖、combined macro-F1 **0.7595**、含 bootstrap）
- **要补的**：加入 **language-only baseline** 与 **majority baseline** 对照（DB 里已有，需并列呈现）；报混淆作者对；报跨主题稳定性
- **它回答什么**：真人 donor 可区分（0.76）。**它不回答生成稿的 persona 是否可盲辨** —— 那是 Tier 2

---

## Tier 2：生成侧消融（Tier 1 通过后再做）

四条件按你的定义：

| | 条件 | 输入内容 |
|---|---|---|
| **A** | 规则/关键词/TF-IDF | 事实包 + 关键词检索到的 exemplar |
| **B** | structured profile prompt | 事实包 + pooled 数值画像（**= 当前 S1 跑的那格**） |
| **C** | multilingual embeddings + retrieved real exemplars | 事实包 + 真实 donor 帖子正文（带 post_id） |
| **D** | role-separated multi-donor retrieval | 事实包 + 按 knowledge/reasoning/language/habit 分角色的 donor 与权重 |

**前置条件（缺一不可）**：

1. Tier 1 的 T1.3 完成，donor 组合不再三 persona 同源
2. 事件数扩到 **≥8**，否则 n 不足（见开头）
3. 七层 QA 闸门就位，否则 4 个条件会各自复制 S1 那 4 类缺陷

**消融**：donor removal（逐个移除 knowledge/reasoning/language donor）与 role swap（互换两个 persona 的 language donor），检验指标是否按预期方向变化。若移除 knowledge donor 后知识覆盖不降，说明 donor 只是标签。

**评测三分离**（你已指出 LCS 的局限，这里落实）：

| 指标 | 定义 | 现状 |
|---|---|---|
| `verbatim_overlap` | difflib 最长公共子串字符数 | 已有（S1 = 10 字符） |
| `semantic_source_overlap` | 生成句 vs donor 帖 embedding cosine 的 top-k 分布 | **未实现** |
| `cross_persona_self_similarity` | 同事件不同 persona 稿件两两 embedding 相似度 | **未实现** |
| `generic_ai_structure` | 结构模板率（三段式、固定收尾、对称度） | 仅有关键词表，非结构检测 |
| `blind_persona_identification` | 真人盲评，答案在评分前不入 UI/API | **未实现**，且需 n≥50/组 |

**明确不做**：LoRA/SFT。依 `financial-persona-distillation/SKILL.md:45`，需先证明 frozen baseline 存在瓶颈。

---

## Skill 落实（USE 项必须产出 artifact）

- **financial-persona-distillation → USE**：不是 import 它的脚本，而是**在代码里强制执行它的方法契约** —— SKILL.md:25 的"先分组再时序切分、只在训练集 fit 词表/scaler"，SKILL.md:37 的"五模式同证据同预算"，SKILL.md:22 的"language donor 必须有可归属原文并记录支撑 post IDs"（S1 恰恰违反了最后这条）。
- **huggingface-trackio → USE**：**先修同步断裂** —— 当前 DB 只有 `ml-20260906T014631` / `ml-20260906T021854`（clean 1876/1840），权威 run `ml-20260906T025040`（clean 1825）**无记录**，`artifacts` 表 0 行。Tier 1 每次 run 必须落 Trackio 且登记 artifact hash。

其余 skill 的 USE/REJECT/BLOCKED/DEFER 见 `skill_use_decision_matrix.csv`。**视频转录 skill 未安装**，当前无 YouTube/Bilibili 转录能力，不得声称具备。

---

## 需要你决定的

1. **是否接受两层拆分**，即先做 Tier 1（现有数据可定论），把生成侧消融推到事件数够了之后。
2. **人工标注预算**：Tier 1 需要约 **520 条人工标注**（400 去重对 + 120 检索相关性）。这是唯一无法自动化的输入 —— 没有它，T1.1/T1.2 只能继续用银标，就会重蹈实验 A 的循环论证。
3. **顺序**：先 Tier 1，还是先七层 QA 闸门。两者不冲突但都要人力；我的建议是**先七层闸门**，因为 Tier 2 缺了闸门必然复制缺陷，而 Tier 1 不受闸门阻塞、可并行。
