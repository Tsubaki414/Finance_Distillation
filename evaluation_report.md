# 实施与评估结果
截至 2026-09-06T04:27:03.340862+00:00。这是有真实数据和运行记录的研究实现，**尚未达到任务书验收标准**。

| 实际产物 | 结果 |
|---|---|
| 原始 / 清洗帖子 | 2647 / 1825；原始输入哈希未变 |
| 推广处理 | 384 个固定尾注、3 段商业尾文、1 段内嵌导流；另排除 13 条整帖商业内容。保留语料显式推广规则命中为 0 |
| 复核表 | 517 条严格规则复核；300 条明确参考标签，217 条拒判；真人标签为 0 |
| 作者配额 | 只有 4 位中文和 1 位英文作者达到各自 150 条；名单语言不能替代帖子语言 |
| 五条件生成 | 最新完整设计 30 格；目前通过结构 / 数字门槛 7，失败 23；通过不等于内容合格 |
| 人设 / 三类画像 | 3 个原创组合、每类 12 份画像；仅 3 个知识框架通过多帖支持的同模型诊断 |
| 真人盲评 | 0 条真实提交 |
| 数据与 API 校验 | 17 通过，0 失败；完整浏览器 E2E 尚未完成 |

金融分类 A 在同一批 300 条严格规则参考上比较；规则 F1=1 是规则同源性，不能当作人工准确率。

| 方法 | 宏 F1 | 评估数 |
|---|---:|---:|
| rules | 1.0000 | 300 |
| char_tfidf_logistic | 0.8962 | 300 |
| pretrained_embedding_logistic | 0.8343 | 300 |
| local_llm_7b | 0.8233 | 298 |

7B LLM 请求 300 条，298 条返回有效类别；拒判 2 条。217 条缓存是同提示、同系统指令、同模型提交和参数的既有真实请求，83 条新推理。

作者识别 B：按时间留出，排除交叉线程及完全重复内容；6 位训练/测试量足够的作者、360 条测试。这里的资格门槛不是每位 150 条的语料验收门槛。

| 特征 | 宏 F1 |
|---|---:|
| stylometry | 0.7163 |
| embedding | 0.6425 |
| combined | 0.7595 |
| majority | 0.0612 |
| language_only | 0.2260 |

C 为全语料的 8 个探索性主题聚类、12 位作者分布与 66 对兼容性；240 对同题、跨时间文本做 self-similarity。它不是预测回测收益，也不构成纯风格相似度的理论上限。

D 每格只有一次样本，不能据此证明人设组合优于基线。早期受推广污染的版本及失败模型输出单独保留；不同模型与生成约束同时变化，因此不能把差异全归因于模型大小。真实复核已经发现“上修即延迟招聘”“失业率不变即参与率未提升”等错误；同模型检查未拦住它们。详见 `runs/automated-editorial-reviews.json`，原始稿和调用没有覆盖。

Notebook 使用另一组 TF-IDF 特征上限，宏 F1 0.8252；配置不同，不应与主实验 0.8962 当成同一结果。全部模型为固定公开权重本地运行；未启动 LoRA/SFT、未上传语料。

三类视觉分别是：随稿件证据版本重算的数据图、公司原始 10-Q 页面图、由实际事实引用和未来日历节点生成的可编辑结构图。源图不替代正文事实核验。

跨语言转换已实际运行两个方向，但不能判合格：中文转英文把“不能据此认定政策预期过度乐观”译成了政策预期确实过度乐观。逐字检查见 `cross_language_tests/automated-review.json`；这条是 AI 检查，不是真人盲评。

独立的 v4 接口修复测了 3 人设 × 2 语言的 multi 模式，3 格通过、3 格被校验拒绝；不改写前面的 30 格消融结果。v4.1 另修复了英文 lacks 与 negative 数字表述造成的误报，重放原始模型响应并单独记录，未将其计作新生成成功。见 `runs/generation-repair-v4.json`、`runs/validator-calibration.json`。拒绝数不是内容错误率，自动校验存在误报与漏报。

真实调用与成本：

- 已保存 722 个模型调用文件，其中 718 个有完成记录；状态和 token 明细见 `runs/run-ledger-summary.json`。
- 本地模型付费 API 成本为 0；没有计入硬件、电力、网络和既有数据供应商历史费用。Yahoo 的 3 次 SDK 操作不能声称只有 3 个底层 HTTP 请求。
- 新 X 请求 0；SEC 网络请求 0。缺少各自所需的凭证/身份，不能伪造已运行状态。

待完成门槛：

- donor_language_coverage：incomplete。>=6 authors with >=150 Chinese original finance posts each and >=6 authors with >=150 English posts each; complete 180-day windows or documented capped 500 samples
- new_x_collection：awaiting_account_and_cost_preflight。XQUIK_API_KEY and approved extraction cost ceiling; selected collector only
- human_blind_review_and_edit：awaiting_real_human。
- generation_quality：not_validated。Concrete unsupported inferences survive same-model diagnostics. Five-mode results contain schema, citation and factual failures. No persona quality improvement established.
- knowledge_frameworks：partial。Sparse same-donor multi-post support; accepted candidates still lack independent semantic review.
- sec_mcp：disabled。Real SEC_EDGAR_USER_AGENT contact identity. Issuer-hosted 10-Q available; independent SEC retrieval not executed.
- browser_replay：partial。Existing Chrome window corpus checks only; user later navigated away. No new browser or restart. Four-page API verification does not equal complete browser E2E.
- continuous_current_events：not_implemented。Actual captured primary releases replay through versioned ingestion; no continuous live event collection or alert scheduler.

从 `启动.md` 打开实际页面；技能决策见 `skill-audit/audit.md`，每个 skill 的产物、数据量、指标与前端入口见 `skill-audit/skill-product-run-matrix.json`。
