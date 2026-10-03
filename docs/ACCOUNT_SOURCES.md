# 账号自己的信息世界：本地运行与审稿

2026-10-02 最新日常运行说明：[DAILY_PIPELINE.md](DAILY_PIPELINE.md)。下面的固定四例与辅助实验路径是历史证据，不是每天必须手动执行的工作。

当前入口：<http://127.0.0.1:8684/account-intelligence>。

**2026-10-02 更新：用户要求恢复 P0 之外的完整交付。** 总范围、真实状态和剩余动作见 [CURRENT_DELIVERY_PLAN.md](CURRENT_DELIVERY_PLAN.md)。固定三账号各 5 条自动稿已完成，实际人审仍为 0；审稿台现已提供每账号 5+5 匿名包，I04 完整 QA follow-up 保留身份问题 hold。正文恢复后的 unknown 语言已修复，三个指定旧失败已沿原身份恢复排队；原文和发布时间不改。新入口与证据见 [本轮审稿索引](../runs/full_plan_completion_20261002/review/README.md)。下方 10 月 1 日的唯一 P0 范围及运行计数为历史快照，不代表当前完整任务清单。

2026-10-01 当前唯一 P0 是持续监控到人工审稿的运行链。`scripts/run_monitor.py --continuous --interval-seconds 1800` 和账号 dashboard 共用 `live/content_stages.py` 的已验证 Apify / Claude 配置；旧历史页生成入口已停用。每个账号独立订阅、cursor、消费记录、重试和队列。新成稿直接写 dashboard 的同一 Store，页面每 30 秒更新队列，不替换未保存的人审正文。**21:00 UTC 后用户已授权累计 cap $60，真实生成已恢复；本轮四轮实际周期已完成，32 个自动 run 产出两条 Morris 英文稿；Macro/Industry 仍有服务商拒绝/selection 协议错误，P0 未完成。见 `runs/account_monitor/p0_relay_live/DELIVERY.md`。不能把回放的成稿当作本轮真实新稿。**

**密钥核查已更正**：erisedai 配置本来就在 `.env` 的 `REVIEW_BASE_URL` / `REVIEW_API_KEY`，不是缺密钥；真实 `/models` 已返回 200。共享 stages 只按显式 `ACCOUNT_CONTENT_PROVIDER=erisedai_relay` 选择服务商，不隐式 fallback。可用完整 `ACCOUNT_RELAY_BASE_URL` / `ACCOUNT_RELAY_API_KEY` 配置覆盖；两者均未设置时，仅允许读取指向 `api.erisedai.com` 的现有 REVIEW 配置对，禁止跨 namespace 混用 URL/key。模型固定 `claude-opus-5`。密钥不进入调用日志；当前完整失败案例验证见 `runs/full_plan_completion_20261002/relay_env/`。价格采用保守估算，累计 cap 不等于实际 relay 余额。

两个用户级 launchd 服务已安装并实际启动，终端退出后继续运行、登录后自动启动。服务名 `com.mangoworks.finance-distillation.monitor` / `.dashboard`；要求 Mac 醒着且用户已登录。状态命令：`.venv/bin/python -B scripts/manage_monitor.py status`。一次运行用 `.venv/bin/python -B scripts/run_monitor.py --once`；已有 daemon 时第二进程不会并行执行。配置在 `live/account_monitor.json`；每日 3 条是资源上限，不是强制数量目标。没有值得发的内容记录 no-post；故障、预算不足、缺正文保持各自状态。

证据：`runs/account_monitor/replay-final/verification.json` 保存三轮全流程、两次真实进程重启的隔离回放，原始来源与模型响应均来自保存的真实批次调用，故障注入明确标注；它不证明三天实际在线或当前 provider 可用性。真实 launchd 周期保存在 `runs/account_sources_v1/monitor_cycles/`，服务状态与验收边界见 `runs/account_monitor/acceptance.json`。首轮实际运行暴露的历史缺图字符串、RSS 外站条目和旧稿计数问题已修复；原记录及计数更正保留。

历史参考：2026-09-30 后续批次已有三个号各 5 条真实自动候选，见 `runs/content_batch_v2/DELIVERY.md`。更早三例 localization 拒绝与 Codex-assisted 稿是历史证据，见 [旧审稿包](../runs/account_sources_v1/completion_v2/REVIEW.md)，不作为当前自动链状态。

