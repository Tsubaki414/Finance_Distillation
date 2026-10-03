# 871 个特征的来源报告

逐条回答你的九个问题。全部基于只读检查，**本轮没有重算任何特征**。

## 1. 谁、何时、通过什么命令生成？

| 项 | 值 |
|---|---|
| 生成代码 | `evidence_loop/build_profiles.py`（mtime **2026-09-06 13:04:12**） |
| 产物 | `evidence_loop/profiles/*.json`（qinbafrank.json mtime **2026-09-06 13:06:15**） |
| 命令 | `python evidence_loop/build_profiles.py`（`docs/CURRENT_STATE_AUDIT.md` 第 14 行登记，标注"会写入"） |
| 生成者 | **前一位 Agent（Codex），交接之前** |
| 方法版本 | `method_version = empirical-five-profile-v1` |
| 版本 ID | 每 donor 一个内容哈希，如 qinbafrank = `a8e2585d5d288be0`，快照存 `profiles/versions/` |

**注意：没有 run_id、没有 Trackio 记录、没有 dataset_sha256 绑定。** 与 `run_ml.py` 产物（有 `ml-20260906T025040`）不同，画像层缺可复现运行标识。这是需要补的。

## 2. Claude 本轮是否重新计算过？

**没有。** 我只读取。S1 那格消费的是继承下来的既有特征。`handover/migration.json` 哈希核验中 `evidence_loop/profiles/` 与 `profiles/versions/` **未出现在不匹配清单**，可证明未被改动。

## 3. 哪些是规则计数、哪些是统计估计、哪些来自模型？

以 qinbafrank 的 72 个特征为例（12 donor × 约 72 ≈ 871）：

| 类型 | 数量 | 轴 | 实际算法 |
|---|---:|---|---|
| 确定性文体统计 | **54** | style | `stylometry.py`，纯 `re` + `numpy` 的 mean/std/percentile/占比 |
| 正则出现率 | **10** | knowledge 4 + reasoning 6 | 逐帖 0/1 关键词命中率 |
| 元数据计数 | **5** | content_habit 4 + visual 1 | `post_type`、时间戳间隔、`media_type` 占比 |
| 阈值判定 | **2** | content_habit | ≤280 / ≥800 Unicode 字符 |
| 继承字段 | **1** | knowledge | provider 的 language 字段占比 |

**来自模型的特征：0 个。** `stylometry.py` 全文 45 行，无任何模型导入。

统计成分仅限描述统计（均值、标准差、分位数）。**不存在参数估计、不存在推断统计。**

关键限制照抄 `method` 字段自陈：`"Explicit surface reasoning cue, not a proof of reasoning quality"`。所以 `reasoning.causal_cue = 0.471` 的含义只是"47.1% 的帖子出现过 因为/所以/导致 等词"，**不是推理能力度量**。

## 4. 每个 donor 有多少有效样本？

| donor | n | 是否达 Gate B 150 | 时间窗完整 |
|---|---:|---|---|
| aleabitoreddit | 404 | 是 | 否 |
| phyrexni | 357 | 是 | 否 |
| michael_qqq2025 | 338 | 是 | 否 |
| qinbafrank | 312 | 是 | 否 |
| kovainvest | 226 | 是 | 否 |
| xingpt | 149 | **差 1 条** | 否 |
| beth_kindig | 18 | 否 | 否 |
| globalmktobserv | 10 | 否 | 否 |
| tradexwhisperer | 4 | 否 | 否 |
| ericjackson | 3 | 否 | 否 |
| rjccapital | 3 | 否 | 否 |
| citrini | **1** | 否 | 否 |

另有 **46 个 `candidate_no_real_posts` 空壳画像**，n=0。

**全部 12 个 donor 的 `window.complete_timeline` 均为 false。** citrini 用 **1 条帖**生成了完整的 72 个特征 —— 包括 `sentence_std`、`p25`、`p75` 这类单样本下无意义的量。

## 5. 是否计算置信区间或最小样本门槛？

**都没有。** `build_profiles.py` 中 `confidence` / `bootstrap` / `min_sample` / `stderr` 全部零命中。唯一命中的 `interval` 是 `interval_hours`（发帖间隔），是量本身而非区间估计。

