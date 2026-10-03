# 当前完整交付计划

更新：2026-10-02。最新优先级：把三个账号的日常自动闭环接通，不以增加稿件数量代替完成。累计预算上限已获授权改为 $100。本页替代历史文档中相互冲突的“最新状态”；历史证据不覆盖、不重算成人工通过。

Jev 本轮增量：用户授权实现独立参考复核后，现已接入只读审稿面板、保存版本绑定和有界 monitor hook；未改变写作路径或正文。15 篇实际稿的 56 个请求已准备，**尚未实际发送**：自动审批要求明确确认这批稿件可以发往 TypeSafe，正在等待该确认；自动开关仍关闭。原日常监控继续运行，既有内容阻塞未因 Jev 接线而解决，人工验收仍为零。详见 [Jev 当前状态与范围](JEV_PIPELINE_ASSIST.md)。

## 目标与范围

每个账号从自己的信息世界挑内容，完整原文选段进入翻译与轻编，保留信息、逻辑、例子、判断力度和表达节奏，再进入人工审核。机器检查在后台，不写进正文。NONE 真正停止；没有选题时不凑配额。

当前三个运行账号：`en_morris_archive`、`zh_macro`、`zh_industry`。五个逻辑 profile 已存在，另外两个英文 profile 保留停用。Morris 是自己的历史中文 → 英文 evergreen 账号。官方发布仅作事实依据，不作为整篇待翻译帖子。按账号保存订阅、cursor、候选、消费状态与队列，不广播同一个 event 给所有账号。

## 总清单与完成标准

| 工作 | 当前证据 / 状态 | 剩余动作与验收 |
|---|---|---|
| 自动日常链 | monitor 与 dashboard 使用共享 stages；现已补官方 context 真采集、完整保存库输入、provider 恢复、QA-only 续检、原文修订/崩溃 lineage，以及有界格式/容量修复；本轮真实循环证据见 automation_completion_20261002 | 按实际循环报告确认 provider 恢复、自动入台与去重；日配额延期、源正文缺失、端点 403、QA hold 均如实保留。机器运行验收与人审分开 |
| 原冻结 follow-up 评估 | `runs/content_acceptance_followup_v1/completion.json`：12 / 12 已执行 | 不再泛泛重跑这 12 条；保留其具体机器状态和待人工结果 |
| 三账号 × 5 自动样稿 | `runs/content_batch_v2/review/packet.json`：15 条非空稿，原批 7 machine pass / 8 hold | 数量已完成。固定这 15 条供人审，不能用手工稿补数、为了机器通过改正文或换掉差稿 |
| 已知失败阶段 | I04 QA 续跑已返回，研究身份转移仍 machine hold，正文未改；本轮已沿原身份执行日常失败任务，状态见 automation_completion_20261002。原 selection 缺字段案例已推进至 translation 拒绝；另有空响应、JSON 和长度截断，不能继续统称旧失败未执行 | I04 保留原首稿与新检查供人审；实际额外执行 routing/selection，共 3 次新调用，记录于 `runs/full_plan_completion_20261002/qa_followup/result.json`。provider 已显式更换并保留 parent；拒绝不反复烧钱重试。QA-only 冻结原稿，仅续缺失检查；非 QA 执行失败可能重跑早期阶段，尚非全阶段断点续传。格式/容量修复都有独立记录。保存旧失败及 follow-up 身份 |
| 成稿优先审稿台 | source / final draft / risks / 四档评价已有；当前每号 10 条匿名下载已接通并通过真实 HTTP 逐字核验，旧四条辅助稿明确保留历史 | 已完成本轮接线；正文、机器状态和人审结论分开，不替用户点通过 |
| 人工内容验收 | 三账号各 5 条待审；实际人审 0 | 用户或同事记录“不改 / 小改 / 大改 / 拒稿”、实际改动及原因。重点看选段、身份、审计口吻、自然表达、例子/节奏/推理保留。主 KPI 以真实首稿人审计算，pending 与失败另列 |
| 同题材盲审 | 每号 5 自动稿 + 5 已发表公开帖已混排；真实评分 0 | 发参与者包给实际评审者，答案分离，记录已见稿件。公开帖不能宣称已证明纯人工撰写；参照质量/长度匹配限制保留。AI 预评不算同事评分 |
| 人工反馈总结 | 原稿、改稿、修改片段和理由的存储/导出已接；无真实标签 | 人审后先按账号、来源、阶段统计重复问题及具体例子，再提最小改动。没有真人结果时不以模型观察冒充此阶段完成 |
| source discovery 与账号信息世界 | 三份隔离订阅和 registry 已接；官方来源定时采集成 context，Morris 五份保存库合并 200 唯一身份；已有 27 个 source/account 提案、103 个例子及有界引用网络报告 | 已有报告交付；完整近期分母、长期稳定性、跨语言稀缺性、完整 Morris 历史仍未证明（200 条不等于全历史）。来源补充继续留在总 backlog，等核心内容验收后按缺口做有界补采；不把采样量当源质量，不自动扩大订阅 |
| 来源完整性与身份边界 | 原文、作者、URL、语言、精确范围、结构化 hygiene 与私有 QA 已保存 | 缺必需 thread/media、个人经历不可分、历史前提待验证时继续 hold。必要 attribution 修正身份，不能把作者经历变成账号经历，也不能默认加作者前缀 |
| 发布表现反馈 | 人工关联已发布帖与指标快照接口已有；真实 publications / engagement 为 0 | 等用户实际发布并提供可关联记录后检验回流。当前只自动入审，不自动发 X，不制造表现数据 |
| 长期可扩展性 | 已有账号语言、domain/policy、来源/provenance 与 stage 边界；`runs/content_batch_v2/TARGET_ALIGNMENT.md` 记录限制 | 本阶段做目标对齐与边界说明，不启动新领域、新语言、批量注册社交账号、fine-tuning 或旧多 donor 模仿实验 |

