# Finance Distillation — 工作入口

## 2026-10-02 当前状态：累计 cap $100，完整日常链

当前产品与执行优先级以 `docs/CURRENT_DELIVERY_PLAN.md`、`docs/DAILY_PIPELINE.md` 为准。下方各节是历史快照；其中 $50/$60、密钥待提供、默认 Apify、同事件广播、强制重写/禁止直译等旧结论不再适用。目标产品形态按帖型（post_type）成帖：各账号自己的 source universe → 增量跟踪 → 内容单元抽取 → 按帖型和人设成帖（带署名 frame）→ QA → 人工审稿。帖型为 data_take、mechanism_explainer、view_relay、earnings_take、aphorism_translation，定义见 `live/post_types.json`（P0-4b 落地）。“原文选段 → 翻译 → 最小轻编”只是 aphorism_translation（Morris）的实现，不是中文号的产品规格。不以更多稿件数量代替自动化完成。

累计预算上限已按用户指令改为 $100，保留历史支出与预留。现有 `.env` 凭据一直可用，默认 `ACCOUNT_CONTENT_PROVIDER=erisedai_relay` / `claude-opus-5` 已显式持久化，不要求用户重发 key，不自动 fallback。只运行 `en_morris_archive`、`zh_macro`、`zh_industry`，无自动发布。每日 3 条是上限而非配额，QA-only 续检不算新文章。

本轮官方来源是真采集的独立 context，Morris 读取五份已保存库和追加目录；修复已保存结果对账、QA 冻结续检、原文修订恢复和来源作者/出版物分离。无写作 prompt 更改。当前运行证据位于 `runs/automation_completion_20261002/`；最终服务状态以该目录的服务验收及实际 status 为准，不能仅据文档假定 daemon 运行。

人工内容验收、同事盲评和发布表现仍需真实输入，不能以 tests/机器 QA/心跳替代。X 和历史库覆盖有界，付费墙/必需媒体缺失、外部端点失败仍须明确展示；不能宣称全部来源已完整接通或任意领域已一键上线。

## 2026-10-02 更正：relay 密钥一直在现有 `.env` 中

用户指出后已实际确认：`REVIEW_BASE_URL` 指向 `api.erisedai.com`，`REVIEW_API_KEY` 已配置，真实 `/models` 返回 200 且包含 `claude-opus-5`。此前仅检查新增 `ACCOUNT_RELAY_*` 字段后声称“密钥缺失、需重新复制”是核查错误，**不要再要求用户重复提供**。`relay_config()` 已支持同一 erisedai host 的现有完整 REVIEW 配置对；显式 ACCOUNT_RELAY 配置优先，禁止混用不同 namespace 的 URL/key。没有打印、复制或修改现有密钥。provider selector 仍明确控制，原失败案例先沿原身份验证，再决定日常切换。证据：`runs/full_plan_completion_20261002/relay_env/availability.json`。

真实完整原文 follow-up 已实际执行：`run-8a573412e72343509dea514438e1e1f4` 链回原 Macro `run-46055dcca90f4899b26dede0ff19b3e7`。routing/selection 严格复用原 Apify 响应；Erisedai 的 hygiene、translation、localization 均 HTTP 200 / stop，原 content_filter 未复现。非空中文候选自动存入同一 dashboard Store，但数字检查保留 machine hold，模型语义 QA 未运行，不能称内容验收通过。28 项 relay/stages 测试通过；具体证据见同目录 `macro-original-followup/result.json`、`verification.json`。这是一条显式 provider 验证，日常默认仍 Apify，未自动切换或提高 $60 cap（结束估算余额约 $0.916）。

## 2026-10-02：恢复完整交付，不以 P0 代替其余验收

用户明确“其他的也都要完成”。当前完整范围与逐项完成标准以 `docs/CURRENT_DELIVERY_PLAN.md` 为准：三账号日常循环、固定 15 条自动稿内容验收、每号 5+5 盲审、真实人工反馈总结及来源质量 backlog。旧 donor 模仿/同事件广播/泛化训练计划不恢复；只有三个核心账号运行，没有自动发布。

原 12 条冻结 follow-up 已执行完；3×5 自动非空稿也已完成，不再把这些笼统写成“未出稿”。真实人审仍为 0。当前审稿台已接本批每号 10 条匿名材料，旧四条辅助稿保留历史；总入口 `runs/full_plan_completion_20261002/review/README.md`。原稿与盲包冻结，QA 与人工接受分开。

I04 QA 长度 follow-up 已完整返回，正文逐字不变，因研究者第一人称转移仍 machine hold。实际新调用为 routing/selection/QA 三次，translation/localization 复用；源版本 ID 变化导致前两阶段未复用的事实与修复见 `runs/full_plan_completion_20261002/qa_followup/result.json`。后续 execution follow-up 保留原 admission/source snapshot，禁止把缓存旧 run 当作已续跑。