后果：n=1 与 n=404 的特征在 `routing.json` 里以**同等权重**参与 donor 选择公式。

（对比：`run_ml.py:28` 的分类/归因实验**有** bootstrap 区间。不确定性估计只缺在画像层。）

## 6. 特征是否随时间稳定？

**未测。** 没有任何时间切分稳定性检验、没有滚动窗口、没有跨期方差。

且存在**回顾性泄漏**：`window` 为 2026-07-01 → 09-05，覆盖 BLS 事件（09-04 发布）**之后**的帖子。检索侧已做时间过滤（`test_invariants.py:37-42` 断言 exemplar 早于事件），**画像侧没有**。所以 point-in-time 一致性不成立。

## 7. 哪些特征真实进入了新 case 的 prompt/retrieval？

实测 `runs/model_calls/local-1500415fcef14a0b.json` 的 request messages（prompt 全长 19,975 字符）：

进入的是 `"profiles": {"pooled": {...}}` —— **3 位 donor 的算术平均值**，约 70 个数字：

```
knowledge:      macro 0.277, industry 0.339, trading 0.228, psychology 0.205, language_zh 0.979
reasoning:      causal_cue 0.420, comparison_cue 0.143, conditional_cue 0.373,
                invalidation_cue 0.081, alternative_cue 0.586, scenario_math 0.159
style(54 项):   char_count 487.8, sentence_count 11.4, sentence_mean 46.7, digit_density 0.047 ...
```

**没有进入的：** 任何单个 donor 的 871 个特征原值、任何 donor 名、任何 post_id、任何帖子正文、任何角色权重。

实测 prompt 包含性检查：

```
'historical_donor_examples_untrusted' in prompt  -> False
'role_separated_donors'               in prompt  -> False
'post_id'                             in prompt  -> False
'qinbafrank' / 'phyrexni' / 'michael' in prompt  -> False
```

## 8. donor influence ledger 是生成前由检索确定，还是生成后补写？

**两者都不是纯粹形式，且对 S1 而言是空的。**

机制（`run_experiments.py:45-49`）：先由 `prepare_experiments.py` **在生成前**算出检索集 `rs`；生成后取模型**自报**的 `donor_ids`，与 `rs` 做交集得 `actual_input_post_ids`，再用 `difflib` 算文本重合。

所以它是"**生成前确定的检索集** ∩ **生成后模型自报**"的事后连接，代码里自陈 `"not a causal measurement of model internals"`，这个自陈是准确的。

**但对 S1：`structured_profile` 模式下 `material()` 返回 `rs = []`。** 实测结果：

```
actual_retrieved_exemplars: []
role_weights: {}
每一句: declared_donors=[], actual_input_post_ids=[], textual_overlap=[]
```

**S1 的 donor influence ledger 是一个空壳 schema。** 我上一轮称其"完整"是错的，已在 `ml_capability_audit.md` 更正。

## 9. 当前 case 生成时是否读取具体帖子正文？

**没有。一条都没有。**

- 使用的 post_ids：**空集**
- 实际文本片段：**无**

`material()` 的分支条件决定了这一点 —— exemplar 只注入 `profile_exemplars` 和 `multi_donor_separated` 两个模式，S1 跑的是 `structured_profile`。

作为对照，**如果**跑 exemplar 模式，会注入的是 `retrieval.json` 里这 6 条 macro 样本（当前未使用）：

| post_id | donor | cosine | post_type |
|---|---|---:|---|
| 2072665494768021550 | qinbafrank | 0.649 | quote |
| 2095519475567386906 | qinbafrank | 0.600 | quote |
| 2085707173074747750 | phyrexni | 0.559 | quote |
| 2085811500791509406 | phyrexni | 0.540 | quote |
| 2067059111133683797 | michael_qqq2025 | 0.501 | original |
| 2076841170274304335 | michael_qqq2025 | 0.485 | original |

## 结论

871 个特征是**前一位 Agent 在交接前用确定性正则与描述统计生成的、无不确定性估计、无稳定性检验、含回顾性泄漏的表层观测**。

它们在 S1 中的实际作用是：被平均成约 70 个匿名数字塞进 prompt。

**因此"继承 871 个特征 + 调用一次本地 LLM"确实不能计作已执行 ML 蒸馏 —— 你的判断成立。**
