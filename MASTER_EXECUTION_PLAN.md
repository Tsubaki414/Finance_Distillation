# MASTER EXECUTION PLAN

自主执行授权自 2026-09-07。本文件是执行契约与状态账本，随每项任务完成更新。

## 永久保护约束（任何任务不得违反）

不可覆盖、改写或删除：原有 4 个 case、S1 原始输出、`case-a29c6b6c0325` 的冻结正文与 ledger、原始 ZIP、raw posts、v1 profiles、既有数据库记录。

S1 恒为 `run_status=completed / qa_status=failed / content_status=blocked / classification=qa_failed_regression_case`。

所有新实验建新 run/case/version，保留 parent、dataset snapshot、config、model、seed、cost、latency、artifact hash。

## 依赖图

```
P0A 七层 QA 闸门 ──────┐
                       ├──> P1 真实内容闭环(五条件 smoke) ──> P3 平台内容包 + 视觉 brief
P0B 实验与画像完整性 ──┤                                   └──> P5 跨语言(中英)
   └─ profiles_v2 上线 ┘
                       
P0C 产品前端 IA ───────────> UI 接入以上全部真实 artifact

P2 KOL/Tier1 ML(去重·检索·归因·donor role) ──> P1 的 C/D 条件依赖它
P4 Evergreen 工作流(span 权限·聚类·冲突·人审队列·内容产出)
P6 日历与内容机会更新
P7 视频契约(OCR/ASR 保持 deferred)
P8 Powered evaluation(≥8 事件后)
```

关键路径：**P0A → P2 → P1 → P3**。P0B、P0C、P4、P6、P7 可并行。

## 任务表

图例 状态：`done` / `running` / `todo` / `blocked`