正文恢复现已重检缺失/unknown 的预览语言；三个 NextPlatform 既有完整正文已凭原缓存校正语言元数据、沿原 item/run 身份重入重试。原文、时间、媒体注释和旧失败不改。两篇旧 Liberty Street 导入丢段落边界的问题已还原原 XML 的精确正文供复核，尚未入队或当作已生成稿。完整产物位于 `runs/full_plan_completion_20261002/`。200 项相关回归和 JS 语法检查通过；不是内容质量通过。

服务继续运行。累计 cap 仍 $60；新 relay 的完整案例验证仍待同一密钥重新复制，实际默认仍 Apify。不得把待人审、缺密钥、未发布表现或全面来源覆盖悄悄标成完成。下方所有计数都是历史快照。

## 2026-10-01 21:00 UTC 后续：用户授权累计预算上限 $60

累计 cap 已从 $50 调至 $60，原预算失败记录保留并恢复原身份重试；不能再次按下方旧 $50 阻塞描述停工。新的 erisedai relay 小样本已成功，明确 provider selector/安全 transport 已实现；剪贴板随后被覆盖，密钥未保存，已请求用户重新复制。**当前实际日常服务仍显式使用已验证 Apify / Claude Opus 5**，没有自动 fallback。本轮已完成 **4 个真实周期 / 32 个自动 run / 2 条 Morris 英文稿**，均直接进入 dashboard；Macro 三例原失败 follow-up 仍遭 source_hygiene content_filter，Industry 一例 selection JSON 缺协议字段，**P0 仍未标完成**。123 项测试和最终代码三轮记录响应回放通过，但不是新模型稿或人审通过。最新完整数字、原文/新稿、运行证据与待续身份见 `runs/account_monitor/p0_relay_live/DELIVERY.md` / `acceptance.json` / `resume_items.json`。服务保持运行、30 分钟一轮、无发布；预算剩余以当前 ledger 为准（结束快照约 $4.67）。

仅修 P0 恢复问题：补齐的历史正文可重新到达 blocked-source 检查；预算等待不耗掉模型错误的重试额度；launchd 重启等待原服务卸载；显式 follow-up 自动接既有 hygiene/QA 修复，及原本已有的 routing/selection token ceiling，逐次保存 repair 来源。写作 prompt 常量/source universe 未改，没有放宽语义检查。`ACCOUNT_CONTENT_PROVIDER=erisedai_relay` 显式选新服务商时需本地 `ACCOUNT_RELAY_BASE_URL/API_KEY/MODEL`；没有密钥时不要切换、伪称部署成功或寻找未授权 credential。下一步是拿到同一 key 后实测新 relay 的完整原失败案例，并保留父 run 身份；不要继续在已拒绝的 Apify 案例上反复烧钱或再次扩基础设施。账户上限是本地估算 ledger，不是 provider 余额。

## 2026-10-01：唯一 P0 是持续监控 → 自动候选稿 → 人工审核

用户纠正 priority drift：暂停扩源、research、benchmark、泛化和训练。仅 `en_morris_archive` / `zh_macro` / `zh_industry`。`scripts/run_monitor.py` 已接通逐账号增量抓取、SQLite cursor/consumed/失败恢复、去重和现有 dashboard Store；Morris 消费本地历史库，不等待新帖。dashboard 与 monitor 默认共用 `live/content_stages.py` 的已验证 Apify → OpenRouter → Claude Opus 5；旧历史页生成已 409 禁用。没有自动发布。

两个 user LaunchAgents 已实际安装并启动，30 分钟一轮、终端退出继续、登录启动；Mac 必须醒着且已登录。`.venv/bin/python -B scripts/manage_monitor.py status` 查看状态。SQLite 在 `runs/account_sources_v1/store/monitor.sqlite3`，真实周期在其父目录 `monitor_cycles/`；页面 <http://127.0.0.1:8684/account-intelligence> 每 30 秒自动更新。

**daily pipeline 尚未标完成。** 当前原累计 $50 上限不足以完成新的真实生成；$60 上限询问待用户明确答复，不得自行提额。三轮隔离回放及两次进程重启通过，保存真实 API 旧响应的回放不能冒充本轮新模型稿。真实首轮的旧稿计数更正另存，不覆盖历史。最新证据与未完成边界：`runs/account_monitor/acceptance.json`、`replay-final/verification.json`、`live_cycle_corrections.json`；运行说明 `docs/ACCOUNT_SOURCES.md`。同事件去重只覆盖强身份/明确 event ID，未做无关联帖子语义聚类。下方历史“自动0篇 / 未安装scheduler”不再代表当前实现。

## 2026-09-30：当前续作状态（优先于下方历史记录）

账号订阅先行已接通，三个核心账号分别 intake；五个逻辑 profile 保留、另两个英文账号停用、外部平台未绑定。生产未切换。当前交付入口：`runs/account_sources_v1/completion_v2/DELIVERY.md`、`REVIEW.md` 和 `exact_outputs.json`；dashboard 为 `http://127.0.0.1:8684/account-intelligence`。

