# localization_v1：最小重构

本实现落实已接受的 [audit](audits/2026-09-29-distillation/AUDIT.md) G/H；没有重跑生产，也没有修改历史 corpus 或 content queue。真实回归源均为 audit 给出的合成 fixture。

```text
enabled source registry → existing X/RSS adapters
→ complete extracted source + immutable snapshot/hash + source language
→ worth_moving + enabled account routing (one model request)
   SKIP / NONE / NEEDS_SOURCE / NEEDS_REVIEW → persist reason, no generation
→ account.lang determines target_language (en↔zh only)
→ exact paragraph selection (short source = whole post)
→ faithful translation + paragraph alignment
→ minimal span edits applied to the frozen translation (default = unchanged)
→ numeric/language/identity/provenance checks + bilingual semantic comparison
→ draft_ready, human review pending / blocked / needs_review
→ JSON queue + three-way review + separate body.txt / metadata.json exports
```

`live/production.py` 的默认 source-first 写作路径已替换。没有调用旧 `classify_latest`、`_pick_persona`、`write_hot_draft`、`public_writer.SYSTEM`、旧 fact/originality QA 或 Evergreen 成稿库。`--events` 旧生成入口停用；`--prepare` 检索准备保留。没有自动发布。

## 文件与接口

| 文件 | 改动 |
|---|---|
| `live/distillation_source.py` | 原文与规范化文本分离；SHA-256、不可变版本、源语言、完整性、Unicode offsets、缺失 provenance 标记 |
| `live/distillation_prompts.py` | 路由、选段、翻译、轻本地化和双语 QA 五类请求；没有 editor brief 或重写任务 |
| `live/distillation.py` | 数据契约、终止分支、选段验证、对齐、编辑记录、QA 编排、按源版本串行和重放、审核及导出 |
| `live/fidelity.py` | 精确 Decimal 单位/币种转换、有限指标绑定、实体 glossary、语言、作者身份、推广与 footer 检查 |
| `live/distillation_client.py` | 现有 relay 配置；真实 messages、response id、模型别名/返回模型、finish reason、usage、时延、失败日志；无自动 fallback |
| `live/writer_backend.py` | 保留完整结束状态与响应元数据；请求正文通过 stdin 传给 curl |
| `ml/budget.py` | 新调用预留预算，失败/未知 usage 保留估算，响应后结算；未改变额度 |
| `live/analysis_corpus.py` | 去掉 4,000 截断、原文空白折叠和入库关键词丢弃；feed 只选一个正文域，保留段落；不可变 snapshot + 最新索引；读取 enabled registry |
| `live/source_registry.json` | 仅迁移已有 9 个 X、32 个 feed 为 enabled；没有新增订阅，候选仍关闭 |
| `live/accounts.json` | 既有四账号显式 enabled、语言、筛选范围、glossary、轻本地化偏好；不把旧 donor 文风要求传入新 writer |
| `live/production.py`, `live/queue_store.py` | 默认新数据流；正式 account_id/target_language/stage refs/draft_version；先排除处理过的版本，再取源配额；所有失败留痕，下一轮不自动重复付费 |
| `backend/assets.py` | 从新队列读取稿件、状态、原文/译文/轻编对照；不虚构旧 sentence ledger |
| `frontend/workbench.js`, `frontend/workbench.css` | 显示账号/语言、人审状态和三栏对照 |
| `scripts/run_distillation_fixtures.py` | 四案例真实调用的隔离 runner；不把 expected decision/选段答案传给模型 |
| `scripts/check_distillation_mutations.py` | 从真实 fixture 输出构造反例；先确定性检查，必要时调用真实语义 QA |
| `scripts/check_minimal_localization.py` | 固定既有源/路由/译文，只实测轻编与 QA：零改动、局部语法修正和正文编辑解说反例 |
| `tests/test_distillation.py` | 明确标为 TEST_DOUBLE 的离线契约、反例与集成回归 |
| `tests/test_production_queue.py` | 给旧固定日期样本固定时钟，消除 24 小时窗口导致的时间漂移失败 |
| `CLAUDE.md` | 顶部写明当前定义，覆盖旧“重组/独立创作/禁止逐句翻译”等冲突规则 |

调用账本在 `ml/store/spend.json`、`ml/store/distillation_spend.jsonl`，逐次请求和失败在对应 `runs/localization_v1/*/artifacts/calls`。价格按配置表估算，并非真实账单。模型别名不证明 relay 底层实际模型身份。

## 用法

```sh
# 离线契约测试，不联网、不写生产数据
.venv/bin/python -B -m unittest discover -s tests -p 'test_distillation.py'

# 显式、隔离的四案例真实调用；out 必须是新目录
.venv/bin/python -B scripts/run_distillation_fixtures.py --live --out runs/localization_v1/my-run

# 正常生产入口（本轮没有执行）
.venv/bin/python -B live/production.py --once --limit=20
```

