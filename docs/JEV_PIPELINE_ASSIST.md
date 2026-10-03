# Jev 辅助 pipeline 开发

## 2026-10-02：独立审稿意见已实现，批量外发授权待确认

用户确认“ok做”后，新增 `live/jev_advisory.py` 与 `scripts/jev_advisory_review.py`。此版本检查现有三个账号自己的保存记录，结果写入 `store/jev_advisory/`，不会写入原始 run、正文、机器 QA、人工评价或发布状态。

数据流：保存的 source / exact passages / translation / final draft / editorial decisions → 确定性字段核对 + Jev 独立问题 → 带精确输入位置的私有意见 → dashboard 折叠参考 → 实际人工审阅 → 首次人工 verdict 的理由分类与可比较维度对照。没有综合质量分，也没有自动放行或拒稿。

检查包括账号适配、选段完整/过宽、决策与自身理由矛盾、编辑指引和正文的身份归属、翻译、例子/推理、判断力度、轻编越界、新观点、QA 口吻、作者前缀、表达自然度、悬空媒体/下文、历史时间表述和来源 CTA。Jev 选择预先编号的原句；证据文字由代码从输入复制，不让模型编造引文。每个维度最多一个重点疑点，不保证穷尽。完整证据无法放入 API 上限时明确标缺口，不剪掉上下文假装检查通过。

`source_hash`、精确选段、账号/语言、当前订阅、MOVE/stop 与 translation-selection 绑定由代码检查。这仅证明保存记录字段是否一致，不能替代真实运行证据证明 cursor、重启、队列或服务在线。

**当前没有新的 15 篇 Jev 结果。** 实际批量调用被自动审批拒绝，理由是需要明确确认把这批可能含未公开稿件的材料发送到官方 TypeSafe。已向用户提出精确范围的授权问题；未重试、未改用后台绕过。`JEV_ADVISORY_ENABLED` 未设置，自动外发未启用。之前两个小型诊断的真实响应仍保留，不能冒充本轮完整审稿结果。

可审查的完整请求：[prepared_final_20261002/review_packets.json](../runs/jev_advisory_review/prepared_final_20261002/review_packets.json)。15 篇、56 个有界请求，全部符合 payload 限制；这是本地预检，不是 Jev 判断。英文 5 篇、中文 10 篇，原 run ID 与 follow-up 身份不变。

运行入口：

```sh
# 只准备请求，无外发
.venv/bin/python -B scripts/jev_advisory_review.py --packet runs/content_batch_v2/review/packet.json
# 获得本批外发授权后：读取原身份的现有稿件
.venv/bin/python -B scripts/jev_advisory_review.py --live --packet runs/content_batch_v2/review/packet.json
# 明确重试失败/中断的单条；成功结果不会反复付费请求
.venv/bin/python -B scripts/jev_advisory_review.py --live --run-id RUN_ID --retry
```

自动模式由现有 `run_monitor` 完整循环结束后调用，每轮最多 3 条，账号轮流选取自己的待复核记录。需要另行授权持续外发并设置 `JEV_ADVISORY_ENABLED=1` 后重载 monitor；当前未执行。GET / 页面刷新不调用模型。指纹绑定 source、selection、translation、draft、账号准则、决策、当前订阅和实际人审版本；版本不变不重复付费，失败不会无限重试，进程中断显示 interrupted，单条失败不改变内容循环结论。预算沿用现有累计 $100 上限。

审稿台的 Jev 结果默认折叠，与机器保真和人工接受分开。无稿记录也可显示决策参考，但不能恢复生成。人工修改版不沿用原稿意见；`save` 不算接受/拒绝，修改后的 all-pass 不能反过来算原稿 Jev 的误报。尚无实际人审时，分类和一致程度保持 pending，不编造人工标签。

刻意未做：自动重排/消耗来源候选、自动改正文/批准/发布、外部事实验证、扩大 source 或领域、依据模型自评分调写作 prompt、全 pipeline 仅凭 Jev 一票验收。候选适配目前是参考字段；要影响选题排序，仍需实际人工证据。中文与英文判断质量、真实误报漏报尚未校准。