原冻结自动评估依然是三次 localization provider refusal、零自动最终稿。新的三篇 **Codex-assisted** 候选有独立 origin/protocol 和原 follow-up ancestry，不与自动效果混算。F03 独立 QA 通过；F01/F02 私有语义 QA 仍对非必要编辑有发现，原 machine hold 未清除。三篇全部待人工，不得把旧 Morris 稿的反馈映射给新版本。F04 未订阅，零模型调用停止。未继续修改写作 prompts。补充 QA 和 validator v2 只读、按稿件/来源/代码 hashes 展示；已保存原始长度中断及完全相同 messages 的较长输出续跑。

有界 discovery 已做：27 个 source/account 提案、103 个例子；40 个实际 Apify 查询、277 个唯一帖（Morris139）、279 条引用等关系。17 个新候选完整性未知而 hold；另三个 Morris 原帖独立验证全文后以新版本 pending_selection。没有伪称全历史、完整分母、引用中心性、当下事实验证或人审通过。官方文档和当前事实证据仍需显式输入，thread/media/PDF 无通用自动恢复。PJM/DRAM 等真实关键词漏选已记录、未在采样时调订阅规则。

当前新增的是实际审稿材料、保守 execution/validator 修复和反馈记录，不是更大架构。盲审四条材料已准备但评分 0，真实参照的质量/匹配仍待确认。所有人审数据均由真人提交；没有人工结果前不总结“重复人工失败模式”、不调 writer。原自动13文件manifest没有包含两个 numeric/fidelity dependency；不能倒补假称当时已冻结完整依赖。

## 2026-09-30：账号自己的信息世界（覆盖下方旧账号/事件定义）

**后续 15:20 UTC：** 用户已明确回复“批准”，允许 F01/F02/F03 的原文、已有译文、冻结 prompts、账号/QA 上下文经自己账户内私有 Apify Actor → 官方 Apify/OpenRouter → Claude Opus 5，沿用现有预算，仅续跑三例、不切生产。此范围无需再次要求相同批准。私有无 HTTP 服务的透传 Actor 已保留原 messages、temperature=0、max_tokens（包括28000），不改评估生成文件。499 项完整离线测试通过。

三例真实续跑已结束：6 次新模型调用；Morris evergreen/hygiene/translation 正常返回，但三个 localization 请求均收到上游 content_filter 拒绝、正文为空，理由涉及其 duplicating model outputs 限制。当前三篇初译、零篇最终稿、QA 全部 not_run、人工质量仍未验收。不能把这种拒绝称为 fidelity 检查失败或编辑质量不合格，也不能把初译晋升为完成稿。原 koala 失败与新 Apify follow-up 全部保留；精确结果与审阅包在 `runs/account_sources_v1/apify_followups/`。以下两篇初译/余额阻塞等描述记录更早状态。

用户最新授权“开始做”。新隔离入口采用 account → 本账号订阅 → 本账号 inbox → 原文选段/翻译轻编 → QA → 人审；只启用 `en_morris_archive`、`zh_macro`、`zh_industry`。另两个英文账号保留历史。Morris 恢复为历史中文精选 → 英文 evergreen，不是泛 frameworks research input，也不要求翻译之外的新观点。旧 event all-account 入口已停用，生产 `live/production.py` 和原队列未切换。

成稿优先工作台：`http://127.0.0.1:8684/account-intelligence`；说明 `docs/ACCOUNT_SOURCES.md`，交付 `runs/account_sources_v1/DELIVERY.md`。本轮 469 项回归与额外 4 项续跑测试通过，不代表内容验收。三个原身份 follow-up 在 koala provider 额度处中断：两篇初译、零篇最终稿、零个人工质量标签；第四个无关来源在 admission 处零调用停止。记录和原文/精确输出在 `runs/account_sources_v1/review/`。评估生成代码/prompts 已冻结，不因结果或余额失败静默修改。

Apify 更正：2026-09-24 的授权仍有效，旧 Xquik lock 不阻止既有 Apify 正常使用。2026-09-30 实测既有采集 API 可访问；只读历史 dataset 确认 wrapper 会漏存 thread/media/quote 字段，未称完成全历史采集。Apify 也有模型 API：通过现成有限权限社区 gateway 调用官方 OpenRouter 的单次无项目内容测试，`anthropic/claude-opus-5` 实际返回 `APIFY_OK`。官方 proxy 本地直连为 403，要求平台 Actor 上下文。现成 gateway 的 token/参数契约不完全兼容冻结评估，尚未发送真实 fixtures 或切换 provider；详情 `runs/account_sources_v1/APIFY_AVAILABILITY.md`。下方“Apify 只用于 X 搜索”和旧余额文字不代表当前能力/余额。

来源扩展当前是有界公开审计与待审提案；没有完整近期 X 分母、Morris 全历史、source 引用中心性或真实混合盲测。下一质量验收仍是完成既有稿件后人审，再归纳重复修改，不能凭测试通过宣称可发或继续泛化。

