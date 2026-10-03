# 三个账号的信息世界与 source discovery 计划

本方案确认于 2026-09-30；文档状态核对于 2026-10-02。**当前范围、优先级与待办以 [CURRENT_DELIVERY_PLAN.md](CURRENT_DELIVERY_PLAN.md) 为准。** 下文保留账号独立信息世界的方案及当时发现的缺口，不应按旧阶段文字重复执行已完成批次。

已交付的内容批次是 **15 条自动非空候选，三个账号各 5 条；7 条 machine pass、8 条 hold**，见 [审稿包](../runs/content_batch_v2/review/REVIEW_PACKET.md)、[机器可读结果](../runs/content_batch_v2/review/packet.json) 和 [批次交付](../runs/content_batch_v2/DELIVERY.md)。每个账号的 5 条生成稿 + 5 条公开参考帖盲包也已准备。原先冻结的 **12 个 follow-up 已全部执行**，见 [completion.json](../runs/content_acceptance_followup_v1/completion.json)，不能继续笼统列作未跑完。以上均不代表内容质量通过：本次只读核对的人审记录仍为 **0**；后续以实际 Store 和绑定版本的审核记录为准。

账号订阅、独立 inbox、成稿优先审稿与首稿人工 KPI 已接通。**P0 日常运行验收仍未完成**；最近交付快照为 [2026-10-01 21:36 UTC acceptance.json](../runs/account_monitor/p0_relay_live/acceptance.json) 与 [运行交付](../runs/account_monitor/p0_relay_live/DELIVERY.md)，不能把历史回放或已有批次当作三个账号当前稳定出稿的证明。服务状态、后续周期和预算会继续变化，运行方式见 [ACCOUNT_SOURCES.md](ACCOUNT_SOURCES.md)。

有界 discovery 报告已经交付：27 个 source/account 提案、103 个例子、40 个 X 查询、277 个唯一帖，见 [SOURCE_DISCOVERY_REVIEW.md](SOURCE_DISCOVERY_REVIEW.md)。这些是当时的采样证据；完整长期覆盖、总体 signal density/timeliness 与第二层引用网络仍未完成，保留为延后 backlog，不因本轮状态整理而取消。

**历史阶段：** [completion_v2 原文对照](../runs/account_sources_v1/completion_v2/REVIEW.md) 和 [当时交付](../runs/account_sources_v1/completion_v2/DELIVERY.md) 记录更早的三篇 Codex-assisted 候选、原自动 localization 拒绝与 F04 零调用停止。F01/F02 当时 hold、F03 独立 QA 通过；四次补充 QA 请求三次完整返回、一次长度中断，BLS 仅增加输出上限而 messages 不变。原失败和辅助生成身份保留，不与后来的自动稿混算；该阶段“自动最终稿为 0 / 盲审四条”不再是全项目当前数量。未经真实人工反馈，不据机器自评调写作 prompt。

本文件取代 `OWNED_ACCOUNT_INTELLIGENCE_PLAN.md` 中的全账号事件广播、Morris 泛 frameworks 定位及事件优先审稿入口。旧实现和评估保留为历史记录，不能被当作本方案已完成的证据。

## 1. 先确认三个账号各自在看什么

以下是**拟议订阅角色**，不是已经通过 source quality audit 的推荐榜。出版物和人物来自用户指定范围或 repo 现有库存；当前覆盖与缺口见下一节。此次只确认三个核心账号，`en_macro`、`en_industry` 保留原记录，不进入本轮订阅扩展与生成。

