# Source discovery review · account sources v1

2026-09-30。执行的是三个已确认的信息世界。角色均为**针对账号的订阅提案，人工 source review pending**，本报告没有启用新订阅、切换生产、调用 relay 或生成文章；已把有限已订阅source原帖导入各自inbox，均保留来源缺口。

## 结果与采样边界

共审阅 **27 个 source/account 配置候选（Macro 13、Industry 13、Morris 1）**，保存 **103 个具体内容例子**。网络采集为 19 个 publisher feeds 的最近至多12条，共218条；另有6个官方数据页面、7个已发现的上游链接检查、8个摘要源文章检查。所有原始响应、抓取时间、URL、哈希和正文仍保留。

这是可用的第一轮内容证据审核，不是完整历史评级：逐源筛查有界 feed 样本，重点读2–3个具体正文/公开部分；未取得完整6–8周社交时间线，不能给出总体原创率、signal密度百分比或时效排名。表里的质量描述只限所见样本。英文信息是否在中文生态稀缺尚未验证，所有 cross-language scarcity 为 unknown；不给“高信息差”虚分。

已读 agent-reach 网页/RSS 路由，实际走公开 RSS/Jina。doctor 因要 chmod 工作区外的 ~/.agent-reach 失败；未修改其配置。**更正：本轮此前把旧 skills.lock 的 Xquik disabled 错当成当前唯一采集授权，漏读了 CLAUDE.md:167–180 已授权的 Apify 路径。主代理已验证 Apify 账户 API 可用、tweet-scraper actor 有效。** 随后已执行40个有界Apify查询，取得277个唯一原帖，实际费用$0.122。新增固定周窗口提高了年份/时点覆盖，仍非完整时间线。[本轮实际X审计](../runs/account_sources_v1/discovery/X_SAMPLE_AUDIT.md)。[更正记录](../runs/account_sources_v1/discovery/APIFY_CORRECTION.json)。

最有实际影响的发现：

- 旧 corpus 的4,000字符并不总是付费墙：同一条公开 feed 中，Liberty Street Economics、Sahm、SemiAnalysis、Stratechery 等能取得更长正文。SemiAnalysis依然有明确付费尾部，**更长不等于全文**。
- Fabricated Knowledge当前feed有12条，但最新两条各只有9字符“Read more”；可读的代表例子在6月、2月、1月。应是有价值的历史/访谈候选，不能现在认定为及时的日常 CORE。
- The Next Platform feed 12条正文为0；直接网页的两篇可读。ServeTheHome/RBN/Wolf Street feed也多为摘要。默认把feed title/summary当article会直接损失价值。
- RBN一篇文章检查返回CAPTCHA；ASML被引用的High-NA链接返回404。HTTP 200来自reader不代表源内容可读。这两处已标明，未绕过。
- 新的Damodaran/旧Blogger记录存在Atom首个link为comments的情况。此证据包取rel=alternate的正文链接，不把评论feed当原文。

## A. Top candidates / 每账号订阅提案

所有source已保存可追溯例子；CORE指建议日常看，SECONDARY指topic命中，EVENT_ONLY指明确官方release事件，RESEARCH_ONLY不独立出稿，WATCHLIST尚需补证。未按粉丝数排序。

### EN Morris Archive

