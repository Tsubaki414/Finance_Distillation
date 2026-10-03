# 从“甲”找回编辑判断：证据、诊断与小规模实验

本轮以用户最新产品意图为准：preserve meaning, reasoning, texture；编辑力度取决于 source，而不是一律最小替换。已实现的账号/语言、NONE/SKIP、原文版本、出处分离和人审待定状态继续保留。

## 找回的历史证据

正式 repo 没有一份叫“甲”的原始文件。相关实验仍在 `/private/tmp/source-first-round` 与 `source-first-bodies`；本轮已逐字归档到 [history](../runs/editorial_discretion_v1/history/)，并保存 [原路径、mtime 与 SHA-256](../runs/editorial_discretion_v1/history_manifest.json)。没有重新执行旧脚本：其中 write_batch.py 会实际改生产队列，旧 API 调用也没有当前的预算预留。

- [blind_key.json](../runs/editorial_discretion_v1/history/source-first-round/blind_key.json) 的六个案例均把“甲”映射为 `B_briefed_opus`；[c_versions.json](../runs/editorial_discretion_v1/history/source-first-round/c_versions.json) 的 `jia` 与 `editorial_ab.json.briefed` 对应。这个映射有实际记录支持。
- [editorial_ab.py:137](../runs/editorial_discretion_v1/history/source-first-round/editorial_ab.py#L137) 的 writer_messages 确实拼入了 brief **和同一份 material 原文**。此前把 brief 一概视为“替代原文的摘要”过于粗糙。历史 brief 在这里是额外指导。
- 但“完整原文”有边界：`article(name, limit=5500)` 先调用 `_article_blob` 清理再截取。这个清理函数会丢短行、标题、部分强调/列表/图片行。它不是无损正文；writer 也没有读到全文后半段的保证。
- 所谓第三项“已核准事实”不是独立 factual package。WRITER 明写“原始材料里已经写出的数字和事件，没有另外一份新闻包”，user message 只是重复这个限制。不能把它当作外部事实核验。
- editor 模型参数是 `gpt-5.5`，writer 参数是 `claude-opus-5`；可证明的是脚本配置和保存的 usage，不能证明 relay 底层模型身份。甲实验缺逐次完整 transport log、response ID、finish_reason 和请求时间。已生成 [重建输入](../runs/editorial_discretion_v1/reconstructed_jia_inputs.json)，明确标为由脚本/素材重建，不能冒充找回的线上的完整请求；历史导入的 cleaner 版本也未锁定。

## 甲为什么有些地方更自然

可复用的机制是 editor 对这份材料作具体取舍，同时让 writer 接触原文。

| 实际证据 | 有价值的机制 | 不能据此推出的结论 |
|---|---|---|
| Duff 的 brief 要保留十策略/做多黄金的例子、策略与上层管理的关系、增加限制降低收益却稳定曲线的取舍；drop 指向重复比喻与重复表态 | editor 区分“有用的具体性”和“可去掉的重复”；例子不是只有核心 claim 之外的赘肉 | COMPRESS 这个标签本身会保证自然；甲仍把作者跑系统、收费的经历写成了账号第一人称 |
| SemiAnalysis 的 do_not_add 明确不许把 HiSparse 写成 NAND、不把 GB300 当绝对赢家，must_keep 指出后端、速度目标、小时成本等条件 | 针对当前 source 的技术边界能挡住笼统 persona 推演；同轮 opus_only 的 NAND、$0.238/82% 表述明显越出了该材料 | 甲技术表达全部准确：开头“省的是带宽，不是容量”仍过于绝对，原文同时承认 SDPA 局部内存消耗下降 |
| Nvidia 的 brief 要沿着回购授权、额度、时间和原作者信号解读处理，禁止自行补 GPU/供需推演 | 可读的短帖不应被产业链 persona 拉成另一篇研究 | writer 完全听从了它：甲实际增加“更该看执行节奏”“按期执行完才算兑现”等源外评价，并把短原帖扩成长稿 |
| Moontower 的 editor 选 NONE，未把数学例子强行解释成宏观交易 | 内容价值与账号适配是两件事 | 旧控制流正确：for 循环仍无条件调用 writer，NONE 仍产生了数学稿 |
| Stratechery/Net Interest 的 editor 区分两篇论证各自的贡献 | 对来源差异有意识，而不是随便拼素材 | 要恢复 MERGE：旧 schema 强制 combined_insight，恰好鼓励来源之外的新结论 |

自然度的因果证据有限：六个样本、一次随机输出，没有用同一完整 source 控制模型、prompt 和篇幅。甲的 writer 仍有“280 到 450 字、开头判断、禁止小标题”等硬要求，但六稿约 501–977 字，全部超出该目标。不能把它较好的地方归功于这条硬长度要求。其具体细节与推进感有些是原文保留下来的，有些可能是这次采样恰好较好；用户偏好也不是最终发布验收。

## 当前 v1 的问题在哪里

| stage / 结构 | 具体位置与行为 | 对内容的影响 |
|---|---|---|
| 选段 | `Pipeline.select`：短于 1,800 字符自动整条；长文只选 paragraph IDs，没有 source-specific treatment | 短帖的重复/推广不能由 editor 预先处理；长文只能决定整段取舍，缺少“这个例子值得留、此处重复可压”的指导 |
| 翻译 | [distillation_prompts.py](../live/distillation_prompts.py) TRANSLATE：“逐段…所有选中文字”“每个选中段落对应一个输出段落，ID 和顺序不变”；`segments()` 校验同序同数 | 信息保留被实现为段落/句子级机械保留，选中段内的重复同样成为必保留项 |
| 轻编 v1.4 | LOCALIZE 默认空 edits，只允许唯一匹配片段替换；`apply_localization_edits` 不接受重生段落 | 它很好地执行了上一轮“已有忠实译文，只改不自然处”，但无法承载这轮允许的合理压缩、少量重排与说明 |
| QA v1.4 | `minimal_edits`、`order_emphasis_rhythm_preserved` 与事实维度一起取 all；false 即停止 | 把编辑偏好和事实安全混成一个二元 gate；即使没有语义损失，合理的大些改动也可能被否决 |
| 数字 QA | [fidelity.py](../live/fidelity.py) 每个原文段与译文段的数字 Counter 必须相同，含出现次数 | 重复一次的同一个数不能只说一次；跨段合并也被视为不一致。应继续防止改值/改单位，同时区分删重复与删证据 |
| 作者身份 | BIO 正则只识别有限第一人称模式，其余情况下新增作者名会被视为不必要 attribution | 对个人预测/独家估算等必要归因不够细。仍需语义核对，不能一律留或一律删作者名 |
| 背景 | v1 禁止所有 external factual additions；没有按 source 判断必要背景的接口 | 防止凭空扩写是正确边界，但“已有源中可以解释的术语”和“必须外部补证的事实”不应混淆 |

“审计口吻”的已证实来源还包括测试输入污染。[原 audit 长文 fixture](audits/2026-09-29-distillation/regression_cases.json) P7–P9 **原文就含** “This supports a narrower judgment”、 “two observations should not be collapsed”、 “The source does not provide…” 和 “Adding any of those would introduce a new view…”。v1.3 翻译保留这些话不能算 writer 自行新增。本轮没有修改这些历史输入或输出来掩盖问题，也不拿这个合成样本代表真实长文的一般表现。

真实源码中，QA 在生成后运行，没有将 findings 回送 writer 的自动 repair loop；`text` 只取 localization，不拼接 QA reasons。旧 C 的 `rewrite_c.py` 依赖当时的 `public_writer.SYSTEM` 再叠加“完整、不要特别短”等要求，缺该 system 的版本快照，无法精确重建每条历史冲突。后来 method_ab.py 的 EDITOR 则明确要求“一句话”，B writer 只收到 editor 摘的 passage，且没有精确选段校验；这条已知路径确实进一步收窄了材料。当前新增局部替换 prompt 存在把注意力过多放在 QA 词语上的风险，但不能只凭 prompt 猜测它导致了上述 fixture 里的原句。

## 最小修改与边界分工

实验入口为 [EditorialPipeline](../live/editorial.py)，复用 Pipeline 的完整 source、路由、target language、终止分支、不可变快照、预算日志、重放、draft 状态及 body/metadata 导出。默认 production 仍实例化 Pipeline，不在内容尚待用户评议时批量迁移。

`source → existing account/language routing → exact selection + free-form editorial judgment → source-grounded adaptation → fidelity QA + separate editorial assessment → human-pending draft`

- 用一个 selection+editorial 请求替代旧选段：精确 source IDs + 一段自由说明，没有 KEEP/COMPRESS/EXPAND 枚举、单 thesis、固定长短或 must_keep 配额。
- writer 同时看到完整可用原文、实际选段、目标账号/语言和判断。直接翻译并编辑，不强制先生成字面稿。输出与 source 是多对多段落对照，映射供审核，不限制文章结构。
- 代码约束：合法账号/语言、NONE/SKIP 停止、完整性、精确选段、有效引用、空稿/截断/拒绝、数值/单位新值、语言错误、后台出处分离与待人审。保留独立的原文和候选稿，即使 QA 拦截也不销毁。
- editor/writer 原则：根据 source 决定编辑量、保留有意思的例子和推进、只做有作用的澄清、必要归因、避免模板。模型判断什么值得搬和如何处理。
- fidelity review：数字绑定、实体、因果、条件、语气强弱、身份、无新增结论及没有新增 QA 元说明。重复数字可合并；删掉独立信息与删掉必要支撑必须由语义核对区分。数字正则与语义核对仍不完备。
- editorial review 单独写具体观察，不以自然度、节奏、压缩比例或模板分数决定事实 pass。是否像目标账号愿意发的内容、是否编辑得恰好，留给真人评议。模型评议不写成 human approval。
- 首轮不新增自动 repair、跨源 MERGE、外部检索器或模型 A/B。外部 factual_context 为空；若不可缺少的背景不在 source 中就停止。术语/指代解释可以基于 source 现有信息。

## 实验设计与证据边界

[五份冻结输入](../runs/editorial_discretion_v1/cases.json)：Duff、SemiAnalysis、qinbafrank/Nvidia，加 HAOHONG_CFA 英文消费/财富效应帖与 kovainvest 中文 Google 财报预期帖。后两条在 prompt 编写前选定，针对本地 2,367 个保存的模型调用/实验结果做 ID 和正文前缀排除；未检出。它们本来在采集 corpus 中，这不代表此前参与写作 prompt 调试。无法证明未保存或外部会话从未用过；也不是严格独立作者盲测。

两篇长文使用保存的公开正文完整快照，保留 markdown、段落、原图链接供选择判断，不再走会丢短句/强调行的旧 cleaner。SemiAnalysis 是**完整捕获的公开部分**，付费部分并未获取，不宣称有全文授权或完成外部事实核实。需要未读图表或付费后文的选段应停止。

Nvidia 按现有账号映射为中文→英文；不因历史中文样稿而改回中文。Duff 的交易系统文章在现有四个 Macro/Industry 账号中可能为 NONE；没有生产 Trading 账号时，不会绕过路由强出稿。任何额外实验用账号须显式标为实验配置，不能冒充正式 account。

本轮原始调用、失败和最终成稿继续保存在 [实验目录](../runs/editorial_discretion_v1/)。最终结果和逐篇两轴评议见该目录 DELIVERY.md；这些是历史内容加工实验，不是当前交易或市场事实建议。

## 实际结果：有必要恢复判断，但尚未证明这个 editor 写得更好

完成五个真实 source 的路由实验，四个产生候选稿，Duff 为 NONE。现有四个账号只有 Macro / Industry 中英文号；没有为了得到 Duff 样稿强配金融账号。已提出仅实验用 Trading 配置的选项，但未收到答复，本轮不新增该账号。因此 Duff 的新编辑效果没有被测到，只能分析甲的历史样稿。

原始 v3 结果：Nvidia、HAOHONG、Kova 为 needs_review；SemiAnalysis 先因缺公式停在 needs_source。随后从同一公开网页恢复四个实际存在的代码块，建立新 source 版本再运行；候选稿生成，但 QA 缺少 editorial_review 字段而 blocked。完整旧输入、失败和正文均未覆盖。恢复公式的原文、插入锚点与前后 hash 在 [source_completion.json](../runs/editorial_discretion_v1/source_completion.json)。这只是本例的提取补全，没有读取付费段、推测公式或增加新技术结论。

逐篇阅读得到的结论和模型 QA 有差异：

- **HAOHONG** 基本保住顺序、排除条件与结尾力度，未出现 QA 解释。中文仍有“难以指望短期内有救”的拗口句；这是可以具体轻改的地方，不需要重新规划论证。原拦截来自 August/September 变成 8月/9月的数字误报。
- **Nvidia** 仍显得在解释作者：“which is where the 4% figure comes from” 不是源文的句子，且时间窗口不能独自推出回购比例。作者名本身是否必要有判断空间，不能把任何 attribution 都当错误。QA 一边指出推导不成立，一边在 editorial_review 里重复同一推导；其“a floor under the stock”修改建议还可能引入股价支撑的新意思。因此 QA 文字也不能直接当修稿事实。
- **Kova** 保住了 Cloud→capex→供给瓶颈→产业链收钱的推进与比喻。但 “For my own book” 把作者持仓移给账号，“Long $GOOGL and $MU here” 把未选中的 cashtag 推成明确做多披露。模型 QA 抓住后者，却将 identity_preserved 判为 true。editor 已把 bare tags 解释成持仓，writer 随后进一步具象化，说明 guidance 仍可能成为幻觉起点。
- **SemiAnalysis** 候选保住了大量数字、模式取舍、门槛与公式；也选得过宽，横跨 HiSparse、DSA、roofline 和 IndexShare。开头许诺存储市场/实际 serving，结尾却停在架构吞吐，文章范围没有编辑干净。“正如我们在 Kimi K3 那篇文章里解释过的”仍挪用了原媒体的既往发表经历，模型 QA 没有抓住。长稿末尾不是靠审计口吻收束，但术语处理与中文句法仍显机械；“如何被服务”等句子并不自然。不能称为成熟成稿。

这些是本助手的逐篇阅读结论，**不是人工验收结果**。真实编辑体验仍需用户评议。仅靠一次模型 pass，不足以证明 attribution、力度和必要补充完全正确。

## 实验后仅修控制问题，未用 holdout 继续调 prompt

v3 prompts 在两条 holdout 出稿前冻结，之后保持字节不变。代码另升为 `editorial_discretion_experiment_v1.1`：

1. 明确日期语境里的英文月份进入数字归一化，避免 8月/9月误报；不把一般 modal “May” 当月份。
2. 无局部作者归因的第一人称持仓/账户等表达进入 human review，即使语义 QA 错判通过。该检测范围有限，不是完整叙述身份解析。
3. 缺 editorial_review 标为 missing_assessment，不再将缺自然度评议等同于事实失败。必需的 fidelity 检查仍完整保留。

使用原始 stage 响应做了 [零网络控制回放](../runs/editorial_discretion_v1/control-replay-v1.1/summary.json)，候选正文逐字不变、source hash 不变、没有重新请求 QA：HAOHONG 变为 draft_ready / human pending，其余仍停止或待复核。不能将这个回放称为新的模型通过率。121 个离线测试通过。

仍未修的技术问题包括：带共享单位的中英文数值区间（如 1800到1900亿 / $180–190B）解析、技术公式和过短术语行的语言误报、正文证据链接与 provenance footer 的区别、广义作者研究/发表经历识别。现有数字库存也不能证明每个数与实体的绑定正确。它们是实际复现的限制，绝不以把 QA 全放松来消除红灯。

建议保留这个轻量实验接口，暂不替换生产默认。editor 的价值应集中在范围、冗余、例子和所需背景判断；目前它仍会给短帖写过长的解释，甚至制造不存在的推导。下一轮应先解决这些已见问题，再用全新材料评估；本轮不通过不断重抽样把失败洗成成功。