| 账号 | 目标读者 | 主要内容 | 核心 source | 辅助 source | evergreen source | shared primary sources | 不应该看的 source |
|---|---|---|---|---|---|---|---|
| `en_morris_archive` · EN Morris Archive | 希望读到有价值中文历史分析的英文读者 | Morris 历史内容中今天仍值得看的框架、解释、行业判断；自然英文翻译与轻编辑 | **仅 `@Morris_LT` 历史中文原创**；按主题和历史时段整理，不用热度搜索代替历史库 | Morris 原帖引用的原始材料、完整 thread / quote / media；只为理解和验证原帖补充 | 逐篇检查前提仍成立的 Morris 历史段落，保留原有逻辑、例子、力度与节奏 | 按所选原帖需要查询公司材料、官方数据和当前事实；这些材料不独立触发该号出稿 | 泛金融实时新闻池；其他 KOL 作为该号正文主来源；以个人持仓、收益、经历、CTA 或已失效即时判断为核心的内容 |
| `zh_macro` · 中文 Macro / Data Flow | 需要理解宏观数据、政策与市场资金机制的中文读者 | 政策、通胀、就业、利率/外汇、流动性、定位、波动率/期权、资金流与市场运行机制 | 主动订阅 BLS/BEA/Fed/Treasury 的相关发布；研究候选为 The Overshoot、Liberty Street Economics；flow/positioning 专业源另做证据筛选 | Chartbook、Claudia Sahm、Nathan Tankus、Conks；中文 qinbafrank / HAOHONG_CFA 仅按匹配主题选入；均待代表性内容审计 | 经日期/口径核对的宏观机制、货币管道、周期与仓位/波动率框架，不能把旧行情当今天 | BLS、BEA、Fed、Treasury、IMF 等原始数据及必要市场数据；订阅的发布可形成 Macro 候选，访问权限不等于广播 | 半导体 channel checks、产品评测、无宏观/flow 机制的单公司帖子；喊单、钱包播报、泛新闻搬运与无关日常 |
| `zh_industry` · 中文 Stocks / Industry | 关心公司经营、产品与产业链机制的中文读者；首批聚焦半导体与 AI 基础设施 | 财报、单位经济、产品、产能/供需、芯片/光通信/数据中心/电力的具体约束与取舍 | 关注公司的 IR/filings/earnings/investor day；用户指定的 SemiAnalysis、Fabricated Knowledge 为重点审核对象；后者当前缺实采正文 | 相关主题的 Stratechery；Claus Aasholm、The Semiconductor Engineer、Next Platform、ServeTheHome；dylan522p 等专业人物候选。按主题接入，不全收 | 经复核仍适用的产业链解释、技术/商业模式、公司历史案例；旧估值/供需数字保留历史属性 | 公司原始披露、官方技术材料和所需统计数据；BLS/Fed 只在行业来源明确建立相关机制后按需引用 | 裸 BLS/Fed 事件默认候选；泛宏观/加密行情池；无产业证据的热门股票情绪、持仓截图、referral 与传闻搬运 |

“不应该看”指**不进入默认内容候选**，不是阻止按需核查原始事实。不存在一份所有账号都要评估的大 event pool。

中文 Macro 和 Industry 可以使用中文及英文来源；输出语言由账号确定。同语言材料符合独立订阅和选题价值时可轻编，不必为了跨语言标签强行改投其他账号。Morris 则明确为历史中文 → 英文。

## 2. 实施前审计快照（历史基线）

本节记录计划确认时的实际缺口；后续代码、采集与人审入口的当前状态以文首和 completion_v2 交付为准，不能把本节旧描述覆盖最新结果。

| 核对项 | 实际证据 | 尚未实现 / 不能据此声称的能力 |
|---|---|---|
| 订阅与语料 | `live/source_registry.json` 共 84 条、41 enabled（9 X、32 feeds）；顶部仍标 `candidate — 未做 source QA`。`live/store/analysis_corpus.jsonl` 有 220 条、54 个 source ID；41 enabled 中 38 个有历史行 | 不等于 41 个 source 均有完整正文、连续覆盖或通过质量审计。Acquired、Fabricated Knowledge、Lyn Alden enabled 但此 corpus 无行；旧 schema 的完整性还需核对 |
| 另一套 X 采集 | `live/sources.json` 有 12 个 watchlist、50 个 learning accounts；`live/store/posts.jsonl` 有 5,206 行、62 handles | watchlist / donor learning pool 不是账号自己的订阅。donor 分类、风格/习惯统计不是 source quality 标签 |
| Morris | `runs/content_workbench_v1/morris/sources.json` 有 58 条作者匹配记录，coverage 明确为 60 个排序搜索结果，非完整历史，可能缺 thread 上下文 | Morris 未进入 standing registry/watchlist；不能声称已有完整、代表性的 evergreen archive。主题、年份和媒体完整性需要补齐 |
| Macro 现有正文线索 | Overshoot 2、Chartbook 6、Liberty Street 3、Claudia Sahm 3、Nathan Tankus 1、Conks 4 条历史 corpus 记录 | 数量只说明可开始检查，不能代表长期 originality、signal density 或领先性；flow/vol/positioning 专业覆盖尤其需要补 |
| Industry 现有正文线索 | SemiAnalysis 7、Stratechery 6、Claus Aasholm 3、Semiconductor Engineer 6、Next Platform 6、ServeTheHome 6、dylan522p 5 条历史 corpus 记录 | 抓取片段、付费墙、图表和来源身份要逐条核查；Fabricated Knowledge 不能按“已接通全文”处理 |
| 官方/新闻采集 | `live/news.py` 配置 10 个 feed；`news.jsonl` 有 652 条历史行，包括 Fed/SEC；条目是标题和最多 2,000 字 summary | 不是完整 primary evidence layer；这里没有 BEA/Treasury/IMF adapter，也未形成上述账号订阅关系 |
| 人工反馈 | `live/account_intelligence.py:247` 保存实际原稿、改稿、理由、维度和 edit distance | 未直接记录“无需修改/小改/大改”，未做按修改范围归因的错误统计；edit distance 不能代替人工判断 |