## 2026-09-30：五账号、source hygiene 与内容审核台（最新状态）

用户本轮明确新增五个逻辑账号与 dashboard、source-hygiene / identity-boundary 层。已配置 `en_morris_archive`、`zh_macro`、`en_macro`、`zh_industry`、`en_industry`；平台与 handle 未绑定，未创建外部平台账号。Morris 历史中文原文只路由其英文账号，仍由 worth-moving/NONE 决定是否生成，不是模仿作者。

原 12 个 follow-up 已使用 `runs/content_acceptance_followup_v1/frozen_code` 的 79 个校验文件独立跑完；未根据本轮输出调整其 prompt/架构。4 draft_ready、4 needs_review、1 needs_source、2 not_suitable、1 skipped。首次失败与 215 个历史评测文件均保留。`manifest.json` 是执行前快照；完成事实以 `completion.json` 和 `follow_up_results/summary.json` 为准。Relay 已实际返回，余额不再是本轮阻塞；cap 未提高。

新账号/hygiene 与冻结评测分开：Morris 来源库是 OpenCLI 的 60 条 ranked search results，经作者核对保留 58 条，非完整历史。三条新 development cases 已实际生成英文，均机器通过；所有 13 篇可审候选的人审仍为 pending。未用模型自评代替人工验收，未据此总结重复质量失败模式或继续调 prompt。

`live/source_hygiene.py` 保留原文及精确 offsets 标注，由 editor 决定保留/移除/归属/补上下文；绝非 blanket redaction。生成后检查正文与 editorial guidance 的身份、地址、时间、媒体和 CTA 风险；规则仅是线索，有风险进入人工核对。人工改稿重新检查并保存逐字差异，接受剩余风险须记录理由。后台记录不注入正文。

审核台在 `http://127.0.0.1:8684/content-dashboard`，独立入口 `python -m uvicorn backend.content_dashboard:app --host 127.0.0.1 --port 8684`。浏览不会调用模型，Morris 的「筛选并生成」是显式付费动作，使用原 relay/cap。正文、人审、机器 QA、来源标注、版本分别显示；人工通过只保存决定，不发布。

交付与逐篇原文/选段/完整成稿：`runs/content_workbench_v1/DELIVERY.md`、`review/INDEX.md`、`review/MORRIS_DRAFTS.md`。当前默认仍是 translation → light-localization，候选 EditorialPipeline 未切生产；共享源代码与账号配置有本轮授权修改，不能说源码未变。生产队列、corpus、source registry 的 hashes 未变，旧服务未重启。没有新 domain、自动发布、全量 Morris 历史采集或自动学习。下一步是真实人审，再归纳重复失败模式。

## 内容验收冻结（历史准备状态；执行结果见上节）

用户已明确：架构工作足够，下一里程碑只做内容验收。当前代码与 prompts 冻结；余额恢复后仅续跑 `runs/content_acceptance_followup_v1/follow_up_cases.json` 中的 12 个原案例，保留 follow-up 身份及首次失败。Nvidia/HAOHONG 现稿直接人审，Duff 的 NONE 和 H09/H12 缺资料结果不重复调用。当前尚未确认 relay 余额恢复，准备阶段没有新模型请求。

执行与冻结 hash 见该目录 `RESUME.md` / `manifest.json`。不在收集结果时调整 prompt 或架构（只有无法执行时才处理必要阻塞并记录）。不切生产、不加 domain、不做额外 shadow 或重设计。原文/选段/编辑指导/成稿给人审，机器保真与人工编辑质量分开。待真实人审后，先归纳有案例证据的重复失败模式，再提任何新代码修改；不得以模型自评替代人审。

## 2026-09-29：domain policy 最小拆分与真实评测（最新状态）

用户附件 `0a158dac-b213-4ef8-a47b-beb4477e7f10/Pasted text.txt` 已明确授权将五例回归、12 条冻结 held-out、必要 source/account/prompt 发往现有 koalaapi.com / claude-opus-5。不要重新要求该范围的目的地批准。首轮 17 条进入评测，42 次请求中 33 次返回、9 次 relay 余额错误；2 条 draft_ready、1 条 NONE、1 条 needs_review、2 条缺资料、11 条 blocked。金融质量**未验收通过**，真实人审 0。当前外部阻塞是 relay 余额，不是授权，也不是本地 cap；不充值、不加 cap、不换 provider。

核心已将 account domain/fidelity_policy、语言能力、恢复能力拆出；金融政策在 `live/finance_policy.py`，原金融 deterministic 检查保留。四个历史账号通过 policy 层的兼容映射获得 finance，新账号显式配置 domain/policy，不由 persona 推断。`live/accounts.json`、corpus、生产队列均未改。

默认仍为 translation/light-localization 路径，未切换成 EditorialPipeline。通用 routing/prompt 已在源码中重构，因此不声称默认源码 byte-for-byte 未变；没有重启服务或部署。候选版本 editorial_completion_v2.1、prompt v5-domain-policy，真实模型效果待续跑。新增语言配置接口不代表默认 EN/ZH 之外语言已验证。

