# 三账号日常运行链

当前范围是 `en_morris_archive`、`zh_macro`、`zh_industry`，最终动作是保存到人工审稿台。自动发布始终关闭。累计预算上限 $100；每天每号 3 条是执行上限，不是必须完成的配额，后续 QA 续检不应当作一篇新帖。

## 实际链路与持久状态

```text
账号的订阅名单 / topic scope
  ├─ KOL、newsletter、行业分析 → 增量内容候选
  ├─ Morris 已保存历史库 + 追加导入 → 未消费历史候选
  └─ 官方发布 → 单独保存事实背景，不进入全文翻译候选
              ↓
账号 + source 的 cursor、原始抓取、日期、完整性、去重身份
              ↓
账号自己的 inbox → 值不值得搬 / 是否适合 → NONE 停止
              ↓
完整原文选段 → Morris evergreen 检查（如适用）→ 身份与来源注解
              ↓
目标语言翻译 / 同语言原文底稿 → 最小轻编
              ↓
确定性核对 + 模型 QA → 成稿或具体 hold
              ↓
同一 Store 自动进入对应账号审稿台 → 人工接受 / 修改 / 拒绝
```

`live/owned_accounts.json` 定义实际账号及输出语言；`live/account_source_universes.json` 定义每号订阅及内容范围；`live/source_registry.json` 定义采集适配器、feed/handle/archive 与官方入口。订阅名单并不等于对 X 平台执行关注操作。WATCHLIST / RESEARCH_ONLY 不会因为列在名单里就假装已每日采集。

`monitor.sqlite3` 保存每个账号/source 的 cursor、last_seen、检查错误，及每条内容的消费、重试、去重和父运行身份。不可变 Store 保存原文与 provenance、inbox、每次模型尝试、最终文本及人工审阅。先持久化获取内容，再提交 cursor；模型调用失败不会抹掉抓取结果。

Morris 历史内容保留实际发表时间，不改成今天新闻。历史个人经历、持仓、时间依赖和缺失图文先判断是否影响含义；不能用整体脱敏把作者前提删掉再出稿。历史观点需要当前验证时，缺少真正证据会 hold，普通网页抓取不会被当成验证完成。

## 日常运行

用户不需要手动运行实验 batch 或导入稿件。安装的两个用户 LaunchAgents 分别运行 dashboard 与持续 monitor，monitor 每轮结束后等待 1,800 秒。网页每 30 秒读取更新，保留正在编辑的文本。

- 审稿台：<http://127.0.0.1:8684/account-intelligence>
- 配置与来源状态检查（只读、无模型调用）：`.venv/bin/python -B scripts/check_account_pipeline.py`
- 服务状态：`.venv/bin/python -B scripts/manage_monitor.py status`
- 安装/重载本项目服务：`.venv/bin/python -B scripts/manage_monitor.py install`
- 一次完整循环：`.venv/bin/python -B scripts/run_monitor.py --once`
- 持续运行：`.venv/bin/python -B scripts/run_monitor.py --continuous --interval-seconds 1800`

持续服务已经运行时，另一个 CLI 会报告 `already_running`，不会启动第二个生成进程。Mac 需要处于唤醒和用户已登录状态；这不是云端 24 小时托管。唤醒/登录后沿持久 cursor 继续，不清空旧状态。

## 失败与恢复

| 情况 | 行为 |
|---|---|
| 抓取超时 / 端点错误 | 保留旧 cursor 和明确失败，其他来源继续；下一轮再检查 |
| 预览正文 / 必需图文缺失 | 保存 needs_source / blocked_source；不把片段当全文；可恢复公开正文时有界重试 |
| JSON / 截断 / 模型传输失败 | 保留调用、父 run 和有界重试；尚未用过的明确执行修复可立即就绪，已用修复继续退避，不能无限重复消费预算 |
| 余额 / 本地预算不足 | 保存等待资金状态，不消耗内容质量重试次数；不切到未经授权的服务商 |
| 已保存结果后进程重启 | 对账已有 run / candidate，恢复队列消费状态，不再生成同一篇 |
| QA 执行故障 | 锁定已有原文、选段、译文和成稿，仅续检缺失 QA；检查点不一致则阻断 |
| 数字、身份、论证等真实 QA hold | 保留成稿与具体风险供人审，不自动改写直到通过 |
| 没有值得写的材料 | 明确 no-post；失败或预算受阻与没有选题分开记录 |