已验证：789 项离线测试通过（含客户端、core、UI/API、monitor、CLI），JS 语法通过；本机 `/health` 正常，真实 run detail 返回 Jev pending 且原 machine_hold 和正文不变。浏览器控制未提供可用 browser surface，未声称完成截图视觉验收。监控继续在线，本轮没有新增生产稿或解除旧 hold。

以下保留较早开发探针的实际历史，与本轮批量审稿分开。

2026-10-02：已核对 TypeSafe 官方 API，准备两个真实失败案例的开发复核入口。用户配置的 `.venv/.env` 变量名已由 `type_safe(Jev)_api_key` 规范化为 `TYPESAFE_API_KEY`，值保留。完全合成的连通测试已通过真实 `jev-1.13.0` 调用：发票请求被分到 billing，HTTP 200、386 输入 token、45 输出 token。它只证明认证、请求、解析和记账可执行，不证明项目判断质量。

真实项目诊断请求最初被自动审批拒绝，未执行。用户随后明确回答 yes，授权这两条记录发送至 TypeSafe；2026-10-02T13:40:55Z 已执行原准备包。旧拒绝、缺 key 与合成测试记录均保留，不重写成成功。新调用 HTTP 200、约 0.391 秒、1,130 输入 token，估算 $0.00004746；没有修改生产状态。

实际结果：hygiene 返回 `conflict` / confidence `0.98`，与记录中动作和理由的矛盾相符；temporal 返回 `aligned` / confidence `0.56`。后者的问题把“文章发表在未来”与原理由的“文章描述尚未发生事件”混为一谈；计算发布日期先后不足以核验事件真假。该例保留为问题定义/证据不足及分歧，不能当通过或自动解除 SKIP，也不能用两个探针算准确率。请求未被修改后反复重试以追求预期标签。