Shadow 可使用 `scripts/run_editorial_v2.py --shadow --baseline-code runs/domain_generalization_v1/before ...` 比对真正修改前的默认生产代码。仅完成两条缺资料 source 的零模型 preflight 对照；内容质量 shadow 因余额不足未运行。所有真实失败与新架构审计在 `runs/domain_generalization_v1/` 与 `docs/DOMAIN_GENERALIZATION.md`。旧节中的“审批尚未授权”只描述上一轮。

## 2026-09-29：editorial completion v2（隔离候选，尚未切生产）

`live/editorial.py` 现在包含 contextual identity QA、数值/单位/公式核对、最多一轮默认精确修复再 QA；选段与 treatment 仍由 editor 按原文判断，公开正文不输出审核解释。新增可选公开全文/存档上下文恢复与独立背景证据；不自动补背景，不猜图片，不登录付费墙。

`scripts/run_editorial_v2.py --live ... --shadow` 可隔离对照当前默认与候选，保留全部失败、原稿、修复、模型调用和盲审包。五条历史案例现为 development regression；12 条真实 adaptation holdout 已冻结，不能再作为 prompt 调试数据。`scripts/freeze_shadow_intake.py` 只冻结现有 intake 窗口，不采集或改队列。

`/localization-review` 与 `backend/localization_review.py` 接通人工改稿/原因/版本/逐字差异，提交前隐藏生成方式，提交后展示机器记录。发布关联和表现快照只保存人工提交的已发布记录，不发帖、不训练、不以 engagement 优化 writer 观点。

本轮模型评测因自动审批要求明确确认 relay 目的地及 payload 而未执行。离线测试、公开网页恢复和 preflight 通过不等于模型或人工质量验收。最新交付见 `docs/EDITORIAL_COMPLETION_V2.md` 与 `runs/editorial_completion_v2/DELIVERY.md`。模型调用需先解决该具体审批阻塞；不要换通道绕过。此前授权与旧冻结说明不变。

生产默认没有切换；四个逻辑 account 未增删，真实平台/handle 映射仍待用户确认。更大产品将是跨语言、跨平台、跨账号内容本地化；本轮仅保留这些接口边界，不扩新 vertical、语言或平台。

## 2026-09-29：编辑判断实验（最新产品意图）

用户最新要求是按 source 决定 treatment，保留 meaning / reasoning / texture，不把“永远最小编辑”当产品规格。完整原文继续作为 writer 的一等输入；editorial guidance 不能替代原文或授权新增结论。不恢复固定 action 枚举、单 thesis、强制短帖、统一模板或 MERGE 新结论。

`live/editorial.py` 的 `EditorialPipeline` 是显式实验入口，合并选段与自由编辑判断，直接 source-grounded adaptation；数字/实体/因果/条件/判断力度/身份等 fidelity 与 prose editorial review 分开。公开正文不写 QA reasoning，但原作者自己实际写出的 caveat 和推理限制可以保留。

默认 `production.py` 仍使用下方 `localization_v1`，没有自动切换、迁移旧稿或修改队列。实验复用现有 source/account/语言/停止/存储/导出控制，结果等待用户对内容作判断。不要把下方“最小 span 替换”机制推广为所有 future source 的永久要求。诊断和历史证据见 `docs/EDITORIAL_DISCRETION_STUDY.md`，原始历史、失败、新稿与 QA 在 `runs/editorial_discretion_v1`。

## 2026-09-29：已接受 audit 后的当前主流程（覆盖下方旧产品方向）

`production.py` 默认使用 `localization_v1`：完整 source snapshot → worth_moving + account routing →
account.lang → exact passage selection → faithful translation → light localization → fidelity QA → human pending draft。

- 四个既有账号从 `live/accounts.json` 读取；只使用 enabled 账号。当前最小版仅启用 en→zh、zh→en，无同语言默认回退。
- `NONE / SKIP` 在代码中终止；原文不完整进入 needs_source。旧 REWRITE / MERGE 分类器不控制主流程。
- 选中的原文完整送入翻译，不使用 brief、重组观点、一个判断、默认短、固定句式或 donor 模板。
- 保留原文推理、力度、条件、数字/单位与身份归属。persona 只用于适配、语言、术语和轻微表达。
- provenance 保留在后台；正文默认不附作者/URL footer，但保留原文事实归因及避免身份冒用所必需的第三人称。
- 新增外部事实背景暂未启用；轻编允许零改动。模型 QA 不是人审，review_status 仍为 pending。
- 轻编默认信任已有译文；句子自然就不动。只返回必要的局部替换，由代码保留其余文字；保留顺序、强调、例子与论证节奏，不解释、概括、限定或重述逻辑。
- QA 是后台约束；“有依据/无依据/更窄/有条件/原文没有/新增观点”等编辑判断及改稿说明不得进入正文。原文实际的条件、因果和不确定性照常保留，不靠词语禁令删掉它们。
- 原文版本、选段 offsets、初译、轻编、编辑记录、QA 与真实调用保存在 `live/store/distillation`。
- 订阅由 source_registry.json 的 enabled/adapter 配置控制；历史原稿不迁移、不覆盖。主流程不混入旧 Evergreen。
- `--events` 的旧生成入口已停用，`--prepare` 仍可准备检索素材。旧 daily/write/crosslang 等保留作历史能力，不属于 localization_v1。
- 四个合成 fixture 独立写入 `runs/localization_v1`，不得当真实市场素材进生产队列。
- 新 relay 调用经 ml/budget.py 预留预算并记录 usage；使用配置中的现有额度，不从本文旧的 $10 描述推断额度。