三账号为 `en_morris_archive`、`zh_macro`、`zh_industry`。另两个英文账号保留旧记录，不进入此工作台的新生成。旧生产配置与队列没有切换。

## 现在的数据流

```text
账号 → 本账号订阅增量抓取 / Morris 未消费历史
  → 持久化 cursor / 去重 / 时效 / 上下文 → 本账号 inbox
  → 原文完整性检查 → 对该账号判断 worth / fit
  → 原文选段 → Morris 私有 evergreen/身份检查（仅该账号）
  → 翻译（同语言直接使用原文）→ exact-span 轻编 → 私有 QA
  → 一份成稿 → source / draft / 风险 / 人审
```

`live/account_source_universes.json` 是本地新路径的订阅边界。CORE/SECONDARY/EVENT_ONLY 可按规则形成候选；RESEARCH_ONLY/WATCHLIST/REJECT 不形成写稿任务。物理来源存储可共享，候选与处理记录按账号隔离；没有 event×accounts 默认循环。

明确必需的缺失原文/图表/上下文在 writer 前停止。不确定图表保留为结构化 annotation，选段时判断是否必要，不因文章有作者头像就一律停稿。不完整付费预览没有被当成全文。

Morris 仍是历史中文内容精选→英文；不要求“翻译以外的新观点”。包含必要个人经历、持仓或已经失效的前提时，不能剥掉前提冒充 evergreen。需要当下核验却缺证据时先 hold。作者和真实说话人不能互换；provenance、编辑理由和 QA 保留后台。

翻译/轻编/QA 复用原有提示。新固定账号适配层只限制候选账号、允许同语言原文作底稿，并增加私有 Morris 检查。它不会替换原文、产生 editor brief 或强制重新作文。母语质量最终由人判断。

## 明确账号的命令

在 repo 根目录使用 `.venv/bin/python -B`：

```sh
# 已保存的四个历史 fixture，保持原 source 和 follow-up 身份
.venv/bin/python -B -m scripts.run_account_sources seed

# 一个账号的来源收件箱（不调用模型）
.venv/bin/python -B -m scripts.run_account_sources inbox --account zh_macro

# 将现有 source JSON 数组按这个账号的订阅资格导入
.venv/bin/python -B -m scripts.run_account_sources intake --account zh_macro --input /path/to/sources.json

# 仅更新这个账号的有界 RSS 订阅；不隐式抓 X，不调用 writer
.venv/bin/python -B -m scripts.run_account_sources refresh --account zh_industry --limit 3

# 明确选择已入队候选；有既有结果时返回原结果，不重复付费
.venv/bin/python -B -m scripts.run_account_sources run --account zh_macro --candidate INBOX_ID

# 有意重评才传原 run；原来源/账号不匹配会拒绝
.venv/bin/python -B -m scripts.run_account_sources run --account zh_macro --candidate INBOX_ID --follow-up-of RUN_ID

# 固定四例：三个单账号 follow-up，加一个资格检查即停止的 source
.venv/bin/python -B -m scripts.run_account_sources fixtures

# 导出到新的带时间戳目录；不会覆盖历史评估包
.venv/bin/python -B -m scripts.run_account_sources packet

# 显式 X 有界刷新（付费；保留 actor/dataset/raw hash/quote/media）
.venv/bin/python -B -m scripts.run_account_sources refresh --account en_morris_archive --include-x --source x_Morris_LT --since 2025-01-01 --until 2025-02-01 --limit 5
```

缺少 `--account` 的日常命令会失败，不会默认评估全部账号。旧 `scripts.run_account_intelligence run` 与 `/events/{id}/run` 已停止接受生成；旧单账号实验类保留以供历史 contract regression，不是新入口。`event_all_accounts()` 明确报错。

本地代理不可用时，曾按进程使用 `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy`，没有修改 `.env` 或全局代理。

## 审阅与质量指标

选择账号后默认看本账号成稿，先对照选中原文与完整来源，再看正文和具体风险。approve/edit/reject 直接可见；wait/ignore、旧实验和机器 reasoning 收进次级详情。接受只保存人审，不执行发布，也不自动采纳成账号长期观点。