额外的材料完整性问题：220 条 analysis corpus 中 57 条恰好 4,000 字符，均没有 `content_complete` 字段；这是需要追查截断的信号，不能按完整长文进入翻译。Morris 58 条中 56 条为 `original_or_unknown`、quote 关系为空；部分历史记录实为第三人引语或视频转述，**发帖账号归属不等于观点/经历归属**。需要还原实际说话人，不能默认全部是 Morris 原创 framework。旧 donor inventory 的“usable”是另一任务的风格语料判断，也不等于本轮 source quality 审批。

以下只是可追溯的本地审计起点，**未在本轮联网核验，也未认定完整、正确或可发**：

| Source | 本地保存的内容例子 | 原始记录位置 |
|---|---|---|
| Morris | `2104013330457452688`：重复、测试、反馈与方向选择；`2105134067033469051`：组织赋予的价值与可迁移能力；`2104054942361395309`：秩序过渡中的价值链 | `runs/content_workbench_v1/morris/sources.json` 按 ID 定位，均为 2026-09，不证明多年覆盖 |
| Liberty Street Economics | *Treasury Trading at the Close*；*Who’s Borrowing and Lending in Repo Markets?* | `live/store/analysis_corpus.jsonl:21`、`:89`；分别涉及国债收盘/定价时点、repo 参与者 |
| The Overshoot | *The Fed Finally Gets It*；*Just Waiting for Disinflation is Not Enough* | 同文件 `:30`、`:103`；需要回看完整论证，不能只读标题 |
| Conks | *Money Market Snapshot*；*The Repo Dark Spot: Part I* | 同文件 `:48`、`:66`；另一个 infographic 样本正文很短，需检查图像依赖 |
| SemiAnalysis | *ClusterMAX 3.0*；*Datacenter Moratoriums*；*Intel Panther Lake Teardown* | 同文件 `:1`、`:26`、`:73`；GPU cloud、限制/延期口径、芯片工艺与封装 |
| Claus Aasholm | *The Brightest Star of the Constellation*；*Semiconductor Supply Chain on the Edge?*；*The Comms Company Formerly Known as Broad* | 同文件 `:6`、`:36`、`:45`；公司组织、季度供应链、Broadcom business model |

实际错误入口：

- `live/analysis_corpus.py:367` 从全局 enabled registry 取 sources；`:743` 是最近 24 小时、每源最多两条的全局 intake。已有 `source_ids` 参数可复用，`live/production.py:781` 当前没有传入账号订阅过滤。
- `live/distillation.py:174` 仍是 source 先到、再从跨语言账号中路由；旧 `live/accounts.json` 只有 Morris 的独占 handle 边界，Macro/Industry 没有来源清单。
- `live/account_intelligence_pipeline.py:199` 的 `event_all_accounts()` 遍历全部账号；`scripts/run_account_intelligence.py:192` 未指定账号也逐个运行；`live/account_intelligence.py:42` 读入全部 charters，不能把它描述为已经正确遵守 enabled 边界。
- `live/owned_accounts.json:5` 与正确的旧 `live/accounts.json:31` 冲突：前者把 Morris 改成 Market frameworks / one research input。`live/account_intelligence_pipeline.py:143` 要求 `value_beyond_translation` 非空；代码没有直接检测是否新增观点，但这个产品门槛可能诱导额外分析，不该用来要求 Morris 新增结论。
- `frontend/account-intelligence.html:5`、`frontend/account-intelligence.js:23` 默认围绕事件和所有账号的 decision 展开，稿件与操作在后面。
- `live/research_sources.json` 仍有“不得逐句直译”、旧 SemiAnalysis feed rejection 等陈旧文字。**Python 当前没有加载这些字段**；不能把 catalog 注释误报为在执行的 production prompt。后续整理时退役此重复目录的过时规则。