预算按请求前预留、调用后结算，`ml/store/spend.json` 是本地估算账目，不是中转站余额/发票。当前生成 provider 是显式配置的 `erisedai_relay`，模型 `claude-opus-5`；取 `.env` 内现有同服务商凭据，无隐式模型 fallback。

真实续跑中出现了中文译文引号未做 JSON 转义的重复错误。`translation_json_contract` 只在已记录的 translation `invalid_json`、完整 stop 响应且非 refusal 时选用一次，提醒模型正确序列化；原翻译要求、原文、段落、目标语言、模型和 token 上限不变。它不修补收到的坏 JSON、不接纳缺失字段，也不把失败历史改成成功。每次选择都保存父 run 和修复记录。

已有 localization `length` 响应耗尽 5,000 token 且正文为空时，`localization_capacity` 可沿原身份提供一次 11,000 token 的响应上限，messages 不变。默认仍为 5,000。新支持且未用过的执行修复可令 blocked_execution 恢复一次，持久 receipt 防止重启后重复唤醒，原失败次数保留。不存在每失败一次就自动加大上限的循环。

Erisedai 请求现在显式带 `response_format={"type":"json_object"}`，调用日志和 stage configuration 同时记录。未用该请求格式的旧 Erisedai `invalid_json + stop + 无 refusal` 可以沿原父 run 获得一次 `json_response_mode` 恢复。小额接口测试接受了该参数，不代表服务商保证所有长响应符合 JSON；解析器、字段校验及保真 QA 仍严格执行，已有 JSON mode 的失败不会因同一修复无限重启。

目前只有 QA 续检能冻结并复用原稿；其他阶段的执行 follow-up 可能重新调用前面的阶段。这不是完整的全阶段断点续传。原尝试、原文、译文与调用记录均保留，后续不能把这些中间结果直接晋升为完成稿。

## 人工反馈闭环

审稿默认显示 source → final draft → 风险 → 接受/修改/拒绝。编辑判断、调用日志与机器推理折叠。机器 fidelity pass 和人工“不改 / 小改 / 大改 / 拒稿”分别记录，修改后的文章不继承原文 QA。

人工实际改动、理由、问题类型用于归纳重复错误；不会自动改变账号长期观点或 prompt。发布后可关联实际帖子和表现记录，但当前不自动发 X，也没有虚构的表现数据。生成量、测试数和服务心跳均不等于内容已被接受。

## 以后复用到其他领域

保持现在的配置和阶段边界；不另建一个 event pool：

1. 定义新账号的读者、目标语言、平台形式、主题和处理方式，建立自己的 source universe。
2. 为每个候选源保存真实内容例子与采样范围，按原创性、信息密度、证据、时效、重复度、噪声和账号 fit 审核。选为 CORE / SECONDARY / EVENT_ONLY / RESEARCH_ONLY / WATCHLIST / REJECT；名气和粉丝数不是准入条件。
3. 在 registry 配置现有适配器；新平台只有实现了真实正文/线程/媒体恢复和 cursor 语义才算支持。新增来源先检查出处、语言、时间和原文完整性，不能仅加一个 handle 就宣称覆盖完整。
4. 复用 passage → translation → minimal localization → QA → review。通过 domain policy 增补术语/数字规则，不能绕过通用保真与身份检查。
5. 为新领域至少做长文跨语言、短帖跨语言、同语言轻编、明确 SKIP、重启/去重/失败隔离验收，并用真实人审评估可发率。

目前生产 monitor 有意限制三个固定账号、中文/英文和 Morris 专用历史门禁。未来启用新领域需要显式修改运行白名单并验证适配，不是已经实现任意领域/平台的一键批量上线。逻辑 profile 也不等于注册了外部社交账号。

## 仍需保留的实际边界

- X 是有界 provider 搜索采样，RSS 是当前 feed 窗口；不能声称全时间线、完整历史或永不漏帖。饱和/缺口应当出现在来源状态。
- 同帖、同正文及明确 thread/event identity 能去重；没有通用跨作者语义同事件聚类。
- 官方页面采集是事实材料，不自动证明 Morris 的历史判断仍成立；当前验证仍需可追溯的核查记录。
- 付费墙、任意 PDF、图片/视频、完整线程等未实现通用恢复，不能推断缺失内容。
- source discovery 的已有内容样本不是完整近期分母。长期稳定性与跨语言稀缺性需要持续实际记录；本轮不另开大规模 KOL 研究。
- 真人接受率、同事盲评、发布表现只能由真实输入完成。

本轮运行、修改与验收证据见 `runs/automation_completion_20261002/`。该目录中“真实调用”“录制结果重放”“离线核对”分别标注，不能互相替代。