Jev 输出 Choice / Score / Noul 类型的判断，不生成代码、文章或推理说明。本轮用 Choice 辅助排障；Codex 负责阅读证据、改代码和测试。官方说明：[与 coding agents 配合](https://docs.typesafe.ai/introduction/coding-agents)、[API](https://docs.typesafe.ai/api)。

## 当前最小用途

入口是 `scripts/jev_pipeline_review.py`，读取现有不可变 Store 中三条失败记录：

| 记录 | 处理 |
|---|---|
| Industry `run-7cea29b5d58a4bdf90a5d265c0e064b4` | 原探针用代码比较来源日期和 as_of；实际理由涉及文中事件真伪，题意与证据不完全对应。保留原请求作为已知局限，不将结果当作时间/事实验证 |
| Macro `run-255ebeaabc274bf39f763a9dabc18c18` | Jev 比较 hygiene 的 needs_context 动作、动作定义和该模型自己的理由；不替代读取缺失媒体，也不判定文章可发 |
| Industry `run-f6b8d62308fa43309a82aaf3bc7162a7` | content_filter 是明确的执行状态，代码直接保留，不浪费 Jev 调用，也不解除拦截 |

请求只包含所需的日期、决定和理由；完整文章、凭据、请求 headers 不进入请求。原 run 身份与内容哈希留在本地 packet。两个问题返回 `aligned / conflict / insufficient`、概率和 confidence；所有答案都只作开发参考，不拥有执行权限。

## 运行

准备并检查确切请求，不联网：

```sh
.venv/bin/python -B scripts/jev_pipeline_review.py
```

在项目 `.env` 配置自己的 `TYPESAFE_API_KEY` 后，执行一次实际请求：

```sh
.venv/bin/python -B scripts/jev_pipeline_review.py --live
```

每次创建独立 `runs/jev_pipeline_assist/<timestamp-id>/`，保存 packet、调用记录及结果。缺密钥、预算不足、网络故障、格式错误均明确返回 blocked/failed；不伪造模型答案。`--output-dir` 必须指向新目录。

客户端固定请求 `https://api.typesafe.ai/v1/systemone`，固定 `jev-1.13.0`；只读取该服务自己的 `TYPESAFE_API_KEY`，不会把现有中转站密钥发给 TypeSafe。若使用其他供应商，应先核对其原生 decision API 和认证方式，目前未实现其他供应商适配。

每次请求前使用现有预算账本预留，沿用总上限 $100。当前官方价目为每百万输入 token $0.042、输出免费，代码记录为本地估算，不是账单；未知用量保留保守预留。没有自动重试、模型 fallback 或无限循环。[官方模型和价格](https://docs.typesafe.ai/models)

## 验收与边界

- 离线测试验证合同、日志、预算、缺 key、错误响应和只读案例构建；不能证明 Jev 对本项目的判断质量。
- 需要真实调用结果，才能比较这两个诊断例的回答。它们是已知问题探针，不能当代表性准确率 benchmark。
- 即使 confidence 很高，也不修改生产 routing、source selection、正文、QA、SKIP 或人工状态。没有接入 monitor 或增加定时任务。
- 数字、日期、去重身份、cursor、target language 映射和权限仍由代码确定。官方也说明 Jev 对数字、日期比较、间接推理和不相关长上下文有弱点。[已知限制](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- 后续适合评估的用途是账号自己的候选源适配、hygiene 注解处理和已检索证据的相关性；必须先用实际中英样本与人审结果验证。Jev 的类型正确不等于事实正确，也不能绕过 NONE 或让一个事件广播给所有账号。
- Jev 不会修复翻译/轻编模型的长文本 JSON、付费墙或缺失媒体。当前生产 pipeline 的未完成项仍以 `docs/CURRENT_DELIVERY_PLAN.md` 为准。

本轮原准备包：[review_packet.json](../runs/jev_pipeline_assist/prepared_20261002/review_packet.json)。历史 prepared / blocked 文件保持原状态，新调用单独留档。

实际合成连通结果：[result.json](../runs/jev_pipeline_assist/synthetic_connectivity_20261002T133555Z_0e681e56/result.json)。这不是两个真实失败案例的诊断结果。

用户授权后的真实诊断结果：[result.json](../runs/jev_pipeline_assist/20261002T134055Z-4a11471d/result.json)。

## 目标对齐与稿件检查的合理分工

以下是建议的后续用途，尚未接成新的生产 stage：

| 检查 | 主要负责者 | Jev 可提供的帮助 |
|---|---|---|
| 每号独立来源、cursor、去重、NONE 终止、目标语言字段、队列入台 | 代码、真实运行记录与人工代码审查 | 有证据的局部语义复核，不能靠读计划判定运行已接通 |
| 选中的完整原文是否真正传入翻译，轻编是否在翻译后执行 | stage 输入/哈希/调用链检查 | 对可疑指令是否鼓励 summary → rewrite 给第二意见；不能替代调用链证据 |
| 选段是否丢掉特定理由、条件、例子或取舍 | 原文与精确段落映射，长论证由编辑核查 | 按具体已枚举内容逐项比较，返回疑点，不自己概括替换 source |
| 身份转移、额外 attribution、编辑/QA 口吻进入正文 | 对照来源、编辑指导、译文、成稿 | 对预先编号的句子或范围分类，返回 ID 与概率，不生成虚构引文 |
| 新增观点、判断力度变化、不必要的重排 | 原文/译文/成稿对照与编辑核查 | 拆成独立问题；疑似问题留给人核实，不直接删除或改稿 |
| 数字、时间、ID 与 URL 是否一致 | 确定性代码 | 已解析字段的语义用途有需要才问；精确算术和日期比较不交模型 |
| 自然中文/英文、人味、节奏、是否愿意发布 | 真实人工审阅 | 提供参考信号；不能代填不改/小改/大改/拒稿或盲评结果 |

更值得优先尝试的是：账号自己候选池内的主题适配与排序、动作/理由矛盾复核、已有检索结果的证据相关性、人工修改理由分类。来源发现仍需真实采集；JeV 不能从 bio 猜长期质量，不能靠模型知识证明 Morris 历史观点仍然成立，也不把一个事件广播给所有账号。

先只保存旁路意见，对照真实人审记录观察漏报和误报；低置信、证据不足或分歧进入复核，不直接消耗/丢弃源内容。任一真实身份或事实问题不能用其他高分抵消。官方明确英语表现较强，中文需单独验证；confidence 反映选项概率分布集中程度，不是本项目上已测得的正确率。[语言能力](https://docs.typesafe.ai/models) · [confidence](https://docs.typesafe.ai/confidence)