本节是用户接受 `docs/audits/2026-09-29-distillation/AUDIT.md` 后的实施定义。
下面相冲突的“独立创作/禁止逐句翻译/必须署名/重组”条款仅为历史记录，不应用于新流程。

**2026-09-24 起，交接冻结已由用户解除，进入实施。** 采集、生成、新增数据源都已授权，不需要再逐次请示。先读此文件、`docs/KNOWN_FAILURES.md`、`docs/TIMELINESS_DUE_DILIGENCE.md`、`docs/PIPELINE_PROPOSAL_REVIEW.md`。本文件记录用户要求，不能用旧 README、文件名或模型自评推翻它。

## 2026-09-28 当前决定

这一节覆盖下面「当前工作次序」第 2 条，也覆盖本文件上一版「新闻先发现事件、再去分析源里匹配」的主路径。那条路径是辅助，不是主流程。

`source_registry.json` 的意义是订阅。主路径是 source-first：

```text
approved source registry
→ 持续轮询新帖 / 新文章
→ 新内容到达
→ 分类：REWRITE / MERGE / SKIP
→ 需要时补全文或链接文章
→ 强模型 public_writer
→ 人设（从已有判断里挑）
→ 现有 QA
→ 审核队列
```

- REWRITE：一条帖子本身已有判断。它就是主要改写材料。可以重组观点、推理、例子、论证顺序、第二层含义。不要连续复制独特原句。
- MERGE：最近窗口里多个已订阅源在讲同一件事，才做简单主题聚类，合并 2–5 条。语义匹配只发生在这一步。
- SKIP：广告、纯转发、生活帖、没有观点的新闻复述、信息量太低。
- 新闻和事实源降级为核对帖子里已经出现的具体数字，不是写稿素材。
- 事件驱动检索保留为第二条辅助能力：新闻很重要、订阅源还没人写，才去外部找分析。入口是 `production.py --events`。不要继续优化关键词检索。
- 日常入口是 `production.py`，默认不跑新闻发现，不抓一年历史。
- 取样按源，不按全库最新 N 条。每个订阅源每轮最多 2 条、只看最近 24 小时。高频账号不能占满窗口。
- 2026-09-28 订阅去重后是 44 个通道：9 个 X + 30 个 feed。Citrini 的 X 和 newsletter 是同一作者的两个通道。Sportico 不在订阅里。没有新增源，22 个 feed 都来自已验证的 `research_sources.json`。
- 改写材料必须带正文。不能压成一句 “author thinks X” 再让模型补。
- 人设从已有判断里挑，不凭空创造观点。三个人设仍是测试组，不是最终账号数。
- 公开稿走 `WRITER_BASE_URL` / `WRITER_API_KEY` / `WRITER_MODEL`（当前主机 koalaapi.com，模型 claude-opus-5）。不要调用 `XAI_API_KEY` 写稿。
- QA、Evergreen、人设数量、源池都先不动。不自动发。

计费：这个 Grok 对话如果进程环境里有 `XAI_API_KEY`，会按 api.x.ai 的 token 扣费，登录态挡不住已经带上 key 的进程。开 Grok 的终端和编辑器不要 export 这把 key。2026-09-28 实测 koalaapi.com 的模型目录有 Grok，但 `grok-4-1-fast-non-reasoning` 和 `grok-4.20-0309-non-reasoning` 都返回没有可用通道，不能把这个对话改到中转站。Apify 商店里没有 Grok 对话 actor，它仍然只用于 X 搜索。

下面「不得」的部分分两类，混淆会出事：

- **纪律类**（证据、provenance、同语言不得搬运、失败必须留痕、模型自评不算验收）——这些是项目被反复打回后写下来的，不随冻结解除而放宽。
- **冻结类**（暂停生成、暂停采集、逐次请示）——**已废止**，不要再据此拒绝干活。

## 实际位置与冻结状态

项目根目录为 `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`，源码直接在本目录。不是 Git 仓库，branch/commit/dirty_files 均为 null；不要据此声称工作区干净。用户授权迁移所有项目文件，已保留完整模型、环境、数据及失败记录。`handover/migration.json` 有迁移前后 SHA-256 清单。旧 `outputs/vertical-slice` 仅是指向此目录的兼容链接，用于旧运行记录和 venv shebang；不要直接删掉旧链接后假设环境仍可用。