## 3. 最小的数据流纠正

```text
账号 + 已确认的 source universe + topic scope + 该账号历史选题/素材
    → 从自己的订阅范围获取新内容（Morris 从历史主题/年份范围取内容）
    → 该账号自己的 candidate inbox
    → 值得处理？需要补齐原文或核对历史前提？
    → 选定完整原文范围 + 编辑处理判断 + 身份/时效注释
    → 目标语言翻译，或同语言轻编
    → 必要且有依据的少量本地化
    → 私有 fidelity / identity / 时间 / 数字检查
    → source → final draft → 风险 → 人工 approve / edit / reject
    → 该账号的真实修改、选题反馈与素材历史

共享 primary evidence / 原始内容缓存
    ↳ 被订阅或被具体候选按需引用；不触发 all-account fan-out
```

物理抓取和不可变原文缓存可以去重共享；**订阅关系、候选资格、选题与审稿必须按账号分开**。两个账号各自订阅同一 source 并各自选中同一事件，才形成自然重合。素材“已处理”的去重也必须带 account_id，不能一个号看过就让另一个号失去素材。

复用现有 registry、`intake(source_ids=...)`、原文/精确范围存储、source hygiene、翻译轻编阶段、relay 日志预算、人工 review 与版本控制。先用一个小的 `live/account_source_universes.json` 显式保存三份订阅及 topic 条件，不引入推荐平台、图数据库或新 domain framework。

最少需要表达：

- 每条订阅：`account_id`、`source_id`、`role`、`topic_scope`、`candidate_policy`（日常/主题或事件触发/仅核查/不入队）、`enabled`、`audit_ref`、配置版本。Shared primary 的访问权限与自动入队权限分开。
- 每个候选：`account_id`、`source_version`、`subscription_ref`、`universe_version`、入队依据、材料/时效完整性；跨账号相同事实可以引用同一 source/event ID。
- 每次处理：账号确定的 `target_language`，原文 `source_language`，选段 exact spans 与原文全文引用，treatment、必要补充及依据、私有 hygiene/QA 结果。
- 每次审阅：原稿与实际改稿版本、人工 edit class、修改片段/理由、错误类型；机器结论与人工结论分开。

`CORE / SECONDARY / EVENT_ONLY / RESEARCH_ONLY / WATCHLIST / REJECT` 是**针对某账号的角色**。CORE 日常进候选；SECONDARY 按 topic 命中；EVENT_ONLY 仅满足已写明的事件条件；RESEARCH_ONLY 只作上下文，不独立出稿；WATCHLIST 只采样观察；REJECT 不订阅。Evergreen 是内容时效属性，shared primary 是事实访问层，不能混成一个优劣排名。

## 4. Morris 的明确处理边界

1. 主来源始终是 Morris 历史中文内容。人工筛选今天仍值得看，加自然英文翻译与轻编辑，本身就是该号的价值；不要求每篇增加“自己的结论”。
2. 对论证依赖的行业事实/时间前提作当下复核；纯框架不为凑验证而加当期新闻。复核过程、证据范围和不确定性留在后台，公开正文不写审计说明。历史例子不是因为旧就删除，也不能把旧数字悄悄替换成当前数字。
3. 原文、作者、时间、链接、完整 thread/quote/media 关系及持仓/钱包/个人经历/CTA 等 annotations 保留。编辑判断哪些可独立删除，哪些是逻辑必要部分。模式命中不等于应删，例如“出现在”中的“现在”不能机械改写。
4. 以个人经历、持仓或当时即时判断为价值主体的帖子不进入本号 evergreen 队列。若这些内容是某一论证不可缺的依据，不能剥掉身份/前提后冒充通用判断：选取完整独立段落，或 hold/skip；不为凑出稿硬处理。
5. 正文不默认 `Morris said...`；有必须保留的引用/说话人关系时准确处理，不能转成账号自己的经历。作者/URL/provenance 后台可见。
6. 选中原文完整进入翻译和轻编；不经 summary/brief 替换。已经自然的译文不改，保留顺序、例子、判断强度与节奏。NONE/skip 无 writer 调用；缺上下文是 hold，不是编造补齐。