人工保存原文版本、实际改稿、修改 spans、理由、错误类型和显式的 unchanged/minor/major/reject。edit distance 仍可查看，但不会自动判断“小改”。变更后的正文不会继承旧稿的 machine QA。

主指标为同账号、同批次**首次稿件的人审原样/小改可发比例**；待审、失败、无稿另列。后续 follow-up 不改变初次稿件分母或回写其首轮标签。机器 fidelity 和人工可发性分开。当前没有任何由 agent 冒填的人工接受记录。

盲测数据尚未收集；既有候选稿单独混排不被计作“真实优质内容 vs AI”盲测。人工审阅后先整理重复错误，再提出代码或 prompt 改动。

## 保存位置与尚未覆盖的能力

- `runs/account_sources_v1/store/`：来源、账号 inbox、运行、真实人审；旧 `account_intelligence_v1/store` 只作历史回退。
- `runs/account_sources_v1/completion_v2/`：当前精确四例输出、原文/译文/稿件对照、测试、v2 validator 诊断、盲审准备和交付清单。
- `runs/account_sources_v1/assisted_followups/`：辅助编辑提交、原始 QA 调用、长度中断、完整 QA 与后恢复 BLS 原文。补充 QA 在 dashboard 只读展示，必须绑定稿件、原文、代码哈希，不清除旧 hold。
- `runs/account_sources_v1/discovery/`：40 次有界 Apify 查询的原始记录、277 个唯一帖、279 条可追溯关系、具体内容审核、17 个初次候选和 3 个独立核对完整正文的 Morris 新版本。
- `runs/account_sources_v1/evaluated_code/`、`evaluation_manifest.json`、`apify_followups/`：原自动评估的冻结版本和真实停止。旧 13 文件 manifest 漏含 `numeric_fidelity.py` / `fidelity.py`；后保存历史副本不能补造当时的冻结覆盖。新运行版本另存 `completion_v2/code_manifest.json`。

现已接通显式、单账号有界 RSS/X 刷新、给定官方 URL 的文档抓取和有证据的 `current_evidence` 输入。正常 RSS 实采：Macro 两条进入 pending_selection，Industry 两条 feed 预览进入 needs_source；未触发别的账号出稿。X 原始文本版本、引用、media 和完整性未知状态保留，不再把返回 text 自动当作完整正文。

历史执行阻塞包含 Macro source_hygiene 的 content_filter 和 Industry selection 缺字段；2026-10-02 已部署显式 erisedai provider 变更后的有界恢复、旧成功 follow-up 对账与 QA-only 续检，具体实际运行见本轮报告；累计 cap 已由用户授权提高至 $100。旧 localization 成功修复仍在共享路径，不能把不同阶段的拒绝混为同一个问题。真实人工可发性验收、盲评分、发布表现反馈尚未完成且不属于本轮 P0 扩展工作；全时间线/代表性 source 质量分母与跨语言稀缺性仍未知。Industry 的 PJM / Micron / DRAM 实例存在关键词漏选，保留记录，没有借本轮调整选题方向。

官方发布现在通过每个账号订阅的官方 feed/index 自动发现并保存到独立 context store；实际引用相同 URL 才关联，不能自动当作核验完成。自动当前事实研究与通用线程/图像/PDF 恢复仍未实现。官方材料只作事实背景，不能整篇成为日常候选。公开正文无法恢复的预览保持 blocked_source，并有有界重试。Morris 已保存历史库按稳定帖身份消费，既有稿件不会重新生成。已接入五份库（含 139 条 normalized 抓取），合并 200 唯一身份；67 明确完整，133 不完整或未知。后续追加文件目录由 source_registry.archive_import_dir 配置，不能把这些采样称为完整历史。同事件去重依赖明确 event/thread ID、同 URL 或相同正文；没有声称能识别所有不同措辞的同事件帖子。现有 X 获取仍是有界 provider sample，饱和窗口显式保留覆盖缺口，不假称完整时间线。

五个逻辑 profile 保留，本轮仅运行三个核心账号，外部平台身份未绑定。不自动发布。本轮补齐来源生命周期和实际运行验收；没有新增 KOL 研究批次、benchmark、盲测设施、领域或训练。未来领域复用的实际边界见 DAILY_PIPELINE.md。