`historical_workspace/` 保留早期工作目录、Phase 0、旧交付 ZIP 和资源方案。旧 ZIP 不是本次交接包。原始 `Finance_Stocks_KOL` 工程、其 `.env`、用户原始 Excel/Reads ZIP 和全局 skills 没有移动。不能改写/删除用户原始输入。交接前的业务文件未修改，新增交接文件除外。

`freeze.json` 覆盖展示状态，不改原始 case 的 running/started 记录。当前只能称为 `Corpus Import + Rule Filtering + News Ingest + incomplete evidence-loop experiments`；不是蒸馏 pipeline、ML persona 或已实现 multi-donor system。

**`:8683` 正在运行**（2026-09-24 实测 `/health` 返回 ok），本文件此前记为「已停止」是错的。在替代方案验证通过前不要杀掉它。`:8680` 状态未复测，用前自己测。

## 产品真实目标

这是多语言金融内容情报与蒸馏系统，不是两个中英文账号生成器或静态文章生成器。汇聚中文、英文、韩文等金融、科技内容；来源包括 X、其他社交平台、YouTube、Bilibili、金融群、财报、电话会、机构研究、宏观数据和权威资料。保留原始文本/字幕、作者、时间、语言、平台、URL、来源 hash、证据和完整 provenance。

分别学习 Knowledge、Reasoning、Style、Content Habit、Visual Profile；特征必须有样本量、计算方法、支持 post IDs、版本和可观察范围。将 2–4 位互补 donor 的知识、推理、表达、习惯、视觉角色分别加权，不能把名单标签当组合证据。权重、真实检索 ID、profile version 和选择理由必须可见。

同一事件由不同 persona 独立提出问题、制定研究计划、取证、写作、配图；禁止先写母稿再换词/翻译。持续识别热点、计划事件、叙事加速/衰减/反转、共识、分歧、立场变化、首发与传播及跨语言信息差。自动运行到人工审核与内容交接；不包括自动发帖、账号设备/IP、互动、养号、流量运营或增长。

## 人设、内容线、语言、格式独立

初始 seeds：宏观数据与资金流观察者；个股及产业链硬核研究者；交易系统与市场心理教练。只是验证不同分析的首轮测试组，不是三个固定模板或最终账号数。跨语言能力不是第四个人设。

六条内容线：Hot Signal、Scheduled Catalyst、Evergreen Trading Principles、Prediction Ledger & Review、Cross-language Information Gap、Deep Research。系统以机会评分和 persona relevance 选择 `Content Lane × Persona × Language × Format`，不机械生成全部排列；允许不发、观察或等待确认。

## 产品入口与审核

一级入口为 Today / Intelligence Desk、Events & Opportunities、Accounts / Personas、Drafts & Visuals、Library & Updates。二级为 Sources & Corpus、Pipeline Runs、Quality & Evaluations、Settings。

首页回答 KOL database 现在说什么、叙事变化、谁最早提出/谁传播、共识分歧、CN/EN 信息差、未来催化事件、值得生产的内容、待审核稿件及来源/pipeline 失败。Corpus 属于二级审计。不要把 ETL 阶段设计成用户必须逐项推进的任务。

Persona Lab 使用滑杆、标签、donor 组合器、真实样本和同事件比较。每项显示自然区间、样本量、计算方法、post IDs 与当前值。Expert JSON View 只在高级设置。视觉必须依据问题选择原始截图、确定性数据图、结构图或不配图；宏观时间序列、产业收入桥/供应链、交易情境矩阵只是可用语法，不是强制模板。

## 事实、视频与实验纪律