| Source / Platform / Language | Subdomain | Originality / 所见 signal | Timeliness / cross-language | Fit / role / confidence |
|---|---|---|---|---|
| **Morris_LT** · X (existing ranked search import) · zh | Morris historical evergreen frameworks, industry explanations | 139 directly attributed Morris posts observed; many life aphorisms/replies/news. Author identity does not prove originality or evergreen worth. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **CORE** · medium on observed content; low on whole-source/general timeliness<br>唯一主作者池；今天仍有价值的历史内容→英文翻译+轻编；不要求添加新观点。<br>[证据 x_Morris_LT](#source-x_morris_lt-en_morris_archive) |

### 中文 Macro / Data Flow

| Source / Platform / Language | Subdomain | Originality / 所见 signal | Timeliness / cross-language | Fit / role / confidence |
|---|---|---|---|---|
| **Liberty Street Economics** · newsletter/web · en | repo, treasury market structure, monetary implementation | 原始研究/官方研究；不等同 FOMC 官方政策立场。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **CORE** · medium-high<br>研究团队用 repo 参与者、固定收益指数定价时点与市场微观结构解释机制；不同于只转发利率涨跌。<br>[证据 libertystreet](#source-libertystreet-zh_macro) |
| **Matthew C. Klein** · newsletter/web · en | inflation, rates, nominal income | 原创解释，明确链接 Fed/BEA/BLS；付费尾部未取得。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>连续三篇检验加息、通胀预测模型及名义收入/收益率关系；保留和 Sahm 不同的政策解释。<br>[证据 overshoot](#source-overshoot-zh_macro) |
| **Conks** · newsletter/web · en | repo, liquidity, money markets, market plumbing | 机制解释 + 数据汇编，snapshot 注明 Treasury/FRBNY/OFR 等数据源。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>补 Treasury cash、SOFR/IORB、repo clearing 和利率曲线 plumbing；不是股票评论。<br>[证据 conks](#source-conks-zh_macro) |
| **Claudia Sahm** · newsletter/web · en | inflation, employment, monetary policy | 作者原创政策解释，引用 FOMC/SEP/研究；个人上镜/照片须隔离身份。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium-high<br>把供给冲击、利润率、就业成本和央行沟通放在同一政策取舍里，不只预测一次会议。<br>[证据 claudiasahm](#source-claudiasahm-zh_macro) |
| **Nathan Tankus** · newsletter/web · en | monetary institutions, liquidity, financial structure | 原创长文/引述混合，政治机构和个人开场占比不小。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>家庭金融组织、央行前瞻指引和流动性危机提供制度解释；只按这些 topic 入队。<br>[证据 crisesnotes](#source-crisesnotes-zh_macro) |
| **Adam Tooze** · newsletter/web · en | macro history, capital flows, political economy | 所见样本主要链接汇编/极短导语，不能据声誉认定原创正文质量。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **RESEARCH_ONLY** · low<br>用来发现上游文章；当前可见 Top Links 不足以作原创主稿。<br>[证据 chartbook](#source-chartbook-zh_macro) |
| **Wolf Richter** · newsletter/web · en | labor data, rates, credit | 原创数据评论；当前 Anthropic leaked-prospectus 题不适合此号默认订阅。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>限定官方数据解读/劳动力和信贷；完整检查 labor-turnover 文能看到 quit/layoff/hire 分拆。<br>[证据 wolfstreet](#source-wolfstreet-zh_macro) |
| **BLS** · official web/data · en | employment, inflation | Primary issuer/data publisher; not editorial interpretation. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **EVENT_ONLY** · high for publisher identity; content selection pending human<br>Employment household/establishment distinction and CPI tables; fixed releases are primary facts.<br>[证据 bls](#source-bls-zh_macro) |
| **BEA** · official web/data · en | GDP, PCE, income | Primary issuer/data publisher; not editorial interpretation. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **EVENT_ONLY** · high for publisher identity; content selection pending human<br>GDP and PCE data landing pages provide release/data entry points, not an account-ready post.<br>[证据 bea](#source-bea-zh_macro) |
| **Federal Reserve** · official web/data · en | monetary policy, balance sheet | Primary issuer/data publisher; not editorial interpretation. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **EVENT_ONLY** · high for publisher identity; content selection pending human<br>H.4.1 tables and dated FOMC statement serve policy/balance-sheet events or verification.<br>[证据 fed](#source-fed-zh_macro) |
| **US Treasury** · official web/data · en | issuance, cash balance, funding | Primary issuer/data publisher; not editorial interpretation. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **EVENT_ONLY** · high for publisher identity; content selection pending human<br>Refunding documents and Daily Treasury Statement define fiscal cash/issuance primary layer.<br>[证据 treasury](#source-treasury-zh_macro) |
| **洪灝** · X (existing import only) · zh/en | China macro, cross-asset | Concrete bank-capital/loan-demand and consumption-policy arguments coexist with podcast/book/personal-performance promotion. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **WATCHLIST** · medium on observed content; low on whole-source/general timeliness<br>访谈入口待补原始 transcript；不能以中英双发重复计 source signal。<br>[证据 x_HAOHONG_CFA](#source-x_haohong_cfa-zh_macro) |
| **qinbafrank / Macro scoped** · X (existing import only) · zh | liquidity, rates, policy, capital flows | Long authored interpretation mixes own views, self-quotes, named third-party frameworks, filings/call claims, and commercial posts; ownership must remain separated. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium on observed content; low on whole-source/general timeliness<br>只取政策/流动性/资本流机制；公司财报和加密交易所宣传不自动入Macro。订阅已有，source质量仍待人审。<br>[证据 x_qinbafrank](#source-x_qinbafrank-zh_macro) |

### 中文 Stocks / Industry

| Source / Platform / Language | Subdomain | Originality / 所见 signal | Timeliness / cross-language | Fit / role / confidence |
|---|---|---|---|---|
| **SemiAnalysis** · newsletter/web · en | semiconductors, AI infrastructure, datacenter power | 独立测评、技术分析和自有模型并存；营销 CTA 与付费尾部需注释。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **CORE** · medium-high<br>技术实现/benchmark/teardown 和项目级数据口径，是与宏观账号不同的核心信息。<br>[证据 semianalysis](#source-semianalysis-zh_industry) |
| **Fabricated Knowledge** · newsletter/web · en | memory, semiconductors, datacenter networking | 原创分析 + 嘉宾对话；必须保留 Doug/Val/其他嘉宾的说话人关系。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>有机器人执行器成本、KV cache/offload 从业者访谈和 memory/optics 周期框架。<br>[证据 fabricatedknowledge](#source-fabricatedknowledge-zh_industry) |
| **Claus Aasholm** · newsletter/web · en | semiconductor companies, supply chain, business models | 原创观点/数据图表与个人从业经历混合。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>Samsung 组织与内部利润、Broadcom 收入结构、Nvidia 战略维度；补公司层面视角。<br>[证据 clausaasholm](#source-clausaasholm-zh_industry) |
| **The Semiconductor Engineer** · newsletter/web · en | process research, materials, photonics | 主要是研究聚合/摘要；不能冒称每条是 firsthand channel check。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **RESEARCH_ONLY** · medium<br>作为论文/技术 primary discovery：制造工艺 monitor 有 DOI、imec 原文和明确限制。<br>[证据 semiengineer](#source-semiengineer-zh_industry) |
| **The Next Platform** · newsletter/web · en | datacenter systems, servers, interconnect | 技术报道/作者分析，另有 sponsored 项，须逐条区分。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>补系统架构和计算经济性；两篇实读网页分别为 AMD 模型布局和量子纠错的 CPU 开销。<br>[证据 nextplatform](#source-nextplatform-zh_industry) |
| **ServeTheHome** · newsletter/web · en | server hardware, CPUs, datacenter systems | 产品解释/测试/活动混合；样本不是所有内容都 firsthand 实测。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>补服务器产品/平台边界，EPYC 分层文章区分 scale-up、scale-out、agentic CPU 类别。<br>[证据 servethehome](#source-servethehome-zh_industry) |
| **Ben Thompson** · newsletter/web · en | platforms, agents, business models | 原创框架与引用分明；weekly roundup 不作一篇新原创。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium-high<br>App→agent 的入口/分发机制以及前沿模型的商业壁垒，限定相关公司/行业机制主题。<br>[证据 stratechery](#source-stratechery-zh_industry) |
| **Marc Rubinstein** · newsletter/web · en | financial services, AI financing, business models | 作者分析和第一人称产品体验混合，引用原始发布/播客/数据。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium<br>用在金融服务/AI融资机制：agent 降低保险转换摩擦、GPU租金与融资结构。<br>[证据 netinterest](#source-netinterest-zh_industry) |
| **RBN Energy** · newsletter/web · en | natural gas, LNG, power supply | 可见摘要有具体产业容量/供需机制，但尚不足认定正文质量。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **WATCHLIST** · low<br>天然气管道、储气和 LNG 需求可能填 data center 能源供给空缺。<br>[证据 rbnenergy](#source-rbnenergy-zh_industry) |
| **Doomberg** · newsletter/web · en | energy infrastructure, midstream | 观点文章，引用新闻，当前可见是付费导语。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **WATCHLIST** · low<br>仅考察能源供给/基础设施；不把强政治修辞或新闻判断默认搬入 Industry。<br>[证据 doomberg](#source-doomberg-zh_industry) |
| **Aswath Damodaran** · newsletter/web · en | valuation, business economics, capital allocation | 原创教学型框架、公开数据表，非 firsthand supply-chain。 <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium-high<br>利率与股价、扩张与盈利的取舍、AI商业化问题；补估值机制，非芯片新闻替代品。<br>[证据 damodaran](#source-damodaran-zh_industry) |
| **qinbafrank** · X (existing import only) · zh | company capital allocation, industry | Long authored interpretation mixes own views, self-quotes, named third-party frameworks, filings/call claims, and commercial posts; ownership must remain separated. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium on observed content; low on whole-source/general timeliness<br>仅公司/行业帖进本账号；最新8条有CEX危机与宏观流动性，不能全部订阅成 Industry candidate。<br>[证据 x_qinbafrank](#source-x_qinbafrank-zh_industry) |
| **Dylan Patel / @dylan522p** · X (existing import only) · zh | AI infrastructure, semiconductor, HBM, power/grid, packaging | Grid modeling, HBM revisions and physical-package research pointers coexist with many replies; some published research is on SemiAnalysis, not in the X caption. <br> 总体signal未估计 | 日期保留；未量化先后优势；跨语言稀缺性unknown | **SECONDARY** · medium on observed content; low on whole-source/general timeliness<br>具体产业线索有价值，但56条所见样本含34条reply、设备/雇佣/客户身份与轻闲聊；按topic找原报告和工程证据，不能整条时间线全收。<br>[证据 x_dylan522p](#source-x_dylan522p-zh_industry) |

## B. Hidden gems

本轮**没有足够证据把任何人标成“粉丝少的 hidden gem”**：没有采粉丝规模，也没有完整引用网络。以下是从实际专业链接发现、值得继续审计的较窄节点，不冒充小号排行榜：

| 上游节点 | 发现依据 | 可补什么 | 状态 |
|---|---|---|---|
| OFR repo研究作者 Ashlyn Cenicola / Melanie Friedrichs / Robert Mann / Luke M. Olson；R. Jay Kahn / Neth Karunamuni / Mark Paddrik | LSE repo参与者一文直接链接2025规模研究和2026韧性研究；两篇原文已取得 | repo规模、未清算部分、网络/operational风险，少一层新闻转述 | 内容例子成立；各人持续产出/账号与规模未审 |
| SGLang / HiSparse项目作者网络 | SemiAnalysis GLM文章引用HiSparse；4月10日原始技术文已取得，早于9月28日分析 | 层级内存、稀疏注意力实现与benchmark原始解释 | 可作Industry research seed；未审核作者个人时间线 |
| imec photonics research | Semiconductor Newsletter引用9月21日Ge/Si APD发布，9月26日再解读 | 光通信/制造能力边界，避免只订阅投资评论 | 已取得原始发布；需区分vendor/research组织宣传与独立验证 |
| Val Bercovici相关访谈线索 | Fabricated Knowledge 2月访谈逐字稿有明确Doug/Val说话人 | KV cache、memory/network实践问题 | 职务、持续覆盖与外部账户尚未独立验证 |

## C. Redundant accounts / 去重与互补

- **Overshoot + Sahm**：都引用同一FOMC statement、press conference、关税FEDS note与Jackson Hole speech。底层事实去重共享，政策解释仍不同；不因共同链接把两位作者合成一篇新结论。
- **Chartbook Top Links + Credit Bubble daily links**：本轮看到的都是上游发现入口，不应把每天链接汇编重复当原创稿件。Credit Bubble此次12条多为新闻链接清单，保留为研究线索即可。
- **Semiconductor Newsletter + SemiAnalysis**：前者主要定位论文/制造研究索引，后者保留技术分析、测评与项目模型。不要给聚合摘要贴firsthand标签。
- **SemiAnalysis + Fabricated Knowledge + Claus Aasholm**：memory/AI资本开支重叠，但技术实现、从业者访谈、公司结构可各自补位；按topic拆订，不按相同ticker全部复制入队。
- **Stratechery + Net Interest agent主题**：共享agent入口问题，但后者聚焦金融服务摩擦；作者个人汽车/保险例子不得变成账号经历。禁止自动MERGE产生两篇都没有的结论。
- **洪灝中文/英文访谈宣传**：9月27日两条属于同一9月25日节目家族，不当两份独立研究信号；8月英文帖明确说内容并非中文节目的逐字翻译，不能声称两种语言版本正文完全相同。
- 同一publisher free article / weekly round-up / X推广帖按原始文章归并；引用该文的另一作者，保留其新增论证与单独身份。

## D. Rejects / 对这三个账号不合适的默认订阅

这里拒绝的是具体账号的候选入口，不是判作者总体低质量。

| Source / 内容 | 对哪个账号 | 处理 | 实际依据 |
|---|---|---|---|
| Morris之外的作者作主稿 | en_morris_archive | REJECT | 账号就是Morris历史内容英文evergreen，不能用泛金融主稿替换 |
| Moontower数学cheatsheet / soulcraft | 三个当前账号的默认主稿流 | REJECT；特定vol机制研究可另案审查 | [Taylor Expansion cheatsheet](https://moontowermeta.com/taylor-expansion-cheatsheet/)主要是数学说明；提及债券不构成Macro选题理由。[soulcraft](https://moontowermeta.com/soulcraft/)为艺术/生活主题 |
| EmberCN鲸鱼持仓/交易与CTA | Macro / Industry默认源 | REJECT | [鲸鱼仓位例子](https://x.com/EmberCN/status/2104511893872549888)附Bitget推广；不等于宏观flow研究。[财库更新](https://x.com/EmberCN/status/2104555828972056630)可按需回到公司原披露核查，不能全源订阅 |
| TraderFeed交易心理/教练材料 | 当前三号默认主稿 | REJECT | 本地How to Become Your Own Trading Psychologist / How To Build A Career In Trading 是交易习惯/教练，不是Macro/Industry当前读者任务，也不是Morris |
| 裸BLS/FOMC发布 | zh_industry / Morris默认候选 | REJECT admission | 共享事实可查，但没有该账号自己的source把它连接到行业机制，就不创建候选 |
| qinbafrank的CEX危机处理/币市短期流动性 | zh_industry | Topic reject | [CEX例子](https://x.com/qinbafrank/status/2104556857356607958)、[币市流动性例子](https://x.com/qinbafrank/status/2104419595348304256)不能因为同一作者写过NVDA就混入Industry |

## E. Missing source types / 尚未填满的世界

- **Morris**：新采139个唯一帖（2024年60、2025年59、2026年20），作者ID与quote/reply/media关系已保存；13窗全部满额，多数旧周窗只覆盖末日，仍缺代表性年份/主题分母及逐篇当下有效性。不能把覆盖年份冒充历史库完整。
- **Macro**：positioning、options/vol、fund flows、rates trader/practitioner仍少；当前更强的是宏观政策和repo解释。中文本地市场plumbing/人民币资金/监管一手材料覆盖仍不足。
- **Industry**：独立光通信/电力工程师、真正供应链从业者、公司earnings/filings/投资者日原文连接不足。当前public研究文章比firsthand practitioner更充足，不能靠多订newsletter冒充补齐。
- **跨语言信息差验证**：没有另一语言社区的对照样本和查询日志，不能从英文source自动推断稀缺。
- **质量与时效**：没有全部source的6–8周完整内容分母、原创/噪音人工标签、重大事件时间对齐；也没有真实人工订阅审批。这些均未伪造为机器分数。

## F. Suggested next seeds / 实际上游扩展

对10个有具体内容的publisher扩一层，保存430条原始链接边（含self-reference），6个被至少两个publisher引用的共同上游URL。它们只是“引用/参考”观察，不是赞同关系、信息领先证明或社交centrality排名。

| Seed | 原始发现路径 | 下一步 |
|---|---|---|
| OFR repo项目与作者 | [LSE参与者文](https://libertystreeteconomics.newyorkfed.org/2026/09/whos-borrowing-and-lending-in-repo-markets/) → [2025 repo规模](https://www.financialresearch.gov/the-ofr-blog/2025/12/04/sizing-us-repo-market/) / [2026网络韧性](https://www.financialresearch.gov/the-ofr-blog/2026/02/10/resilient-repo-market-cyber-induced-outages/) | Macro研究/事实层，检查同团队其他连续产出 |
| NY Fed Treasury研究作者及NISA | [strike-time文章](https://libertystreeteconomics.newyorkfed.org/2026/09/treasury-trading-at-the-close/) → BrokerTec方法、早期研究、NISA 2021材料 | rates/market-structure practitioner线；NISA未深审，先WATCHLIST |
| SGLang / vLLM / THUDM slime | [SemiAnalysis GLM](https://newsletter.semianalysis.com/p/sparse-savings-persistent-demand-inside-glm53) → [HiSparse](https://www.lmsys.org/blog/2026-04-10-sglang-hisparse)、具体PR/论文 | Industry工程原始层；不自动将所有repo活动变成候选 |
| imec / 原论文作者 | [周度制造研究](https://thesemiconductornewsletter.substack.com/p/weekly-monitor-on-semiconductor-process-aa3) → [100GHz APD发布](https://www.imec-int.com/en/press/imec-debuts-100-ghz-gesi-avalanche-photodiode-apd-enabling-net-400-gbps-data-reception-just-5)与DOI | optical/photonics，检验可制造性和实验边界 |
| Intel / Applied Materials / Lam技术材料 | SemiAnalysis Panther Lake teardown的实际链接/专利/论文 | 公司工程原始层，区别vendor主张和独立验证；不靠新闻再转述 |
| Silicon Data / 原访谈嘉宾 | [Net Interest融资文](https://www.netinterest.co/p/financing-the-ai-boom-3) → [GPU价格index](https://portal.silicondata.com/silicon-index) / Colossus原播客 | GPU租金/融资上游，价格口径、样本和商业访问仍需核查 |
| Val / memory与network从业者 | Fabricated Knowledge有说话人区分的KV cache访谈 | 找持续技术内容，不能把嘉宾一次出现当稳定source批准 |

ASML原引用404保留为failed edge，不能写成“已验证primary”。OFR repo规模正文标注2025-12-04，而reader头部有2026-09-24，前者是发表日期，后者不能用于抢先时效判断。

## Morris archive专项

历史基线：58条匹配记录来自60条ranked search结果；覆盖日期2024-07-18至2026-09-30，但分布为2024年7条、2025年2条、2026年49条。覆盖了年份不等于有代表性年份采样。56条post_type=original_or_unknown、2条reply，58条author_id为空，不能将unknown翻译成“原创”。

- 有可继续选段的framework：测试/反馈中寻找正确方向、AI基础设施→工具→agent三个阶段、组织赋予价值与可迁移能力。每篇仍需内容筛选，不能只凭机器完整性放行。
- 明确身份/上下文风险：2024年的“冯唐说”和“宋教授说”不是Morris自己的经历/发言；后者缺视频。旧图文和健康材料不应强造evergreen金融稿。
- 含付费咨询/订阅的帖子，以及来源自己写的转载条件，作为provenance/rights-context注释保留；不进入公开正文，不由模型自动许诺可转载。
- 本轮已补5个半年窗与8个固定旧周窗，共139个唯一Morris帖，全部有author ID。2026年概率/幂律/决策迁移有3条文字framework值得继续审；2024/2025样本包含过期行情、个人家产、医疗断言和生活格言，已逐条列出hold/reject。完整证据和抽样偏差见[X_SAMPLE_AUDIT](../runs/account_sources_v1/discovery/X_SAMPLE_AUDIT.md)，不宣称archive完整。

## 交付文件与接线边界

- [机器可读订阅提案 + evidence](../runs/account_sources_v1/discovery/source_audit.json)：27个候选、103例、账号角色/范围/状态/文本可用性。
- [可导入原文](../runs/account_sources_v1/discovery/usable_sources.json)：10条精确decoded-feed原文，8条结构完整文本、2条SemiAnalysis明确partial。这不是10篇已通过人审或可发稿。
- [引用边](../runs/account_sources_v1/discovery/citation_edges.json)、[共同上游](../runs/account_sources_v1/discovery/shared_upstreams.json)。
- [公开采集日志](../runs/account_sources_v1/discovery/collection.json)、[上游检查](../runs/account_sources_v1/discovery/upstream_collection.json)、[摘要补全文检查](../runs/account_sources_v1/discovery/article_checks.json)。
- raw/保留原始响应；normalized/保留完整feed正文/链接。Morris/local import snapshot独立保存。

原文不先清洗成摘要。来源的照片/头像/CTA/图表等metadata仍保留；头像和装饰图不作为必需依赖，其余图表按选段判定必要性，不把整篇一律hold。source quality pending human、machine fidelity、正文可发性是三个独立状态。

## 新增X实采与账号inbox

40个run，305个dataset items，其中7个noResults占位；298次post观察，去重277帖。实际$0.122。22条intake尝试产生17个新候选（Morris12、Macro3、Industry2），全部needs_source；5条被挡。机器fidelity未运行、source质量待人审、没有新稿。279条带raw pointer的quote/reply/link/mention边已保存。

[逐源实际读后判断与缺口](../runs/account_sources_v1/discovery/X_SAMPLE_AUDIT.md) · [可导入行](../runs/account_sources_v1/discovery/x_ready_import.json) · [入库结果](../runs/account_sources_v1/discovery/x_intake_results.json) · [逐窗覆盖与费用](../runs/account_sources_v1/discovery/x_sampling_audit.json)。

Industry当前topic关键词会漏掉PJM/grid、Micron/SK Hynix、DRAM/XTEM；三条真实例子已保留，未在采样时改变订阅边界。Source被抓到、被账号接收、被编辑选中、机器保真、人工可发是不同状态。

后续已独立读取3个Morris原帖页面，确认其单帖body完整且与捕获逐字一致，无媒体/回复/quote依赖；3个新source版本进入pending_selection，保留旧17个needs_source版本。全部是2026-06-30历史帖，不冒充2024/25代表样本；没有事实核验或人工质量批准。[验证证据](../runs/account_sources_v1/discovery/morris_verification/verified_import.json)。

## 每源具体内容证据

以下每条都能定位到保存的全文/公开部分或明确的摘要。长文章不是因为有URL就算读到完整原文；缺失状态列在每源下。

<a id="source-libertystreet-zh_macro"></a>
### Liberty Street Economics → zh_macro · CORE

研究团队用 repo 参与者、固定收益指数定价时点与市场微观结构解释机制；不同于只转发利率涨跌。

采样：`{"from": "2026-08-10T11:00:00+00:00", "to": "2026-09-30T11:00:00+00:00", "entries_seen": 100, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 12, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：完整公开正文；图表仍需视觉核对。

- [The Role of Repos in Monetary Policy Implementation](https://libertystreeteconomics.newyorkfed.org/2026/09/the-role-of-repos-in-monetary-policy-implementation/) · Wed, 30 Sep 2026 11:00:00 +0000 · `libertystreet-00` · 12169字符。把 repo 作为政策执行工具，区分中央银行与私人参与者动机。
- [Who’s Borrowing and Lending in Repo Markets?](https://libertystreeteconomics.newyorkfed.org/2026/09/whos-borrowing-and-lending-in-repo-markets/) · Mon, 28 Sep 2026 11:00:00 +0000 · `libertystreet-02` · 11722字符。逐类解释现金贷出方、借入方与抵押品；链接 OFR 2025/2026。
- [Treasury Trading at the Close](https://libertystreeteconomics.newyorkfed.org/2026/09/treasury-trading-at-the-close/) · Tue, 22 Sep 2026 11:00:00 +0000 · `libertystreet-03` · 9427字符。用指数 strike-time 从3pm改4pm的事件讨论交易集中时点。

<a id="source-overshoot-zh_macro"></a>
### Matthew C. Klein → zh_macro · SECONDARY

连续三篇检验加息、通胀预测模型及名义收入/收益率关系；保留和 Sahm 不同的政策解释。

采样：`{"from": "2026-05-02T00:45:27+00:00", "to": "2026-09-24T22:20:06+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 11, "ends_read_more": 12, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：公开开头可评方向；不能把 Read more 前的正文当完整文章。

- [The Fed Finally Gets It](https://theovershoot.co/p/the-fed-finally-gets-it) · Thu, 24 Sep 2026 22:20:06 GMT · `overshoot-00` · 4418字符。评估加息的理由并区分关税/能源与名义需求。
- [Just Waiting for Disinflation is Not Enough](https://theovershoot.co/p/just-waiting-for-disinflation-is) · Mon, 14 Sep 2026 23:43:01 GMT · `overshoot-01` · 3397字符。追到 Fed staff 通胀模型与2025回顾论文，讨论模型设定。
- [Rising Bond Yields Are Good, Actually](https://theovershoot.co/p/rising-bond-yields-are-good-actually) · Tue, 01 Sep 2026 03:53:47 GMT · `overshoot-02` · 6120字符。将利率水平放入收入增长和生产率背景；不是涨息必跌股。

<a id="source-conks-zh_macro"></a>
### Conks → zh_macro · SECONDARY

补 Treasury cash、SOFR/IORB、repo clearing 和利率曲线 plumbing；不是股票评论。

采样：`{"from": "2026-06-17T22:41:58+00:00", "to": "2026-09-29T23:17:06+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 5, "ends_read_more": 4, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：7/12 条是 infographic 类型；仅文字会丢机制图。snapshot 有强日期依赖。

- [Money Market Snapshot](https://www.conks.plumbing/p/money-market-snapshot) · Tue, 29 Sep 2026 23:17:06 GMT · `conks-00` · 4649字符。日期化 bill/TGA/reserves/SOFR 与 basis 数据快照。
- [The Repo Dark Spot: Part I](https://www.conks.plumbing/p/the-repo-dark-spot-part-i) · Sun, 13 Sep 2026 20:45:05 GMT · `conks-02` · 2612字符。讨论强制 repo central clearing 的摩擦，图像/footnote不足。
- [Plumbing Feed: Adventures at the Long-end of the Curve](https://www.conks.plumbing/p/plumbing-feed-adventures-at-the-long) · Sat, 12 Sep 2026 12:04:05 GMT · `conks-03` · 8554字符。长端收益率 plumbing 与融资机制；需要图表。

<a id="source-claudiasahm-zh_macro"></a>
### Claudia Sahm → zh_macro · SECONDARY

把供给冲击、利润率、就业成本和央行沟通放在同一政策取舍里，不只预测一次会议。

采样：`{"from": "2026-07-13T01:41:34+00:00", "to": "2026-09-21T00:47:25+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 10, "ends_read_more": 2, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：前三篇正文有完整结尾；不能将作者采访/拍照经历转成账号经历。

- [Questions for the Chair](https://stayathomemacro.substack.com/p/questions-for-the-chair) · Mon, 21 Sep 2026 00:47:25 GMT · `claudiasahm-00` · 12240字符。会议决定与主席沟通分开，问题按政策机制组织。
- [Costly medicine](https://stayathomemacro.substack.com/p/costly-medicine) · Mon, 14 Sep 2026 21:39:29 GMT · `claudiasahm-01` · 6784字符。加息可能把能源成本从售价压向利润，同时损伤就业；保留取舍。
- [Something is shifting in the inflation picture](https://stayathomemacro.substack.com/p/something-is-shifting-in-the-inflation) · Mon, 07 Sep 2026 21:40:41 GMT · `claudiasahm-02` · 9039字符。比较通胀变化、供给冲击和政策阈值，不只给单一结论。

<a id="source-crisesnotes-zh_macro"></a>
### Nathan Tankus → zh_macro · SECONDARY

家庭金融组织、央行前瞻指引和流动性危机提供制度解释；只按这些 topic 入队。

采样：`{"from": "2026-07-14T11:00:41+00:00", "to": "2026-09-15T10:55:57+00:00", "entries_seen": 15, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 12, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：部分 premium 正文截在核心论证前；不是所有政治制度文章都适合 Macro。

- [The Household in The Hierarchy of Finance in a Capitalist Economy (Part One)](https://www.crisesnotes.com/the-household-in-the-hierarchy-of-finance-in-a-capitalist-economy-part-one/) · Tue, 15 Sep 2026 10:55:57 GMT · `crisesnotes-00` · 7215字符。金融层级中的家庭法律/组织形式；付费内容不全。
- [That’s Not the Warsh of It: The End(ish) of Forward Guidance and the Rise(?) of Treasury Monetary Policy](https://www.crisesnotes.com/thats-not-the-warsh-of-it-the-end-ish-of-forward-guidance-and-the-rise-of-treasury-monetary-policy/) · Wed, 02 Sep 2026 10:59:42 GMT · `crisesnotes-01` · 15978字符。前瞻指引与财政货币政策，原文含人物/政治判断。
- [The Great Financial Crisis of 2007-2009 Was First and Foremost a Liquidity Crisis: Lessons for the Data Center Financial Crisis Debate](https://www.crisesnotes.com/the-great-financial-crisis-of-2007-2009-was-first-and-foremost-a-liquidity-crisis/) · Tue, 11 Aug 2026 10:59:53 GMT · `crisesnotes-03` · 4984字符。区分流动性与偿付危机，主要论证在付费后。

<a id="source-chartbook-zh_macro"></a>
### Adam Tooze → zh_macro · RESEARCH_ONLY

用来发现上游文章；当前可见 Top Links 不足以作原创主稿。

采样：`{"from": "2026-09-21T10:04:46+00:00", "to": "2026-09-30T10:19:50+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 2, "ends_read_more": 10, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：12 条抽样多数是付费短预览；没有足够完整正文审核 signal density。

- [Top Links 1240 Debt service and the Pentagon. Private equity and the politics of the US housing market. The return of black lung disease & the Franco-Prussian war in color. ](https://adamtooze.substack.com/p/top-links-1240-debt-service-and-the) · Wed, 30 Sep 2026 10:19:50 GMT · `chartbook-00` · 144字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Top Links 1238 Equity flows. Wages in gold. Path of the Kamikaze & Trotsky on the revolution of dollar hegemony. ](https://adamtooze.substack.com/p/top-links-1238-equity-flows-wages) · Mon, 28 Sep 2026 10:45:52 GMT · `chartbook-02` · 186字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Top Links 1237 Rates, rates rates. The yen-carry-trade unwind. The cartel war in Sinaloa & “socialism or barbarism” (1915).](https://adamtooze.substack.com/p/top-links-1237-rates-rates-rates) · Sun, 27 Sep 2026 10:45:22 GMT · `chartbook-03` · 288字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-wolfstreet-zh_macro"></a>
### Wolf Richter → zh_macro · SECONDARY

限定官方数据解读/劳动力和信贷；完整检查 labor-turnover 文能看到 quit/layoff/hire 分拆。

采样：`{"from": "2026-09-20T04:12:32+00:00", "to": "2026-09-29T19:07:42+00:00", "entries_seen": 10, "entries_saved": 10, "entries_with_at_least_1500_text_chars": 0, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：RSS 都是 teaser；本轮只补取两篇网页，其中一篇含长评论区须正文抽取。

- [Turnover in the Labor Market Calms Down, after Chaotic Churn](https://wolfstreet.com/2026/09/29/turnover-in-the-labor-market-calms-down-after-chaotic-churn/) · Tue, 29 Sep 2026 19:07:42 +0000 · `wolfstreet-00` · 89字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Biggest Borrowers & Lenders in the $13.5-Trillion Repo Market: How the Hedge Fund “Basis Trade” & Money Market Funds Fit In](https://wolfstreet.com/2026/09/28/biggest-borrowers-lenders-in-the-13-5-trillion-repo-market-how-the-hedge-fund-basis-trade-money-market-funds-fit-in/) · Mon, 28 Sep 2026 18:29:12 +0000 · `wolfstreet-02` · 48字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Long-Term Treasury Yields Rise to 5.5%, Mortgage Rates to 7.5%, as Bond Market Grapples with a Complex Reality](https://wolfstreet.com/2026/09/25/long-term-treasury-yields-rise-to-5-5-mortgage-rates-to-7-5-as-bond-market-grapples-with-a-complex-reality/) · Sat, 26 Sep 2026 00:35:25 +0000 · `wolfstreet-03` · 142字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-semianalysis-zh_industry"></a>
### SemiAnalysis → zh_industry · CORE

技术实现/benchmark/teardown 和项目级数据口径，是与宏观账号不同的核心信息。

采样：`{"from": "2026-09-10T14:28:20+00:00", "to": "2026-09-28T19:26:41+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 12, "ends_read_more": 12, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：三篇公开正文远超4k，但都不能声称拿到付费全文；图表、代码与条件不可只保留结论。

- [How GLM5.3 Sparse Attention Affects HBM Memory Usage](https://newsletter.semianalysis.com/p/sparse-savings-persistent-demand-inside-glm53) · Mon, 28 Sep 2026 19:26:41 GMT · `semianalysis-00` · 20775字符。稀疏注意力、HBM/host memory/SSD、训练和推理路径分开；链接代码/论文。
- [Intel Panther Lake Teardown](https://newsletter.semianalysis.com/p/intel-panther-lake-teardown) · Sat, 26 Sep 2026 13:36:32 GMT · `semianalysis-01` · 59894字符。工艺、背面供电、金属互联和封装的 teardown，链接专利和公司技术材料。
- [Everyone Says Datacenter Moratoriums Are Killing the US Buildout. We disagree ](https://newsletter.semianalysis.com/p/everyone-says-datacenter-moratoriums) · Tue, 15 Sep 2026 20:54:41 GMT · `semianalysis-06` · 24563字符。限制边界容量与实际延期容量分口径；项目细节部分在付费后。

<a id="source-fabricatedknowledge-zh_industry"></a>
### Fabricated Knowledge → zh_industry · SECONDARY

有机器人执行器成本、KV cache/offload 从业者访谈和 memory/optics 周期框架。

采样：`{"from": "2025-10-27T14:57:33+00:00", "to": "2026-08-13T15:49:24+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 7, "ends_read_more": 8, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：近期两篇 feed 只有 Read more；三个可读例子较旧，不能承诺及时覆盖。

- [IN-DEPTH: What Unitree's Evolution Means For Robotics](https://www.fabricatedknowledge.com/p/in-depth-what-unitrees-evolution) · Wed, 24 Jun 2026 20:28:30 GMT · `fabricatedknowledge-02` · 42899字符。Unitree 从四足机器人积累执行器规模，再进入 humanoid；含多说话人逐字稿。
- [Another Conversation with Val Bercovici Memory Markets](https://www.fabricatedknowledge.com/p/another-conversation-with-val-bercovici) · Mon, 16 Feb 2026 17:13:23 GMT · `fabricatedknowledge-05` · 25999字符。Doug与Val讨论KV cache和网络/存储取舍；不能合并成作者一个人的经历。
- [2026 AI & Semiconductor Outlook](https://www.fabricatedknowledge.com/p/2026-ai-and-semiconductor-outlook) · Wed, 07 Jan 2026 21:37:33 GMT · `fabricatedknowledge-07` · 14182字符。2026展望回顾 memory/optics 与汽车周期，预测末节不可见。

<a id="source-clausaasholm-zh_industry"></a>
### Claus Aasholm → zh_industry · SECONDARY

Samsung 组织与内部利润、Broadcom 收入结构、Nvidia 战略维度；补公司层面视角。

采样：`{"from": "2026-05-19T13:58:23+00:00", "to": "2026-09-24T10:53:26+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 9, "ends_read_more": 12, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：三篇均有 Read more 或后续未展开；Samsung 引子是作者个人经历，不能冒领。

- [The Brightest Star of the Constellation](https://clausaasholm.substack.com/p/the-brightest-star-of-the-constellation) · Wed, 23 Sep 2026 11:07:56 GMT · `clausaasholm-01` · 10180字符。Samsung叙述有从业经历、组织/转移定价、利润分配；后段未完。
- [The Comms Company Formerly Known as Broad](https://clausaasholm.substack.com/p/the-comms-company-formerly-known) · Thu, 10 Sep 2026 11:09:08 GMT · `clausaasholm-02` · 8892字符。Broadcom从communications转向compute的营收组合与资源配置取舍。
- [The 8 Dimensions of Nvidia’s Strategy](https://clausaasholm.substack.com/p/the-8-dimensions-of-nvidias-strategy) · Tue, 01 Sep 2026 11:33:54 GMT · `clausaasholm-03` · 15036字符。Nvidia八个维度只公开到首个维度附近；选段不能冒称八项已全审。

<a id="source-semiengineer-zh_industry"></a>
### The Semiconductor Engineer → zh_industry · RESEARCH_ONLY

作为论文/技术 primary discovery：制造工艺 monitor 有 DOI、imec 原文和明确限制。

采样：`{"from": "2026-08-19T12:32:25+00:00", "to": "2026-09-28T13:55:01+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 9, "ends_read_more": 7, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：可追溯 DOI 不等于每个概括已核实；关键结论回到论文。

- [Weekly Monitor on Semiconductor Process Research and Manufacturing](https://thesemiconductornewsletter.substack.com/p/weekly-monitor-on-semiconductor-process-aa3) · Sat, 26 Sep 2026 16:29:51 GMT · `semiengineer-01` · 10611字符。五篇研究：厚掩模、器件变异、原子刻蚀、Ta、Ge/Si APD，附论文链接。
- [Semiconductor Materials Roadmap 2027-2033](https://thesemiconductornewsletter.substack.com/p/semiconductor-materials-roadmap-2027) · Thu, 17 Sep 2026 17:06:28 GMT · `semiengineer-04` · 9854字符。材料roadmap区分硅、互联金属、High-NA、封装，并链接SEMI/imec/ASML。
- [Weekly Monitor on Semiconductor Process Research and Manufacturing](https://thesemiconductornewsletter.substack.com/p/weekly-monitor-on-semiconductor-process-6ec) · Sat, 19 Sep 2026 20:46:37 GMT · `semiengineer-03` · 14788字符。前一期周度研究monitor，证明不只一条偶然链接。

<a id="source-nextplatform-zh_industry"></a>
### The Next Platform → zh_industry · SECONDARY

补系统架构和计算经济性；两篇实读网页分别为 AMD 模型布局和量子纠错的 CPU 开销。

采样：`{"from": "2026-09-14T17:54:05+01:00", "to": "2026-09-29T15:24:25+01:00", "entries_seen": 83, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 0, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：feed 12 条正文为零；两篇网页可读，但 ingestion 不能只用 feed 标题。

- [AMD Buys World Labs For $8.2 Billion To Get AI Model Cred](https://www.nextplatform.com/ai/2026/09/29/amd-buys-world-labs-for-82-billion-to-get-ai-model-cred/5299801) · Tue, 29 Sep 2026 15:24:25 +0100 · `nextplatform-00` · 0字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [IonQ: There Is One CPU To Rule Error Correction Decoding](https://www.nextplatform.com/compute/2026/09/25/ionq-there-is-one-cpu-to-rule-error-correction-decoding/5299192) · Fri, 25 Sep 2026 14:23:50 +0100 · `nextplatform-01` · 0字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Vector Search Is Now A Data Type, But The Money Math Has Not Gone Away](https://www.nextplatform.com/store/2026/09/22/vector-search-is-now-a-data-type-but-the-money-math-has-not-gone-away/5298393) · Tue, 22 Sep 2026 18:06:09 +0100 · `nextplatform-03` · 0字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-servethehome-zh_industry"></a>
### ServeTheHome → zh_industry · SECONDARY

补服务器产品/平台边界，EPYC 分层文章区分 scale-up、scale-out、agentic CPU 类别。

采样：`{"from": "2026-09-24T23:17:57+00:00", "to": "2026-09-29T17:00:59+00:00", "entries_seen": 6, "entries_saved": 6, "entries_with_at_least_1500_text_chars": 0, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：feed 为短摘要；EPYC 网页结尾仍说接着做 mapping，需确认分页/图表依赖。

- [Where We Expect AMD EPYC 9006 CPUs in the era of Agentic AI](https://www.servethehome.com/where-we-expect-amd-epyc-9006-cpus-in-the-era-of-agentic-ai/) · Tue, 29 Sep 2026 17:00:59 +0000 · `servethehome-00` · 209字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [NVIDIA Open Agent Safety Platform Launched](https://www.servethehome.com/nvidia-open-agent-safety-platform-launched/) · Tue, 29 Sep 2026 03:00:04 +0000 · `servethehome-01` · 195字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [AMD Takes the Lid off of Next-Gen EPYC 9006 Venice As Zen 6 Comes to Servers](https://www.servethehome.com/amd-takes-the-lid-off-of-next-gen-epyc-9006-venice-as-zen-6-comes-to-servers/) · Fri, 25 Sep 2026 17:00:01 +0000 · `servethehome-04` · 314字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-stratechery-zh_industry"></a>
### Ben Thompson → zh_industry · SECONDARY

App→agent 的入口/分发机制以及前沿模型的商业壁垒，限定相关公司/行业机制主题。

采样：`{"from": "2026-09-17T10:00:00+00:00", "to": "2026-09-30T10:00:00+00:00", "entries_seen": 10, "entries_saved": 10, "entries_with_at_least_1500_text_chars": 4, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：两篇免费正文完整；付费 daily updates 只有摘要，不能自动扩写。

- [Apps, Agents, and Aggregation](https://stratechery.com/2026/apps-agents-and-aggregation/) · Mon, 28 Sep 2026 10:25:37 +0000 · `stratechery-02` · 17166字符。用iPhone/App历史及Meta/Microsoft分发讨论agent入口，正文有完整结尾。
- [Frontier Overhangs](https://stratechery.com/2026/frontier-overhangs/) · Mon, 21 Sep 2026 10:00:00 +0000 · `stratechery-07` · 21052字符。模型前沿、安全要求和商业壁垒的论证；不应挪成普通芯片新闻。
- [2026.39: Begun, the Aggregator Wars Have](https://stratechery.com/2026/begun-the-aggregator-wars-have/) · Fri, 25 Sep 2026 17:00:00 +0000 · `stratechery-03` · 3975字符。本周回顾，同作者上述文章链接，不应重复收成独立事件。

<a id="source-netinterest-zh_industry"></a>
### Marc Rubinstein → zh_industry · SECONDARY

用在金融服务/AI融资机制：agent 降低保险转换摩擦、GPU租金与融资结构。

采样：`{"from": "2026-07-03T16:38:39+00:00", "to": "2026-09-25T17:33:27+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 12, "ends_read_more": 12, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：本次三篇停在 read on/Read more；体验涉及作者汽车被盗/保费，身份敏感。

- [Agents Revolt](https://www.netinterest.co/p/the-agents-revolt) · Fri, 25 Sep 2026 17:33:27 GMT · `netinterest-00` · 2925字符。个人买保险体验与agent降低转换摩擦；有第三人推文，身份需分开。
- [Brookfield of Dreams](https://www.netinterest.co/p/brookfield-of-dreams) · Sat, 19 Sep 2026 15:05:47 GMT · `netinterest-01` · 3242字符。Brookfield公司案例的可见开头；后续论证未取得。
- [Financing the AI Boom 3](https://www.netinterest.co/p/financing-the-ai-boom-3) · Fri, 14 Aug 2026 16:46:59 GMT · `netinterest-06` · 3565字符。GPU租赁价格、耐久性和融资；链接Silicon Data和原播客。

<a id="source-rbnenergy-zh_industry"></a>
### RBN Energy → zh_industry · WATCHLIST

天然气管道、储气和 LNG 需求可能填 data center 能源供给空缺。

采样：`{"from": "2026-09-23T00:00:00-05:00", "to": "2026-09-30T00:00:00-05:00", "entries_seen": 30, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 0, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：两次文章检查一次遇 CAPTCHA；另一页有营销/页面噪音，正文需分离再审。

- [Comeback Story? – New Pipelines Boost Permian Natural Gas Economics, But Oil Still Drives Activity](https://rbnenergy.com/daily-posts/blog/new-pipelines-boost-permian-natural-gas-economics-oil-still-drives-activity) · Wed, 30 Sep 2026 00:00:00 -0500 · `rbnenergy-00` · 293字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Long Time – Economics, LNG Exporters’ Needs to Determine Which Gulf Coast Gas Storage Gets Built](https://rbnenergy.com/daily-posts/blog/economics-lng-exporters-needs-determine-which-gulf-coast-gas-storage-gets-built) · Tue, 29 Sep 2026 00:00:00 -0500 · `rbnenergy-01` · 307字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Leap of Faith – Potential Plans to Limit U.S. Diesel Exports Come With Plenty of Downside Risk](https://rbnenergy.com/daily-posts/blog/potential-plans-limit-us-diesel-exports-come-plenty-downside-risk) · Mon, 28 Sep 2026 00:00:00 -0500 · `rbnenergy-04` · 302字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-doomberg-zh_industry"></a>
### Doomberg → zh_industry · WATCHLIST

仅考察能源供给/基础设施；不把强政治修辞或新闻判断默认搬入 Industry。

采样：`{"from": "2026-08-23T09:01:54+00:00", "to": "2026-09-29T09:02:34+00:00", "entries_seen": 20, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 10, "ends_read_more": 12, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：最终的四种推演等核心部分在 paywall 后，不能仅凭导语作出稿源。

- [Going With the Flow](https://newsletter.doomberg.com/p/going-with-the-flow) · Tue, 29 Sep 2026 09:02:34 GMT · `doomberg-00` · 2884字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Escalation Clauses](https://newsletter.doomberg.com/p/escalation-clauses) · Tue, 22 Sep 2026 09:02:17 GMT · `doomberg-02` · 3574字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。
- [Value Trap](https://newsletter.doomberg.com/p/value-trap) · Wed, 16 Sep 2026 09:00:37 GMT · `doomberg-04` · 3681字符。具体页面/摘要如 snapshot 所示；此例不代表已验证全文。

<a id="source-damodaran-zh_industry"></a>
### Aswath Damodaran → zh_industry · SECONDARY

利率与股价、扩张与盈利的取舍、AI商业化问题；补估值机制，非芯片新闻替代品。

采样：`{"from": "2026-03-24T13:23:00.001-04:00", "to": "2026-09-10T12:37:37.212-04:00", "entries_seen": 25, "entries_saved": 12, "entries_with_at_least_1500_text_chars": 12, "ends_read_more": 0, "deep_evidence_examples": 3, "sampling": "latest up to 12 entries returned by publisher feed; no pagination"}`

限制：正文完整但很长，图表/嵌入 tweet/教学链接需按选段保留；Atom alternate URL 已纠正。

- [Interest Rates and Stock Prices: An Old Debate Flares up!](https://aswathdamodaran.blogspot.com/2026/09/interest-rates-and-stock-prices-old.html) · 2026-09-10T12:37:37.212-04:00 · `damodaran-00` · 20387字符。分解名义利率、信用spread、盈利与估值，链接原始数据工作簿。
- [The Scaling and Profitability Trade off: Venture Capital's Weakest Link!](https://aswathdamodaran.blogspot.com/2026/09/the-scaling-and-profitability-trade-off.html) · 2026-09-02T13:39:51.574-04:00 · `damodaran-01` · 38774字符。讨论VC优先扩张与企业盈利的冲突，引用论文与旧案例。
- [AI's Bar Mitzvah Moment: From Hype & Hope to Business Questions!](https://aswathdamodaran.blogspot.com/2026/08/ais-bar-mitzvah-moment-from-hype-hope.html) · 2026-08-20T17:18:56.328-04:00 · `damodaran-02` · 54266字符。AI从资本故事转到商业问题，保留公司差异和现金流框架。

<a id="source-bls-zh_macro"></a>
### BLS → zh_macro · EVENT_ONLY

Employment household/establishment distinction and CPI tables; fixed releases are primary facts.

采样：`{"sampling": "two selected official pages, not continuous release history", "entries_saved": 2}`

限制：Exact release tables/pages captured; data-series connectors not implemented by this audit.

- [Employment Situation Summary - 2026 M08 Results](https://www.bls.gov/news.release/empsit.nr0.htm) · see captured release; landing pages may change · `official-bls_employment` · 6902字符。Employment household/establishment distinction and CPI tables; fixed releases are primary facts.
- [Consumer Price Index Summary ](https://www.bls.gov/news.release/cpi.nr0.htm) · see captured release; landing pages may change · `official-bls_cpi` · 20112字符。Employment household/establishment distinction and CPI tables; fixed releases are primary facts.

<a id="source-bea-zh_macro"></a>
### BEA → zh_macro · EVENT_ONLY

GDP and PCE data landing pages provide release/data entry points, not an account-ready post.

采样：`{"sampling": "two selected official pages, not continuous release history", "entries_saved": 2}`

限制：Exact release tables/pages captured; data-series connectors not implemented by this audit.

- [Gross Domestic Product | U.S. Bureau of Economic Analysis (BEA)](https://www.bea.gov/data/gdp/gross-domestic-product) · see captured release; landing pages may change · `official-bea_gdp` · 12791字符。GDP and PCE data landing pages provide release/data entry points, not an account-ready post.
- [Personal Consumption Expenditures Price Index](https://www.bea.gov/data/personal-consumption-expenditures-price-index) · see captured release; landing pages may change · `official-bea_pce` · 5980字符。GDP and PCE data landing pages provide release/data entry points, not an account-ready post.

<a id="source-fed-zh_macro"></a>
### Federal Reserve → zh_macro · EVENT_ONLY

H.4.1 tables and dated FOMC statement serve policy/balance-sheet events or verification.

采样：`{"sampling": "two selected official pages, not continuous release history", "entries_saved": 2}`

限制：Exact release tables/pages captured; data-series connectors not implemented by this audit.

- [Federal Reserve Balance Sheet: Factors Affecting Reserve Balances - H.4.1](https://www.federalreserve.gov/releases/h41/) · see captured release; landing pages may change · `official-fed_h41` · 170500字符。H.4.1 tables and dated FOMC statement serve policy/balance-sheet events or verification.
- [Federal Reserve issues FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm) · see captured release; landing pages may change · `official-fomc_september` · 29662字符。H.4.1 tables and dated FOMC statement serve policy/balance-sheet events or verification.

<a id="source-treasury-zh_macro"></a>
### US Treasury → zh_macro · EVENT_ONLY

Refunding documents and Daily Treasury Statement define fiscal cash/issuance primary layer.

采样：`{"sampling": "two selected official pages, not continuous release history", "entries_saved": 2}`

限制：Exact release tables/pages captured; data-series connectors not implemented by this audit.

- [Treasury Quarterly Refunding](https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding) · see captured release; landing pages may change · `official-treasury_quarterly_refunding` · 38256字符。Refunding documents and Daily Treasury Statement define fiscal cash/issuance primary layer.
- [Daily Treasury Statement (DTS) | U.S. Treasury Fiscal Data](https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/) · see captured release; landing pages may change · `official-treasury_daily` · 19238字符。Refunding documents and Daily Treasury Statement define fiscal cash/issuance primary layer.

<a id="source-x_haohong_cfa-zh_macro"></a>
### 洪灝 → zh_macro · WATCHLIST

访谈入口待补原始 transcript；不能以中英双发重复计 source signal。

采样：`{"method": "bounded fixed-window search, Latest requested", "unique_posts": 22, "windows": 9, "published_years": {"2026": 22}, "reply_posts": 0, "quote_posts": 3, "posts_with_media": 12, "text_variant_disagreements": 13, "nonprefix_text_variant_conflicts": 6, "explicit_completeness_flags": 0, "cap_reached_windows": 2, "nonmonotonic_latest_windows": 4, "missing_author_ids": 0, "collection": "x_sampling_audit.json"}`

限制：Exact longest-visible body and all competing variants/author/quote/reply/media captured. No explicit body completeness flags. Capped windows are not a complete timeline; pending facts/context/human source review.

- [HAOHONG_CFA · 2096813507081818348](https://x.com/HAOHONG_CFA/status/2096813507081818348) · 2026-09-07T04:11:11+00:00 · `x-live-2096813507081818348` · 1230字符。银行注资、EPS稀释和弱贷款需求是具体机制，但资金数值/历史轮次/增长断言均需回到财政部和银行公告核验；HAOHONG订阅仍WATCHLIST。
- [HAOHONG_CFA · 2099726611864076593](https://x.com/HAOHONG_CFA/status/2099726611864076593) · 2026-09-15T05:06:49+00:00 · `x-live-2099726611864076593` · 643字符。零售/可支配收入/财富效应的明确推理和政策判断；有图，历史低点与4–5%需原数据核查。
- [HAOHONG_CFA · 2089546693574566269](https://x.com/HAOHONG_CFA/status/2089546693574566269) · 2026-08-18T02:55:28+00:00 · `x-live-2089546693574566269` · 989字符。贷款需求弱时常规降准降息的局限，主张直接刺激；开头订户指标预测成功属于作者自己，不能移植给账号。
- [HAOHONG_CFA · 2088047083345604694](https://x.com/HAOHONG_CFA/status/2088047083345604694) · 2026-08-13T23:36:33+00:00 · `x-live-2088047083345604694` · 348字符。Nate Silver图书和风险/不确定性方法；写推荐语是作者个人经历，图书宣传不是自动候选。
- [HAOHONG_CFA · 2104147972946817207](https://x.com/HAOHONG_CFA/status/2104147972946817207) · 2026-09-27T09:55:44+00:00 · `x-live-2104147972946817207` · 687字符。9月25日英文节目入口，正文是节目介绍；必须取得音频/逐字稿才有完整内容，不能扩写问题列表。
- [【与瑞士宝盛的月度对话（英文版）】US-China relations are back in ](https://x.com/HAOHONG_CFA/status/2104147972946817207) · 2026-09-27T09:55:44+00:00 · `local-ade2b10082ecad05` · 683字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。
- [【与瑞士宝盛的月度对话】中美关系再度成为市场焦点。投资者密切关注中美会谈能否取得实质性进展，并改](https://x.com/HAOHONG_CFA/status/2104142996740751835) · 2026-09-27T09:35:58+00:00 · `local-76e1406a989e3caa` · 247字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。
- [This mid-autumn festival, Hong Kong has all the ](https://x.com/HAOHONG_CFA/status/2103890164573773982) · 2026-09-26T16:51:18+00:00 · `local-107e27cee25560b3` · 155字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。

<a id="source-x_qinbafrank-zh_industry"></a>
### qinbafrank → zh_industry · SECONDARY

仅公司/行业帖进本账号；最新8条有CEX危机与宏观流动性，不能全部订阅成 Industry candidate。

采样：`{"method": "bounded fixed-window search, Latest requested", "unique_posts": 60, "windows": 9, "published_years": {"2026": 60}, "reply_posts": 25, "quote_posts": 39, "posts_with_media": 24, "text_variant_disagreements": 31, "nonprefix_text_variant_conflicts": 21, "explicit_completeness_flags": 0, "cap_reached_windows": 9, "nonmonotonic_latest_windows": 3, "missing_author_ids": 0, "collection": "x_sampling_audit.json"}`

限制：Exact longest-visible body and all competing variants/author/quote/reply/media captured. No explicit body completeness flags. Capped windows are not a complete timeline; pending facts/context/human source review.

- [qinbafrank · 2086443355815428175](https://x.com/qinbafrank/status/2086443355815428175) · 2026-08-09T13:23:54+00:00 · `x-live-2086443355815428175` · 285字符。13G客户代持与自营持股区分有用；10.5%/7.2%需原filing，图表没有独立读到；不是当前Macro订阅自动Industry广播。
- [qinbafrank · 2086281764356665611](https://x.com/qinbafrank/status/2086281764356665611) · 2026-08-09T02:41:48+00:00 · `x-live-2086281764356665611` · 2357字符。AAOI财报/800G/1.6T/CPO的具体工艺和产能顺序；正文长不代表财报事实已核验，quote还含Bitget赞助。
- [qinbafrank · 2093964796026859973](https://x.com/qinbafrank/status/2093964796026859973) · 2026-08-30T07:31:26+00:00 · `x-live-2093964796026859973` · 2141字符。明确总结fin大，nested quote保留9138字原文；应回到fi56622380原帖，区分原作者论证与qin的追加判断。
- [英伟达未来一年要回购超过4%的自家股票，英伟达官方刚刚宣布董事会批准将股票回购计划授权增加 15](https://x.com/qinbafrank/status/2104549140198027380) · 2026-09-28T12:29:50+00:00 · `local-6806c02cd6ed1334` · 186字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。
- [看到不少分析把当下长债收益率走高跟90年代相比，但是忽略这两个年代的差异。关键是不同点： 1、九](https://x.com/qinbafrank/status/2104458773582786629) · 2026-09-28T06:30:45+00:00 · `local-13c643543c4929c1` · 970字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。
- [对于大饼和加密，需要关注一些流动性的变化。银行准备金上上周3.03万亿，上周已经回落到2.96万](https://x.com/qinbafrank/status/2104419595348304256) · 2026-09-28T03:55:04+00:00 · `local-50bd6c0a5a8b9f35` · 297字符。现有本地导入，未重新获取帖/媒体/thread；qin 的英伟达与宏观帖必须按主题拆分，洪灝两条是同一访谈中英宣传，不算两份独立研究。

<a id="source-x_morris_lt-en_morris_archive"></a>
### Morris_LT → en_morris_archive · CORE

唯一主作者池；今天仍有价值的历史内容→英文翻译+轻编；不要求添加新观点。

采样：`{"method": "bounded fixed-window search, Latest requested", "unique_posts": 139, "windows": 13, "published_years": {"2024": 60, "2025": 59, "2026": 20}, "reply_posts": 11, "quote_posts": 1, "posts_with_media": 34, "text_variant_disagreements": 43, "nonprefix_text_variant_conflicts": 5, "explicit_completeness_flags": 0, "cap_reached_windows": 13, "nonmonotonic_latest_windows": 2, "missing_author_ids": 0, "collection": "x_sampling_audit.json"}`

限制：Exact longest-visible body and all competing variants/author/quote/reply/media captured. No explicit body completeness flags. Capped windows are not a complete timeline; pending facts/context/human source review. Exception: three June30 standalone bodies independently matched against public post pages; these three new source versions are pending_selection. This is extraction verification only, not factual/evergreen/human quality approval.

- [Morris_LT · 1749041977017110753](https://x.com/Morris_LT/status/1749041977017110753) · 2024-01-21T12:11:17+00:00 · `x-live-1749041977017110753` · 810字符。2024-01，互联网/规制/技术竞争框架保留具体配对例子；并非自动等于今天仍成立，部分是当时诉讼/监管格局。
- [Morris_LT · 1782182031688131014](https://x.com/Morris_LT/status/1782182031688131014) · 2024-04-21T22:58:02+00:00 · `x-live-1782182031688131014` · 63字符。2024-04矿工奖励与Runes热度的即时状态；缺图，不能直接作为今天的evergreen。
- [Morris_LT · 1815164369556439128](https://x.com/Morris_LT/status/1815164369556439128) · 2024-07-21T23:18:04+00:00 · `x-live-1815164369556439128` · 106字符。2024-07马斯克更换头像的即时平台事件；不是值得长期搬运的分析框架。
- [Morris_LT · 1848505776887022071](https://x.com/Morris_LT/status/1848505776887022071) · 2024-10-21T23:24:55+00:00 · `x-live-1848505776887022071` · 322字符。2024-10，借沛县/凤阳等历史例子谈人才与机会；有观点与例子，但历史事实和观点力度需审，图片作用未判。
- [Morris_LT · 1881846818872672576](https://x.com/Morris_LT/status/1881846818872672576) · 2025-01-21T23:30:19+00:00 · `x-live-1881846818872672576` · 117字符。2025-01，交易回报和自愿付出区别；可读短观点，是否足够有价值/符合账号选题待人审。
- [Morris_LT · 1914134860379422891](https://x.com/Morris_LT/status/1914134860379422891) · 2025-04-21T01:51:28+00:00 · `x-live-1914134860379422891` · 53字符。2025-04拥有自己世界再分享的短观点；今天属于原帖时点，不应机械改成账号经历；非高价值自动结论。
- [Morris_LT · 1947137238795760017](https://x.com/Morris_LT/status/1947137238795760017) · 2025-07-21T03:31:08+00:00 · `x-live-1947137238795760017` · 241字符。2025-07，竞争指向品质还是负和价格战；保留原文判断及对比，但中日广泛概括不能当作已验证事实。
- [Morris_LT · 1980453852613841071](https://x.com/Morris_LT/status/1980453852613841071) · 2025-10-21T01:59:28+00:00 · `x-live-1980453852613841071` · 37字符。2025-10 DOGE/X CEO图文；短时平台梗和缺图，不是evergreen主稿。
- [Morris_LT · 2071809306375389231](https://x.com/Morris_LT/status/2071809306375389231) · 2026-06-30T04:13:25+00:00 · `x-live-2071809306375389231` · 65字符。线性/幂律/真实世界下方向与努力的区分；文字独立，有明确条件，不要压成单一励志判断。
- [Morris_LT · 2071805649974141165](https://x.com/Morris_LT/status/2071805649974141165) · 2026-06-30T03:58:53+00:00 · `x-live-2071805649974141165` · 201字符。交易训练概率、风险、规则、复利、修正，并迁移到投资创业职业决策；保留完整推进与不保证不亏钱的限定。
- [Morris_LT · 2071789599572308031](https://x.com/Morris_LT/status/2071789599572308031) · 2026-06-30T02:55:07+00:00 · `x-live-2071789599572308031` · 271字符。幂律领域的失败率与大回报关系；保留领域限定、坏主意/竞争消耗例子和抓住少数成功的结尾。
- [Morris_LT · 1807307502431691196](https://x.com/Morris_LT/status/1807307502431691196) · 2024-06-30T06:57:41+00:00 · `x-live-1807307502431691196` · 53字符。暴富五年后的家和装修成本属于Morris个人经历；不改成账号亲历，且本条缺图片内容。
- [Morris_LT · 1873881582819565939](https://x.com/Morris_LT/status/1873881582819565939) · 2024-12-30T23:59:19+00:00 · `x-live-1873881582819565939` · 95字符。疾病可治比例等医疗断言；无原始证据且不适合当前金融/商业framework账号。
- [很多人都知道，要坚持做正确的事情。但真正的问题是：一开始，你根本不知道什么才是正确的事情](https://x.com/i/status/2104013330457452688) · 2026-09-27T01:00:43+00:00 · `morris-2104013330457452688` · 125字符。Current framework candidate; manual evergreen review still required.
- [AI 浪潮的三个阶段：
第一阶段，资本：能源、芯片、算力、数据中心，解决 “AI 能不能](https://x.com/i/status/2105105425037439231) · 2026-09-30T01:20:18+00:00 · `morris-2105105425037439231` · 181字符。Current framework candidate; manual evergreen review still required.
- [订阅会员问我：旧秩序切换到新秩序，最大的危害是什么？如果你曾经是某家公司的副总裁、某个集](https://x.com/i/status/2105134067033469051) · 2026-09-30T03:14:07+00:00 · `morris-2105134067033469051` · 291字符。Current framework candidate; manual evergreen review still required.
- [冯唐说：只有穷人，才会痴迷技术。只有笨人，才会想着先把事做好。越是底层的人，处理人际关系](https://x.com/i/status/1834095860726333889) · 2024-09-12T05:05:03+00:00 · `morris-1834095860726333889` · 207字符。Third-party speech: 冯唐/宋教授. Posting account is not necessarily speaker; media context required.
- [宋教授说中国下半场的生意经， 任何生意越做利润越趋近于零，文化的核心是价值。 https](https://x.com/i/status/1850700591334625553) · 2024-10-28T00:46:19+00:00 · `morris-1850700591334625553` · 62字符。Third-party speech: 冯唐/宋教授. Posting account is not necessarily speaker; media context required.

<a id="source-x_dylan522p-zh_industry"></a>
### Dylan Patel / @dylan522p → zh_industry · SECONDARY

具体产业线索有价值，但56条所见样本含34条reply、设备/雇佣/客户身份与轻闲聊；按topic找原报告和工程证据，不能整条时间线全收。

采样：`{"method": "bounded fixed-window search, Latest requested", "unique_posts": 56, "windows": 9, "published_years": {"2026": 56}, "reply_posts": 34, "quote_posts": 5, "posts_with_media": 8, "text_variant_disagreements": 3, "nonprefix_text_variant_conflicts": 3, "explicit_completeness_flags": 0, "cap_reached_windows": 9, "nonmonotonic_latest_windows": 6, "missing_author_ids": 0, "collection": "x_sampling_audit.json"}`

限制：Exact longest-visible body and all competing variants/author/quote/reply/media captured. No explicit body completeness flags. Capped windows are not a complete timeline; pending facts/context/human source review.

- [dylan522p · 2089143804695916646](https://x.com/dylan522p/status/2089143804695916646) · 2026-08-17T00:14:32+00:00 · `x-live-2089143804695916646` · 187字符。PJM建模、容量拍卖和$12B机制评论，实际quote到SemiAnalysis原分析；应按原文章去重和补证，不把推广短评当独立证据。
- [dylan522p · 2085191620048326947](https://x.com/dylan522p/status/2085191620048326947) · 2026-08-06T02:29:57+00:00 · `x-live-2085191620048326947` · 129字符。Micron/SK Hynix估值差与治理判断清晰但只有两句，未给证据；不能擅自展开为完整因果分析。
- [dylan522p · 2102208035225760191](https://x.com/dylan522p/status/2102208035225760191) · 2026-09-22T01:27:07+00:00 · `x-live-2102208035225760191` · 208字符。真实封装、DRAM和Hitachi XTEM是实物研究线索；作者团队设备/工作身份不得转给账号，图片尚未看。
- [dylan522p · 2088653662780547546](https://x.com/dylan522p/status/2088653662780547546) · 2026-08-15T15:46:53+00:00 · `x-live-2088653662780547546` · 1100字符。HBM速度要求变化、Micron重返与Broadcom/AMD不同事项；依赖争论父帖与客户报告，不能移植our revenue/clients。
- [dylan522p · 2101350877932212621](https://x.com/dylan522p/status/2101350877932212621) · 2026-09-19T16:41:05+00:00 · `x-live-2101350877932212621` · 553字符。军事芯片跨市场报价与严重指控；截图和价格口径未核验，不能把强烈断言当已证实渠道调查。

<a id="source-x_qinbafrank-zh_macro"></a>
### qinbafrank / Macro scoped → zh_macro · SECONDARY

只取政策/流动性/资本流机制；公司财报和加密交易所宣传不自动入Macro。订阅已有，source质量仍待人审。

采样：`{"method": "bounded fixed-window search, Latest requested", "unique_posts": 60, "windows": 9, "published_years": {"2026": 60}, "reply_posts": 25, "quote_posts": 39, "posts_with_media": 24, "text_variant_disagreements": 31, "nonprefix_text_variant_conflicts": 21, "explicit_completeness_flags": 0, "cap_reached_windows": 9, "nonmonotonic_latest_windows": 3, "missing_author_ids": 0, "collection": "x_sampling_audit.json"}`

限制：Exact longest-visible body and all competing variants/author/quote/reply/media captured. No explicit body completeness flags. Capped windows are not a complete timeline; pending facts/context/human source review.

- [qinbafrank · 2096589128213389501](https://x.com/qinbafrank/status/2096589128213389501) · 2026-09-06T13:19:35+00:00 · `x-live-2096589128213389501` · 1162字符。财政部两轮注资的机制与政策猜想；保留事实/作者推测边界，不能把是否有配套政策的问题改成已发生结论。
- [qinbafrank · 2103726759934144989](https://x.com/qinbafrank/status/2103726759934144989) · 2026-09-26T06:01:59+00:00 · `x-live-2103726759934144989` · 1337字符。对Ackman利率/AI论点的赞同与反驳均有用；保留Ackman问句、作者不同意见和短期需求/长期生产率的时差。
- [qinbafrank · 2089000142427091042](https://x.com/qinbafrank/status/2089000142427091042) · 2026-08-16T14:43:40+00:00 · `x-live-2089000142427091042` · 2238字符。美元流动性与币价路径，包含当时数字/图形形态；应按历史dated材料审，不把8月预测当今晚信号。
- [qinbafrank · 2103282960682344479](https://x.com/qinbafrank/status/2103282960682344479) · 2026-09-25T00:38:29+00:00 · `x-live-2103282960682344479` · 458字符。交易所被盗与补偿宣传不是当前Macro政策/flow候选；引用Bitget关联账号，不能因出现美元金额而入选。