本机继承的代理指向不可用的 `127.0.0.1:7897`，本轮真实调用只在测试进程中移除 HTTP(S)/ALL_PROXY 大小写变量直连。未修改系统代理或 `.env`。正常生产仍继承启动它的网络环境。

## 验证与限制

模型输出、失败、重试均保留；不得把人工改稿称为模型原始输出。`draft_ready` 只代表机器检查通过、可供人审；自然表达和保真的真人评审仍为 pending。

### 轻编边界更新（prompt v1.4 / pipeline v1.1）

轻编信任已有译文，不重新翻译、概括、限定或重述逻辑。自然句子原样保留；顺序、强调、例子和论证节奏只在目标语言确有障碍时才调整。账号偏好不构成重写自然表达的理由。

LOCALIZE 只返回 `edits` 与空的 `added_background`；每条 edit 包含 `paragraph_id`、`before`、`after`、`reason`、`source_support`，不再返回 `segments`。`before` 必须在该段原始译文中精确且唯一出现，不能重叠、依赖前一个替换结果或删除整段。代码计算段内 Unicode offsets 并执行替换，所有未选中文字逐字保留。空 edits 是严格零改动。编辑必要性仍由语义 QA 判断，精确替换本身不是保真证明。

QA 新增 `minimal_edits`、`order_emphasis_rhythm_preserved`、`no_editorial_commentary` 三项硬门槛，缺失或 false 都不出 ready 稿。理由和核对说明只写 metadata/review；正文不得出现“这个判断有依据/有条件/原文没有”等编辑解说。真实的 if/may、因果和否定仍应保留，不做关键词禁用或自动删除。QA 不回写正文，也不再要求为含义已清楚的指代额外添加主体名。

历史 audit fixture 和真实调用产物保持原样。原长文合成 fixture 自身含有测试说明式句子（如“Adding any of those would introduce a new view”）；不能把其旧译文里的这些句子误报为轻编模型凭空新增。v1.4 使用单独的聚焦样本验证上述边界，不把旧四例结果冒充为新 prompt 的真实验收。

路由/QA 的模型自报 confidence 仅记录为诊断，不用未经校准的 0.8/0.85 阈值替代明确判断与证据。显式 NEEDS_REVIEW、未知语言、非法账号/语言、缺失正文、无效选段、漏对齐、空稿/拒绝/截断、确定性不一致或任一未解决语义缺陷仍会阻断正文出队。初译缺陷若被轻编实际修复，QA 必须记录为 resolved 并确认最终稿各维度保真；最终稿缺陷不能伪装成 resolved。选段理由中的非正文错误保留为 metadata_note。首版没有额外自动修复重试环。

没有 production stub 给路由、翻译或 QA 伪造成功。测试里的 FakeClient 只用于离线控制流。以下是明确未启用或未完成的能力：

- **外部事实背景补充**：`added_background` 必须为空；只允许基于已给原文/标题的必要指代与术语澄清，没有伪造检索结果。
- **正文补全与复杂媒体**：不完整 feed/X、缺图表/线程、超过 60,000 字符的长文停止；没有新建通用 paywall/browser/媒体补全器。feed content 域与截断标记只是完整性的启发式证据，后续路由仍需识别缺失。历史被截断的正文不会凭空恢复。
- **同语言轻编、多于 EN/ZH 的语言**：本版明确不启用。语言识别为有限 EN/ZH 启发式；混合/未知进入人工复核。
- **全面语义保证**：确定性指标词表有限；任意实体、因果、否定和判断力度还依赖模型双语核对。四 fixture 及 mutation tests 不是总体准确率，也不是独立市场事实核实。
- **人工反馈写回**：三栏对照和 draft_version 已接入；新审核表单/API、人工修订版本合并、批准与导出权限闭环尚未实现，所有真人字段保持 pending/null。
- **发布表现反馈**：未实现自营账号 published-post ID、曝光/互动关联和回流；未把 donor 热度冒充自营效果。
- **持续调度/采集水位/语义去重**：保留现有轮询适配器和窗口，未安装 launchd，未补分页恢复或语义聚类；本次只做稳定内容/选段/账号版本去重。
- **legacy 清理**：旧 daily/write/crosslang、event writer、分析辅助及历史素材保留；它们没有被全部改造成新流程，也不参与新主链。旧测试的通过不代表新产品验收。

这次刻意没有迁移历史稿、没有启动训练/多模型 A/B 实验、没有新建数据库或 agent 编排、没有新增账号、没有全量回跑或发布。
