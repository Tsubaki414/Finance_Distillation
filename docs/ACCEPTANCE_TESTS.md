# 历史验收要求与保留 backlog（非当前执行清单）

**2026-10-02 范围核对：当前验收与执行顺序以 [CURRENT_DELIVERY_PLAN.md](CURRENT_DELIVERY_PLAN.md) 为准。** 本文件保留更早的 donor/persona、事件研究、视频与视觉要求及其证据门槛，不是要求立即恢复所有历史工作，也不是已通过清单。后来的用户指令优先：三个账号各自订阅和选择内容、Morris 历史原文→英文、翻译与轻编、人工审稿；不恢复同一事件默认广播全账号、固定双稿或 persona 重写流程。

来源真实性、provenance、实际改动记录、失败不抹除、机器与真人验收分开等约束仍适用。扩源、完整长期语料、视频/视觉、额外 benchmark、新领域/语言、批量账号和训练等未完成项保留在 backlog，按当前计划的明确阶段与授权推进；不能因旧表列出就越过内容验收。下文的 Xquik-only 限制也已被后续明确 Apify 授权覆盖，不应据此阻止已授权的现有采集。

详细原始产品与视觉要求逐字保存在 `handover/requirements`。原交接口径为“交接不取消、不缩减此前要求”；保留历史不等于取消后来的范围纠正。机器脚本只能证明其实际检查的结构/计数，人工语义评估不得由模型代填。

## A. 真实来源与 donor

- 至少 12 名真实 donor，目标至少 6 中文、6 英文，覆盖宏观、产业、交易心理；按真实发文语言统计，不用表格主观评价或目标语言冒充实测。
- 每人最近 180 天或最多 500 timeline items（达到上限应保存游标、边界/停止原因和仍未覆盖范围），时间顺序、original/reply/quote/repost 关系完整。每人至少 150 条作者真正产生的可用金融原创内容；quote/reply 里的原创分析应单独核验，不将转述/广告充数；不足则替换。整体约 1800+；总量不能代替逐人门槛。
- raw/clean 均保留：stable_author_id、handle_at_collection、post_id、URL、created/collected、语言、媒体、thread/reply/quote/repost、engagement_snapshot、source/provider run/hash；保存分页/API 请求/响应、费用估计与实际量。新 X 只用审计后选定的 Xquik，不能同时运行 kohoj。
- 原样保留 raw，清洗移除推广/广告/生活/无依据喊单，记录 span、规则/模型/版本、置信度与理由。分类覆盖原始任务的 13 类。300 条真正人工标注的随机/分层抽样、标注人、时间、分歧处理；规则复核不能替代此后新增的人类要求。
- 新 Excel 只身份/平台/URL/发文语言/候选，禁止采纳后面对作者的主观商业评价；外平台 transcript 不直接作短帖 Style/Habit。

## B. 画像、ML 与多 donor

- 每位 donor 的 Knowledge、Reasoning、Style、Content Habit、Visual 五轴均可计算：样本量、方法、自然区间、支持与分母 post IDs、版本、时间覆盖和 unknown 范围。
- 知识框架/因果机制/风险/时间周期/立场变化/预测证实证伪/知识边界均有原始支持，不能仅让模型写人物简介。
- 风格包含句段长度、数字/ticker/link 密度、图表比例、问题/第一人称/hedge、证据开头/结论开头、列表碎句/长论证、术语解释、引用/开结尾等；习惯包括间隔/爆发沉默、工作日周末、回复引用、主题时长、反应延迟、承认错误/更新等。不完整时间序列下不可观测项明确 unknown。
- 相关性分类比较规则、传统/embedding、LLM；precision/recall/F1、置信区间、失败例、样本数/拒判。银标结果单列。
- 作者/style attribution 使用 stylometry+embedding、轻量模型，按时间和完整 thread 划分，去重/泄漏控制，报告准确率/macro-F1、语言/多数类对照和关键特征。
- 主题聚类和知识差异展示真实帖子、上游来源重复与互补依据；Jensen-Shannon/embedding 距离只作为测量之一，非互补结论。
- 每 persona 选 2–4 donor，Knowledge/Reasoning/Language/Habit/Visual 角色分别说明真实权重、profile versions、retrieved post IDs 和 exemplar、取舍理由。不同 persona 同事件独立研究；可因不相关而不生成。
- Hugging Face 三项技能有实验证据与产物对应；不启动 LoRA/SFT，除非真人数据、有效 baseline 和消融支持必要性。全局官方/项目 skill 的存在不能算模型效果。

## C. 完整事实包与五组新实验

旧 45 为 legacy_invalid_output/failure_case，另有 37 拒绝尝试；全部从产品稿件/待审/训练/few-shot/正式评估/质量统计隔离。只保留少量明确标注失败回归案例；旧目录名含 baseline 不改变其无效性质。

用同批真实事件、完全相同完整事实来源/版本/hash、同模型 revision/temperature/seed/预算策略、同语言与格式条件，重新运行：Base Model、Simple Persona Prompt、Structured Persona Profile、Profile + Retrieved Exemplars、Multi-donor Separated。预注册样本、指标、失败/重试策略、重复次数；报告分布和不确定性。单事件单 seed 的 15 格只能是试点，不是普适优越性的结论。