| id | 任务 | 用户价值 | 依赖 | 输入 | 输出 artifact | 验收 | 风险 | 状态 | 实际测试 | 进 active pipeline |
|---|---|---|---|---|---|---|---|---|---|---|
| **P0A-1** | 七层闸门核心引擎 | 错误内容不进队列 | — | fact packet, case ledger | `qa/gates.py` | 11 条对抗用例全过 | 规则过严误杀 | **done** | `tests/test_qa_gates.py` 35 项全过 | 是 |
| **P0A-2** | 三层状态与路由门禁 | 未过审内容不可导出 | P0A-1 | backend routes | `qa/status.py`, `/api/deliverable` | active/export 拿不到 qa_failed | 旧路由遗漏 | **done** | 隔离测试 13 项全过 | 是 |
| **P0A-3** | 冻结输入回归 run | 证明修复有效 | P0A-1 | S1 冻结输入 | `qa/runs/qa-reg-*.json` | 5 条缺陷全被拦 | 覆盖 S1 | **done** | **5/5 全中**，S1 未改动 | 否（诊断） |
| **P0B-1** | 实验 ledger 与 artifact 登记 | 指标可复现 | — | run_summary | `ml/ledger.py`, `ledger.json` | 权威 run + artifact hash 可查 | — | **done** | 5 run 全在 Trackio；artifact 表原为 0 行已补 | 否 |
| **P0B-2** | profiles v2 上线开关 | 画像无泄漏 | P0B-1 | profiles_v2 | `profiles/active.json` | 通过测试才切换，可回滚 | 误切换 | **done** | 14 项全过；已激活 v2，6 位合格 donor，rollback_to=v1 | 是 |
| **P0B-3** | 禁用 pooled 平均 | multi-donor 不再匿名化 | P0B-2 | run_experiments | `material()` 按 donor 分列 | pooled 分支移除 | 破坏旧对照 | **done** | grep pooled=0；两模式均输出具名 donor | 是 |
| **P0C-1** | 中文产品 IA | 编辑能用 | — | intel view model | 中文导航、首页、生产链路横条 | 1440×900 首屏达标 | — | **done** | 截图已验证 | 是 |
| **P0C-2** | Opportunity Workspace | 内容生产工作区 | P0C-1 | workspace model | 三栏页面 | 真实 artifact 接入 | — | **done** | 截图已验证；Evergreen 3 条已激活 | 是 |
| **P2-1** | 语义去重评测 | 不误合并真实内容 | — | clean posts | `dedup_eval.json` + 标注包 | 四方法对比 + CI | 无真人标签 | **done** | 50 硬样本；朴素 embedding fp=15，加数字守卫 fp=0 | 是（守卫规则） |
| **P2-2** | 检索评测 harness | 检索质量可测 | — | retrieval | `retrieval_eval.json` + 92 条判定包 | 10 query × Top-5 | 需真人标注 | **done** | 两法 Top-5 近零重叠；生产检索 exemplar 全在 clean 集内 | 否（待标注） |
| **P2-3** | 作者归因 v2 | 无效 donor 不参与生成 | P0B-2 | clean posts | `authorship_v2.json` | 时序切分+近重复隔离+CI+基线 | 样本失衡 | **done** | combined macroF1 0.693 CI[0.635,0.745]，语言基线 0.223；4/6 可作语音 donor | 是 |
| **P2-4** | Donor role 分离 | 五角色各有真实依据 | P2-3 | profiles_v2, posts | `experiments/roles_v2.json` | 每角色带依据与次优对比 | 角色同质 | **done** | 3 个 persona → 3 组不同 donor 组合；视觉角色如实留空 | 是 |
| **P1-1** | 五条件 smoke | 第一条真实闭环 | P0A, P2-4 | fact packet | 15 个新 case + smoke 报告 | C/D 实读原帖正文 | 生成质量 | **done** | 15/15 完成 0 失败；全部被 QA 拦；10 条原帖 6,652 字入 prompt | 否（未人审） |
| **P3-1** | 平台内容包 | 运营可直接用 | P1-1 | drafts | content packages | 6 种形态 + 来源包 | — | todo | 结构校验 | 否 |
| **P3-2** | 视觉 brief 引擎 | 配图不套模板 | P1-1 | facts, claims | visual briefs | 按内容选类型 | — | todo | 断言多样性 | 否 |
| **P4-1** | span 级权限七字段 | 引用合规 | — | principles | 更新 candidates | 每 span 独立判定 | — | todo | 断言 | 是 |
| **P4-2** | 原则聚类与冲突图 | 去重并保留条件差异 | P4-1 | 110 principles | `principles/clusters.json` | 冲突对可查 | — | todo | 评测 | 是 |
| **P4-3** | 人审队列 | 真人审核入口 | P4-1 | principles | review queue API+UI | 无人审保持 pending | 需真人 | todo | 接口测试 | 是 |
| **P4-4** | Evergreen 内容产出 | 语录/解释稿/章节 | P4-2 | clusters | 内容 artifact | 状态正确 | — | todo | QA 闸门 | 否 |
| **P5-1** | 中英跨语言 | 双语内容 | P1-1 | drafts | 跨语言 case | claim/数字保真评估 | 韩文保持 gap | todo | 评测 | 否 |
| **P6-1** | 日历与 adapters | 事件不遗漏 | — | 已有日历 | source adapters | 增量更新 | — | todo | 断言 | 是 |
| **P6-2** | 内容机会排序 | 知道先做什么 | P6-1, P2 | signals | opportunity scoring | 可解释 | — | todo | 断言 | 是 |
| **P7-1** | 视频数据契约 | 未来可接 | — | video-audit | schema + fixture | 标 deferred | ASR 未授权 | todo | 契约测试 | 否 |
| **P8-1** | Powered ablation | 统计结论 | ≥8 事件 | cases | 正式报告 | 达样本才跑 | 样本不足 | blocked | — | 否 |

## 里程碑 1 结论（P0A + P0B + P0C + P2-1）