## 5. Source discovery：先取证，再决定订阅

### 第一轮范围与执行方式

先确认第 1 节的三个信息世界。之后各自开展小批量发现，**不立即扩大为 400 个账号**：

- Morris：不扩 donor；先按年份/主题补有代表性的历史内容，补齐高价值候选的上下文和原始引用。58 条排序搜索结果仅是线索。
- Macro：从当前有正文线索的研究源和用户偏好的 seeds 起步，优先填 positioning、options/vol、rates、liquidity、fund flow、market plumbing，以及中文市场机制的缺口。
- Industry：先审 SemiAnalysis / Fabricated Knowledge / 公司 primary materials；再从已存材料的引用网络找工程师、供应链、光通信、datacenter/power 等互补来源，减少同一新闻的重复覆盖。

每个主题先做约 10–15 个候选的有界采样；证据不足就降低 confidence/保留 WATCHLIST，不用凑满 shortlist。采集前核对 repo 的当前 collector、端点、时间窗口与访问能力。X API 优先保留可追溯的 IDs/时间/引用关系；Grok 若用于发现，只产出待核实线索，不作为“读过该账号历史”的证据。付费批量采集单独使用真实 provider 估价与已有授权范围，不虚构成本或覆盖。此轮未调用二者。

### 内容抽样与证据包

对候选检查连续近期窗口，例如先覆盖 6–8 周；高频账号按周分层抽样，低频 newsletter 向前延长，记录实际覆盖区间、抓取分母、缺失/受限内容。再取较早的 framework 与事件案例，判断持续性。**只挑 2–5 条最佳帖子不足以估计 signal density。**

逐项检查 originality、signal density、持续覆盖的 subdomain、引用的 primary evidence、相对原始发布的时效、framework value、另一语言生态中的稀缺性，以及广告/referral/地址/CTA/未经证实传闻。原创评论不能仅凭 original/quote 平台类型机械判断；有原创分析的 quote 与无增量转发分开。未知 timeliness、不可见图表/付费全文记 unknown，不能自动打低质量分。

每个高优先级候选必须有：handle/name、platform、language、domain/subdomain、信息类型、**2–5 个具体历史内容例子**（URL/ID、日期、内容概述、关键原文范围、可追溯证据）、样本窗口及分母、originality、noise、timeliness、cross-language value、account fit、role、confidence 和限制。所有推荐落到“适合哪个账号、哪个主题、什么触发条件”。

跨语言价值要抽查另一语言社区是否已有等价原始解释，记录查询和时间；不能仅凭中文/英文标签或搜索无结果声称“信息差”。高优先级推荐必须能回到实际文本，不用 follower count 排序。

### 引用网络与多样性

沿 seeds 的引用、回复、quote、推荐、文章参考资料和 conference/podcast/video 嘉宾扩展，区分赞同/批评/简单互动、独立引用与同一转载链。找到比放大账号更早的原始材料。用保留原帖链接与日期的边表即可，不建新的 graph service。

首轮内容审计后，对最好的最多 10 个候选再扩一层：他们引用谁、谁是上游、谁被多条独立来源重复引用。专业网络里的引用中心性只是候选信号，仍要读内容；不能用互推、互喷或转发团伙代替质量。若只有 6 个有足够证据，就审 6 个。

Shortlist 主动覆盖 primary/official、researchers、practitioners、investors、engineers、industry specialists、data/flow、independent writers、niche small accounts；不是每类硬凑人数。对内容重合的作者/跨平台身份做归并，并说明各自的新增信息。粉丝少的 hidden gems 必须真的有可核对的规模及内容证据，未知则不贴标签。

### 本轮确认后应交付的 A–F