BLS 同一事件必须消费完整原文：工资环比同比、参与率、兼职、行业贡献、历史均值、修订及相关表格/脚注/调查口径。每个 persona 独立 Analysis Plan；禁止母稿改写。至少覆盖宏观、产业链、交易心理三组。

逐篇保存并在前端展示 event source URLs/time/hash、完整提取事实、donor 及角色、实际检索 post IDs、选择理由/权重/profile version、prompt/model/temperature/seed/run ID、逐句 claim ledger、逐句 donor influence ledger。每段可回原帖/视频说话人/时间戳。任意稿件必须完整反查：来源→语料→定量画像→实际检索→研究决策→每句依据→评估。

指标：真人盲测 persona 识别率、事实完整率/source fidelity、引用准确率、稿件跨 persona 语义重合度、与任一原源句子/n-gram/语义重合度、generic AI structure、真人修改量/时间。随机盲评，答卷/answer key 分离；ID 命中率不代替 entailment；同模型自评分不能当真人；失败计入分母，不能只报告成功稿。

双向 CN→EN、EN→CN 必须使用真实来源、补受众背景、检查信息差/框架迁移，保留数字/单位/归属/hedge/时间；至少一组真人盲测与修改记录；韩文等扩展目标不被交接取消。

## D. 视频和两个真实主题

- 至少 3 YouTube + 3 Bilibili 金融长视频、相关 KOL 真实帖子、1 当前真实热点、1 evergreen 主题；不用 fixture/模拟结果验收。
- human_caption 优先、auto_caption 兜底、无字幕 ASR；完整 metadata/raw/transcript/cues/segments 永久保存；说话人/置信度、金融术语/公司/ticker/数字/日期校正、事实/观点/推理/预测/案例/原则/广告/闲聊分类；所有观点有 timestamp URL。不能一小时先缩成几百字再只“蒸馏”摘要。
- 用重复上传真实例验证标题/音频/transcript 跨平台去重，保留双方来源；视频主要更新 Knowledge/Reasoning/Framework/Prediction/Evergreen。
- 热点：同一事件≥5 KOL 真观点、≥2 带时间戳视频 segment、≥1 权威事实；展示 consensus/divergence/originator/amplifier、立场变化、CN/EN 差；3 persona 独立成稿，各段来源/influence 与原源重合检查。
- Evergreen：≥10 条真实来源提取 Atomic Trading Principles；语义去重、适用市场/周期/regime/条件、执行/失效/误用/反例、原源/时间戳、冲突互补/历史当前案例；≥3 种不同内容形态；一次当前情境触发历史原则 resurfacing 完整回放。

## E. 自动化、产品与视觉

- source sync→pagination/backfill→normalize→重构关系→分类去重→画像→event/narrative→机会评分→路由→独立研究→稿件/视觉→QA→review→update。有定时或事件触发，不靠用户依次点击。每 run ID、start/end、处理数、失败来源、重试状态、输入/产物版本。
- 实际新事件、一个未来 scheduled catalyst、一个 KOL 主题变化、一次新证据影响旧稿/旧图→V2/V3，保留人工改动与版本差异；planned/breaking/evergreen 生命周期不同。实时/每日/每周/月画像与来源质量更新职责保留。
- Intelligence Desk 首页：今日变化、加速主题/KOL 数、共识分歧/最早源/传播、CN/EN 差、视频增量、未来 7 天催化、机会队列、推荐 persona 理由、待审/更新数、freshness/失败；数据缺失不生成假叙事。
- Opportunity 详情完整事实、Claim Graph、原帖/视频时间戳、立场变化、权威证据、组合计划、persona 为什么不同。语料/debug 为二级。
- Persona Lab 滑杆/标签/donor组合器；自然区间、n、post IDs 同屏，三个 persona 同事件真实预览；JSON 仅高级设置。
- Visual Profile 与 Visual Grammar 量化可解释。至少真实数据可复现图、官方来源截图/原图页码、可编辑产业/事件结构图；正文图表共享事实，新数据实际重算；不只换颜色，不强制配图。
- Visual Package 包含图、不同尺寸、可编辑 Chart/Diagram Spec、原数据/出处/页码、caption/署名/alt text、正文绑定、persona/语言/版本/有效期/更新条件、权限和人工审核。检查轴/单位/数字一致、日期、溢出、中文可读性、来源、重复、旧图失效。
- 不用生图生成精确金融数据、伪造新闻/人物背书、删水印、误裁来源、公开群成员身份。实际运营/发帖仍不在范围。
- 最终演示是一个真实新事件自动采集→识别→机会卡→三个独立计划/稿/不同视觉→QA→待审→加入真实新证据自动更新。不能用 hardcoded event/static arrays/预写稿掩盖任一阶段；未自动的阶段明确标注。

## 本次核验的边界

verify_handover 的 8 个安全测试验证真实文件 hash、raw-clean 关联、profile IDs、检索时间、caption hash/链接、模型请求记录和旧稿清单。通过这些只能说明交接材料完整性；不证明内容正确性、人格化效果、端到端自动化或前端可用。当前产品验收预期 FAIL/UNKNOWN 必须真实报告。