| 能力 | 证据 |
|---|---|
| 七层 QA 闸门 | `tests/test_qa_gates.py` 35 项全过，含 11 条对抗用例与 6 条泛化用例 |
| 闸门有效性 | 冻结 S1 重放，**人工发现的 5 条缺陷全部命中且理由正确**，S1 未被改动 |
| 交付门禁 | `/api/deliverable` 对 82 条遗留稿全部 409；QA 未跑 = 不可交付 |
| 画像完整性 | v2 已激活，时点截断 + 最低支持度 + bootstrap CI + 收缩；6 位合格 donor，3 位样本不足被排除 |
| 匿名平均已禁 | `run_experiments.py` 中 pooled 出现 0 次 |
| 去重产品决策 | 该语料真重复 0，模板日更 15，朴素 cosine 全误判；数字守卫将误报降为 0 |

## 里程碑 2 结论（P2 Tier 1 ML）

| 发现 | 证据 | 产品影响 |
|---|---|---|
| 语义去重会误合并模板日更 | 50 硬样本，朴素 embedding fp=15，数字守卫 fp=0 | 不上纯 cosine 去重 |
| 作者归因 v2 低于 v1 | v2 0.693 vs v1 0.7595 | v1 的高分含泄漏（未隔离近重复、未遮蔽 cashtag） |
| 仅 4/6 donor 可作语音 | xingpt 召回 0.250、kovainvest 0.444 | 两者不得担任语言 donor |
| 语言必须匹配受众 | aleabitoreddit 中文占比 0% | 英文作者不得作中文语音 donor |
| 三 persona 终于分化 | 3 组不同 donor 组合（原为同一组） | multi-donor 消融才有意义 |

## 里程碑 3 结论（P1-1 五条件 smoke）

15 格全部完成、0 失败、**全部被 QA 拦截**（无一可交付）。30 次调用、303,155 tokens、27.6 分钟、0 费用。

**主发现（方向，非结论）**：人设约束越多，必含事实覆盖越低，且单调。

| 条件 | 必含覆盖 | prompt tokens | 真实 donor 原帖 |
|---|---:|---:|---:|
| base_model | **0.92** | 5,895 | 0 |
| simple_persona_prompt | 0.67 | 5,593 | 0 |
| structured_profile | 0.64 | 11,209 | 0 |
| profile_exemplars | 0.58 | 12,917 | 3.3 |
| role_separated_multi_donor | **0.56** | 13,050 | 3.3 |

每条件仅 3 格，**不作统计推断**。下一步验证：把事实覆盖做成生成期硬约束，或把事实渲染与语气渲染分离，再重跑。

**闸门在真实规模下暴露了自身缺陷并已修**：首轮 15 格共 9 项误报，其中 7 项是同一个 —— 把"12 个月"里的 12 当数值与 `food_12m_mean=12,000` 比对报 1000 倍错误。修复后重评（不重新生成），误报清零，S1 回归仍 5/5。

## 已知阻塞（不停止其他工作）

| 阻塞 | 原因 | 保留的接口 | 绕行 |
|---|---|---|---|
| X 新采集 | 无 `XQUIK_API_KEY` 与成本上限 | Collector Inbox 手工导入 + fixture | 用既有 2647 raw |
| 传播层 | 引用/回复父帖不可解析 | schema 保留，UI 标 unavailable | Hot Signal 降级 |
| 扫描 PDF OCR | tesseract 未授权 | `deferred_non_blocking` | 用文本层 PDF 与人物线 |
| 真人审核 | 需真人 | 审核队列 + 标注包 | 一律 `pending_human_review` |
| 韩文 | 无语料无审阅 | schema 一等位 | 显式 gap |
| Powered ablation | 仅 1 事件 | harness 就绪 | 只出描述性结果 |

## 汇报口径

每个里程碑回答：用户获得了什么、证据是什么、哪些未人审、哪些仍 blocked、下一项自动任务。不用"测试全绿"代替产品进展。