| 输出 | 必须包含 |
|---|---|
| A. Top candidates | `Account / Platform / Language / Subdomain / Originality / Signal density / Timeliness / Cross-language value / Fit / Recommended role`；Account 此处是 source handle/name，Fit 明确 owned account；每行链接上述证据包 |
| B. Hidden gems | 专业引用与实际内容为何有价值，规模观察日期；不按“小号”自动加分 |
| C. Redundant accounts | 重叠主题/材料、共同上游、保留其一或分 topic 订阅的原因 |
| D. Rejects | 对具体 owned account 不合适的证据与原因；不把“不 fit”混为作者总体质量低 |
| E. Missing source types | 三个 universe 各缺哪些信息，以及信息缺口会影响哪些选题 |
| F. Suggested next seeds | 下一层 handle/source、由谁引用、对应原帖与待解决的覆盖问题 |

**这些是待执行的研究交付，不是假装已完成的榜单。** 第 1 节确认的是账号定位及初始 source 方向；有代表性内容审计后才确定正式 CORE/SECONDARY。审核通过的 sources 先写订阅提案，不在发现时自动启用。

## 6. 成稿优先的审稿与真实质量指标

默认入口选择账号，随后看到该账号待审稿：**source（选中范围可直接对照全文）→ final draft → 简明风险 → approve / edit / reject**。三个操作直接可见。风险写具体受影响句子和原文证据；详细机器 reasoning、决策理由、QA JSON 折叠。wait/ignore/未完成材料在独立次级列表，不占默认稿件流。

主要 KPI：

`首轮人审确认可原样发或只需小改的稿件数 / 同一固定批次已完成首轮人审的稿件数`

- 分账号、语言、长短文显示；同时显示批次总数、已审/待审、reject/大改/执行失败。不能只审或统计 machine-pass 稿件；失败与无稿另报，不冒充质量通过。
- “小改”由人判断：只是局部语言/必要删减；需要重选范围、重建推理、改变事实/身份归属的即使字符改得少也不能算小改。原样发与小改分别报，不靠 edit-distance 阈值推断。
- 每个初始稿只计一次首轮结论；后续修订通过不能倒写初稿 KPI。人工实际 edit spans、原因和错误类型关联原始 candidate/version；可记录审稿耗时和改后结果。
- 错误类型至少包括选段不全/过宽、推理/例子丢失、力度改变、新增观点、数字/实体、身份转移（含 guidance）、审计口吻、母语不自然、旧时间/媒体/CTA 和 account fit。
- Machine fidelity 是独立列，只说明检查结果；人工质量不是模型评分；human approve 也不等于已经发布。

盲测是辅助指标：将候选稿与**真实优质账号内容**按语言、主题、格式、篇幅和时间背景匹配混排；保存真实来源与隐藏答案键，去掉会泄露组别的 UI 标签，不能改坏真实文案或冒充指定作者。请读者评自然度/可发性，再判断是否像 AI 并给 confidence；同时报告两组被判 AI 的比例（含真实文误报）和组内样本量，不能只报候选稿“未被识破率”。现有 `BLIND_COPY.md` 只有候选稿，不算完成了该盲测。

人工审阅完成后，先按反复出现的问题归纳（频次、严重度、原文与修改例子、账号/来源/阶段分布），再提出最小代码或 prompt 变更。质量样本采集期间冻结生成配置；确实不能执行的修复另留版本和 follow-up 身份。不能用机器自评造人工标签。

## 7. 实施顺序与可验收结果

| 步骤 | 做什么 | 验收 / 边界 |
|---|---|---|
| 0 · 本轮 | 核对实存 sources 与接线、给三账号确认表、替代冲突计划 | 本文件及旧计划/运行说明的 superseded 标记；未改运行时、未新出稿 |
| 1 · 用户确认信息世界后 | 执行有界 source discovery/content audit，给 A–F 与每账号订阅提案 | 高优先级每源 2–5 个具体例子 + 代表性样本；明确已接通/待补全文/未验证，不拿名单当能力 |
| 2 · 最小接线改造 | 复用 registry/intake，加 account-scoped subscriptions/inbox；恢复 Morris source adaptation；移除默认 all-account 执行；兼容同语言轻编；收敛重复账号定位 | CLI/API 缺 account/candidate subscription 不能默认全遍历；现有五 ID 与历史结果保留；新入口只启用确认的三号；新 desk 不得调用旧全局生成入口绕过账号订阅边界 |
| 3 · 审稿入口与标签 | 把 source/成稿/风险/操作置前；添加人工改动等级与具体修改记录 | 核对真实原稿与改稿、首轮 KPI 和 pending 分母；不强制每天出稿 |
| 4 · 小批真实验收 | 在确认的来源内出小批真实稿，冻结配置，人工审阅；known fixtures 重用身份并保留 follow-up 关系 | 来源忠实度与可发性分别验收；输出全文与 stops，不拿通过测试代替内容验收 |
| 5 · 反馈总结 | 汇总主要错误与代表性人工修改，再建议改动 | 没有人工结论就明确待审，不自动继续 infrastructure/FT/新 domain |