## 本轮执行顺序（用户最新要求优先）

1. 累计预算上限改为 $100；保留历史账目与预留，不把 100 当作稿件配额。
2. 接通真正的来源生命周期：每个账号自己的订阅与增量 cursor；Morris 消费未处理历史库并支持后续追加；官方来源定期抓取成独立事实背景，不能成为全文翻译候选。
3. 共享新 relay 入口；修复已保存 follow-up 与 monitor 的对账、provider 切换后的有界恢复、QA 执行失败的原稿续检。内容 hold 不等于执行失败，不能重写文章直到通过。
4. 用真实 source/output 修复确定性数字解析误报与身份漏报，保持写作 prompt 和冻结样稿不变。人工接受仍须真实评审。
5. 至少三轮完整循环／重放验证增量、重启、隔离、去重、失败隔离、no-post 和自动入审；把真实网络调用与记录重放清楚分开。
6. 重启持续服务，交付当前每个来源的采集状态、运行入口、恢复方式、真实阻塞和未来扩领域边界。
7. 内容人审与盲测继续等待真实输入；后续先总结重复错误，再提内容改动。后续名单扩展以每个账号覆盖缺口和实际内容证据为依据，不为了扩名单重复抓取。

新增领域的配置设计在现有 account / universe / registry / domain policy 内完成。本轮不启用更多账号，不自动注册、follow、发帖，不承诺尚未验证的跨平台适配器。未来新账号需要通过同样的来源隔离、四类内容回归和人工验收，不能仅复制 persona 名字就上线。

## 当前外部依赖与预算

- **密钥核查更正**：erisedai 配置已经保存在 `.env` 的 `REVIEW_BASE_URL` / `REVIEW_API_KEY`。原先只检查 `ACCOUNT_RELAY_*` 后称密钥缺失是错误；现已兼容现有同 host 配置对。一个原 Macro 拒绝案例已真实续跑：hygiene、translation、localization 均 200，生成中文候选，数字检查仍 hold、语义 QA 未运行。无需用户再次提供密钥；2026-10-02 已将共享默认 provider 显式切换为 erisedai_relay，凭据不变、无自动 fallback；单例 transport 成功仍不等于内容验收通过。证据见 `runs/full_plan_completion_20261002/relay_env/verification.json`。
- 原样/小改可发率、真人盲测和重复人工错误总结需要真实审阅。评审同事的收件人/渠道尚未提供；不能用 AI 评分补上。
- 累计本地预算 cap 为用户授权的 **$100**；调用前预留，按 usage 结算；当前余额见 `ml/store/spend.json`，不是 provider 账户余额。不得再次自行提高。
- Mac 必须醒着且已登录，LaunchAgents 才能持续运行；本轮没有新增云托管承诺。

## 证据入口

2026-10-02 本轮验收快照：738 项离线回归通过；保存 15 次真实即时完整循环（不是 15 个自然日），新生成最终稿为 0，旧稿对账不计新稿。最后两条 JSON-mode follow-up 保留原身份，但分别停于 hygiene / routing；正确日期已传入，仍出现模型时点判断和 hygiene 动作/理由冲突。长稿 JSON 修复、稳定新稿自动入台尚不能宣称验收通过。持续 monitor 和 dashboard 已重载并核实实际心跳；详细逐轮结果、确切输出和未完成项见 [本轮交付记录](../runs/automation_completion_20261002/DELIVERY.md)。固定 15 稿人审包不变，真人验收仍待实际输入。

- [完整日常链、恢复与扩领域边界](DAILY_PIPELINE.md)
- [本轮自动化接线与真实循环](../runs/automation_completion_20261002/)
- [审稿台](http://127.0.0.1:8684/account-intelligence)
- [固定 15 稿审阅包](../runs/content_batch_v2/review/REVIEW_PACKET.md)
- [本批内容事实与限制](../runs/content_batch_v2/DELIVERY.md)
- [日常循环上一轮实际验收](../runs/account_monitor/p0_relay_live/DELIVERY.md)
- [三账号信息世界与 source discovery 计划](ACCOUNT_SOURCE_UNIVERSES_PLAN.md)
- [本轮完整计划续作产物](../runs/full_plan_completion_20261002/)

“已实现接口”“已执行”“机器通过”“人工接受”是四种不同状态。总计划不会因为 P0 单项通过就自动完成，也不会把需要真人输入的条目静默删除。
