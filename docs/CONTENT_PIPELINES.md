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