- 完整原文→完整事实包→事实/观点/推断分离；Yahoo 只能补充，不能替代 IR、SEC、电话会原文。BLS 工资、参与率、兼职、行业贡献、历史均值、修订均不可被摘要裁掉。
- 每篇保留 source URLs/time/hash、事实包、donor/角色/权重/版本/真实 exemplars、prompt/model/temperature/seed/run ID、逐句 claim ledger 和 donor influence ledger。显示的是实际输入和声明使用，不应冒充模型内部因果证明。
- `legacy_invalid_output` 45 篇（另有 37 条 quarantined-generation）不得进入稿件库、待审核数、训练、few-shot 或正式评估。只留带标签的失败回归案例。目录名含 baseline 的旧生成记录也无效；不要重写或删除历史记录。
- 真正五组 baseline 必须在同一完整事实包、同批真实事件、同模型设置、同评估规则下新建。当前 15 格协议只有 4 格被尝试，3 格失败、1 格中断；有效新稿 0，真人标签和审核 0。
- 视频保留完整 transcript 和 segment，human_caption → auto_caption → ASR，之后说话人分离、金融实体/数字日期校正、分类、跨平台去重、统一 corpus。视频主要进入知识/推理/框架/预测/Evergreen，不直接学习 X 短帖 Style/Habit。
- 每段事实和 donor influence 可反查原帖或视频说话人/时间戳。多来源独立综合；除短句且明确署名引用，禁止复制表达、近义词洗稿、固定推广/导流/订阅/邀请码。
- **搬运只能跨语言或跨平台，同语言同平台一律不准搬。** 判定看的是"源与成稿之间是否跨过了语言或平台边界"：
  - **同语言禁止**：英文源→英文稿、中文源→中文稿，不得搬运措辞、句式、论证顺序或结构。同语言只能独立重写，闸门按 donor 自己的重合基线判定（真人写两条不同帖，最长连续一致中位数为 0）。
  - **跨语言允许**：英文一手信息→中文稿、中文圈讨论→英文稿，这正是 Cross-language Information Gap 这条内容线的目的。搬的是**信息与事实**，不是句子：目标语言的每一句仍须自己写，注明来源与原语言，不得逐句直译冒充原创。
  - **跨平台允许**：X→小红书、YouTube/Bilibili 字幕→贴文等，同样只搬信息，且须按目标平台重新组织。
  - 无论跨不跨边界，以下一律禁止：搬对方的推广/导流/订阅/邀请码、搬对方的短链与跟踪链接、冒充对方身份或暗示由其背书。
  - 本条约束的是"外部来源→我方稿件"。我方四个账号之间仍然禁止先写母稿再换词/翻译（见产品目标一节），那是各账号独立成稿的要求，不受本条放宽。
- 模型输出自评、规则银标、HTTP 200、文件数量、截图和安装 skill 都不是验收完成。必须保留失败、样本量、指标、盲测和人工修改量。

## 技能与资源约束

官方 jupyter-notebook/playwright/screenshot 已在全局安装；项目本地 `.agents/skills` 有审计后的选定 Xquik、金融补充、Trackio 和专属 financial-persona-distillation。锁定与产物对应见 `skill-audit/skills.lock.json` 和 matrix。

**X 采集（2026-09-24 更新，取代原「只选 Xquik」）：**

- `twitter` CLI 按账号轮询仍是主路径，**关键词搜索仍然 404**（当日复测，不是沿用旧记录）。
- **Apify 已授权，用户原话「这个尽管调用」。** `APIFY_TOKEN` 在项目根 `.env`。账户 SCALE 方案，月额度 $500。`apidojo/tweet-scraper` 实测可做关键词搜索，**$0.0004/条**，10 条 $0.004。这是目前唯一能做 X 关键词搜索的通路。
- 调用要记 run id 与实际 `usageTotalUsd`，和 LLM 调用一样留账。单次任务超过 $5 先说一声。
- Xquik 仍未配置凭证，不要拿 RapidAPI key 调它。既有 RapidAPI 导入是历史数据，不要当成新采集。

train-sentence-transformers、huggingface-community-evals 已评估；LoRA/SFT 不启动，除非真实数据、基线、消融证明必要。writer-persona/Bespoke 只借鉴 stylometry、blind backtest、self-similarity、AI-pattern 机制，不照搬最终人设。

**SEC EDGAR 已启用**（2026-09-24）。用户明确授权用其邮箱做 User-Agent 联系方式，仅出现在 `live/news.py` 的 SEC 请求里，不得加到任何其他源。仍然不得编造身份。

只能使用用户指定的现有 Chrome window；ambient in-app browser 不构成授权。不得导出 Cookie、读取浏览器凭证库或绕过登录/锁屏。不得暴露 API key/token。

付费调用：**Apify 已按上节授权，正常使用不必请示。** LLM 调用受 `ml/budget.py` 的硬上限约束（当前 $10）。未经明确授权仍不得 push、部署、发布、购买新套餐或升级计划。

## 当前工作次序

1. 新闻源跑几天攒真实量级（`live/news.py`、`live/calendar_events.py`，已接 10 源 + Nasdaq 财报日历）。
2. **已被 2026-09-28 一节覆盖。** 主路径是订阅源发新内容，再判断改写、合并或跳过。新闻只核对帖子里的具体数字。不要再把「新闻发现事件 → 关键词去 KOL 池搜索」当主流程。
3. 向量去重（同一通稿多家转发，hash 抓不住）→ 聚类成事件 → LLM 只作用于幸存者。
4. 视频转写接入 opinions 层。视频是 creators 把推理讲完整的地方，正好补稿件最弱的一环。
5. 定时器最后上（launchd `StartCalendarInterval`，睡眠后会补跑；`StartInterval` 会丢）。

不要重新执行会覆盖失败记录的旧脚本。完整验收标准在 `docs/ACCEPTANCE_TESTS.md`。

四份原始任务文本逐字保存于 `handover/requirements/`；后续术语纠正、视频/六内容线、证据闭环和产品纠偏以本入口及验收文件补充。早期“四页”“旧 baseline”“先做 Phase 0”等表述已被后续用户要求覆盖。