计划涉及的最小文件范围：`live/owned_accounts.json` / `live/accounts.json`（统一定位，不再相互冲突）、一个三账号订阅配置、`live/analysis_corpus.py` / `live/account_intelligence_pipeline.py` / `scripts/run_account_intelligence.py`（账号候选入口）、现有翻译轻编接入、`backend/account_intelligence.py` / `frontend/account-intelligence.*`（稿件优先）、`live/account_intelligence.py`（真实修改标签与统计）。`live/production.py` 的旧全局生产路线此轮不切换；新 desk 必须使用显式隔离的账号入口。

生成 prompt 的边界：保留 source-first、translation-first、轻编、silent QA；退役 Morris 的“必须有翻译之外的新角度”和默认 original commentary 要求，不以新增观点满足门槛。先完成必要接线变更，再冻结评估；不能一边收结果一边调 prompt。发现阶段不需要生成文章。

## 8. 最小回归与内容验收

| 场景 | 技术回归 | 人工验收 |
|---|---|---|
| BLS 原始就业发布 | 只有订阅它的 Macro inbox 收到；Industry / Morris **没有 candidate、没有 decision / writer 调用**，而不是跑一次再 ignore | Macro 是否有值得发的解释；无新增论断、审计口吻 |
| SemiAnalysis / 公司行业来源 | 进入 Industry；不默认进入 Macro；只有完整原文才可选段 | 选段保留技术推理、条件、取舍和例子 |
| Industry source 明确连接就业与公司机制 | Industry 因自己的来源形成 candidate，并按需引用共享 BLS；记录自己的 admission 来源 | 不是靠“债券/公司”等关键词牵强拉题 |
| Morris 历史 framework → 英文 | Morris inbox；复核时效与上下文；选段原文完整传下游；其他作者无法替代主来源 | 自然英文，原有顺序、力度、例子；无泛化重写、默认作者前缀或身份冒领 |
| Morris 个人持仓/过时即时判断/缺视频论证 | annotation 不毁原文；必要依据不可分时 hold/skip，无 writer | 没有删去前提后形成虚假 evergreen |
| 账号独立订阅同一 source | 可自然产生两个 account candidates；分开历史与素材状态；未订阅账号不参与 | 两个账号是否分别真的有理由选它 |
| 明确不适合的 source | NONE/ignore 终止；hold 也无 writer；不能通过默认 API 绕过入队范围 | 无强行金融化、无 filler |
| 人工修改与拒稿 | 原始版本/实际修改/首轮标签可还原；不能复用旧 machine pass；待审不计 accepted | 修改理由能定位到问题；小改比例反映实际工作量 |

旧英文长文→中文、英文短帖→中文、中文→英文、SKIP 四类 fixtures 保留原始身份；需要重跑时追加 follow-up，不覆盖历史失败，也不再为每个 fixture 乘以所有账号。技术检查只验证订阅隔离、原文传递、停止控制与记录正确；最终以真实人工可发性和自然度判断内容完成。

以上步骤表记录最初确认点的计划；用户随后已授权执行。当前实施以文首状态及 [CURRENT_DELIVERY_PLAN.md](CURRENT_DELIVERY_PLAN.md) 为准。`runs/account_sources_v1/completion_v2/DELIVERY.md`、`results.json` 与 `apify_followups/` 保留较早阶段的辅助稿及自动评估停止结果，其中“未安装调度 / 未切入口”等描述不能覆盖后续运行交付。真人混合盲测、人工内容验收和完整长期来源覆盖仍未完成；没有账号自动发布或训练。
