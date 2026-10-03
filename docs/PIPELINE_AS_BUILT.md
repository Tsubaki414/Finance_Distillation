# 当前 pipeline 实际是怎么跑的

写给第一次接触这个项目的人。**描述的是已经跑通的东西，不是规划。**
没做的部分单列在最后一节，不混在流程图里。

## 先说一件容易误会的事

**这里没有模型蒸馏。没有训练，没有 LoRA，没有 SFT，没有权重更新。**

项目名字里有 Distillation，日常也叫"蒸馏"，但实际做的是：
从 62 位 KOL 的 3,925 条真实帖子里**统计**出可观察的特征，把这些特征连同真实样本
写进提示词，让一个冻结的商用模型去写，再用一串闸门检查它写出来的东西。

训练路线试过并且记录在案（`ml/train_sentence_lora.py`）：本机 16GB 内存 + MLX 4bit
量化模型，torch 加载失败、MLX GPU 反向传播失败、CPU 95 小时，最终判定不可行并停止。
**对外描述应当是 `Corpus Import + Rule Filtering + News Ingest + evidence-loop experiments`，
不是 distillation pipeline，也不是 ML persona。**

---

## 一、输入层：四类来源

| 来源 | 模块 | 量 | 说明 |
|---|---|---|---|
| X 账号轮询 | `live/collect.py` | 5,206 帖 | 12 个观察账号，append-only，每次轮询存一份互动快照供算加速度 |
| 新闻 RSS | `live/news.py` | 292 条 | 10 个源，中英 + crypto。**关键词搜索在 X 上返回 404**，所以发现只能按账号 |
| X 关键词搜索 | `live/xsearch.py` | 按需 | 走 Apify，$0.0004/条。这是唯一能看到名单之外的通路 |
| 财报日历 | `live/calendar_events.py` | 110 场 | Nasdaq 免费接口，带 `pre_market`/`after_hours` 标记 |

**每个新闻源声明 `max_age_hours`，每次运行比对最新条目的年龄，过期报"失败"而不是"空"。**
这条不是洁癖：WSJ 的 RSS 返回 HTTP 200、XML 解析正常、最新条目停在 2025-01-27。
只看状态码会把它当成可用源，而它每次都报"0 条新增"。同类还有两个：
律动 BlockBeats 的官方端点全部返回 `{"status":0,"data":[]}`；Blockworks 的 feed 没有任何带日期的条目。

## 二、语料加工

```
原始帖 → clean.py（去推广/导流，保留裸链接）→ 62 位 donor 的语料
```

裸链接故意保留：第一版会因此丢掉 439 条帖子，包括「回家 https://t.co/...」这种
——不加空格的 t.co 本身就是真人痕迹。

在此之上算四类画像，每一项都带样本量、计算方法和支持的 post ID：

- **Style**（`live/style.py`）：句长变异、数字密度、片段率等，给出 donor 自己的百分位区间
- **Habit**（`live/habit.py`）：发帖节奏、活跃/沉默天数
- **Positions**（`live/positions.py`）：立场与预测台账
- **Terms**（`live/terms.py`）：用词

## 三、事件层

```
新闻 → 向量去重 → 聚类成事件 → 机会评分 → 分配给账号
```

**去重与聚类（`live/cluster.py`）的设计值得单独说，因为它推翻了最直觉的做法。**

最直觉的做法是设一个余弦相似度阈值。292 条实测把它否了——相似度最高的三对
全都不是重复：

```
0.988  BTC跌破84000，跌 0.00%   vs  同上，跌 2.82%       两个时点
0.961  8-K INDEPENDENCE REALTY  vs  8-K/A 同一家          修正案是另一份
0.905  8-K Enhanced Group       vs  8-K FIVE BELOW        不同公司，模板相同
```

而真重复分布更低（0.72–0.88），全是跨语言对。真重复 0.72–0.99、假阳性 0.80–0.96，
**区间完全重叠，任何单一阈值都分不开**。

所以相似度降级为"便宜地提候选"（36,585 对 → 270 对，135 倍），**由模型做裁决**。
规则版与模型版在同样 60 对上比过：分歧 19 处，规则 0 对。规则保留为 API
不可用时的兜底，并在输出里标明降级。

向量化在本机跑（`.runtime/models/embedding`，多语言 384 维），292 条 5.4 秒，零调用成本。

评分在 `live/hotspots.py` + `live/opportunities.py`：速度、扩散度、新颖度、
跨语言差，全部对各自基线归一化，所以大号不会仅因为大而排前。
每个实体对每个账号单独打分，允许"今天不发"。

## 四、事实层

```
事件 → resolve_event.py 找一手文件 → label_facts.py 命名指标 → render_slots.py 渲染数字
```

- 一手来源有排序，低于 2.0（发行人/通讯社/监管机构）的包不写
- 每个数字由代码从原文渲染成 slot，带 `fact_id`、原文引用、字符跨度
- **正文里每一个数字必须匹配某个 slot 的值与单位**，由 `live/write.audit` 逐个核对

这条是全链路里唯一不交给模型判断的：它是核对不是判断，确定性检查在这里更强，
因为它不能被说服。

## 四·五、Persona：定义了 3 个，在用 2 个，角色分离大半是名义上的

定义在 `evidence_loop/experiments/roles_v2.json`。每个 persona 把**五个角色分别指派给
不同 donor**，每项带指标值、样本量、领先第二名多少、支持的 post ID 和入选理由。
这一层是产品规范里「2–4 位互补 donor 分别加权」那条要求的实现。

| persona | knowledge | reasoning | language | habit | visual |
|---|---|---|---|---|---|
| **macro** 宏观数据与资金流观察者 | qinbafrank (n=308) | phyrexni (n=350) | phyrexni | aleabitoreddit (n=401) | 未指派 |
| **industry** 个股与产业链研究者 | xingpt (n=147) | phyrexni (n=350) | phyrexni | aleabitoreddit (n=401) | 未指派 |
| **trading** 交易系统与市场心理教练 | phyrexni (n=350) | phyrexni | phyrexni | aleabitoreddit | 未指派 |

每个 persona 还带一个「本人设要回答什么问题」：

- macro：工资、参与率、行业广度与历史修订是否共同说明宏观状态切换？如何区分数据和政策推断？
- industry：就业行业构成对需求与成本意味着什么？哪些推导尚缺公司财报或电话会证据？
- trading：什么新增证据足以改变交易决策？怎样等待确认、控制仓位，并预先定义判断失效？

### 三件必须说清楚的事

**一、五个角色里有四个在三个 persona 之间完全相同。**
reasoning、language 全是 phyrexni，habit 全是 aleabitoreddit，visual 全部未指派。
真正有差异的只有 knowledge 一项。

文件自己带了这条警告：

> `distinctness.note`: *If every persona resolves to the same donor set, multi-donor is a label.
> This number must be greater than one before an ablation is meaningful.*

`unique_donor_sets: 3` 技术上成立，但**当前状态离"multi-donor 只是个标签"只差一步**。
准确的描述是：**共用一套语言与推理，换一个知识来源。**
对外不应称为已实现的 multi-donor system。

**二、`trading` 有完整定义、有证据、有 donor 指派，但没有任何账号绑定它。**
四个账号是 macro×2（中英）+ industry×2（中英）。
**第三个人设从来没有写过一篇稿。**

**三、visual 三个都未指派，所以配图整条没有在跑。**
`roles_v2.json` 的 `limits` 里写了原因：
*Visual roles stay unassigned until image evidence passes a sample rule.*

### 选法本身的局限（文件自述）

```
Selection is evidence-ranked, not learned optimal.
Knowledge incidence is keyword based and is not proof of expertise.
```

knowledge 的排名是**关键词命中率**的收缩估计，不是专业度的证明。
margin 也很薄：industry 的 xingpt 只领先第二名 aleabitoreddit **0.0083**。

## 五、写作层

```
人设 + 风格目标 + 真实样本 + 事实 slot + KOL 观点  →  冻结模型  →  正文
```

当前写手是 **`relay2/gpt-5.5`**（中转站），温度 `0.25 + 0.12×尝试次数`，最多 7 次。
每次不过闸就带着**具体的失败原因**重写，不是盲目重试。

提示词里有四块：

1. **人设与内容线**：四个账号（中英 × 宏观/产业），各自独立成稿，**禁止先写母稿再翻译**
2. **风格**：不是描述而是**续写框架**——给 5 段该作者最近写的东西，要求"按他平时的写法接着写下一段"。
   公开研究里续写式 few-shot 的风格一致度是抽象描述的十几倍，实测也如此
3. **事实 slot 表**：数字、单位、量级必须一致，但句子怎么写由模型决定
4. **KOL 观点**（`live/opinions.py`，今天才接上）：按标的筛出最近真实原帖，
   每侧每作者最多 2 条，**中文源只能推理不能搬措辞，英文源可搬信息不可搬句子**

## 六、闸门层

正文写完后逐个检查，任何一项 blocking 即打回重写：

| 闸门 | 查什么 | 判定方式 |
|---|---|---|
| `write.audit` | 每个数字的值+单位是否在 slot 表上 | **确定性，永远不交给模型** |
| `qa/gates.py` | 事实/观点/推断分离、失效条件、逐句可回溯 | 规则 |
| `content/originality.py` | 是否搬运。同语言禁止，跨语言允许 | 规则（最长公共子串） |
| `content/leak_check.py` | 提示词词汇有没有漏进正文 | 规则 |
| `content/tells.py` | 机器味词表、数字密度上限 | 规则 |
| `content/reader_spec_llm.py` | 读者列的六类不喜欢的表达 | **规则 + 模型并集** |
| `live/opinions.overclaim_check` | 把 12 个账号写成"英文社区" | 规则 |

最后一条的由来：稿子写过「英文社区最早把出货连到 NVDA，比中文侧早 134.3 小时」。
那个数字是 12 个 handle 之间两个采集时间戳的差。**把采集样本的性质当成世界的性质。**

`reader_spec` 用规则+模型并集，是因为测过：22 篇稿上，模型抓到 13 处规则漏掉的
（包括现造术语「数据层/政策层」），规则抓到 2 处模型漏掉的。**互不包含，所以取并集。**

## 七、留痕

每篇稿的 JSON 里有 37 个字段，关键的几个：

```
sentence_to_source_ledger   每一句 → 它用了哪些 slot → 对应哪些 fact_id
slots                       每个数字的原文引用与字符跨度
opinions_shown              写作时看到了谁的哪几条帖子（post_id 可查）
attempts                    全部 7 次尝试，各自的失败原因与评分
writer_model / 温度 / seed   
crosslang_evidence_withheld 算了但故意不给写手看的内部计数
quality.does_not_mean       明确写出"过闸不代表读起来像人写的"
```

## 八、验收：这是全项目最难看的一块

**唯一有效的验收是人工盲测**（`ml/human_review.py`）。模型自评、规则银标、
HTTP 200、文件数量都不算验收——这条是项目规范明写的。

三轮结果：

| 轮次 | 机器稿 | 检出率 | 备注 |
|---|---|---|---|
| 1 | 6 | 1.0 | groundedness 5.00/5，**naturalness 0.17/5**，六篇全标"重写" |
| 2 | — | 1.0 | 22 次调用失败，18 次"成功"全是缓存命中，本轮作废 |
| 3 | 8 | 1.0 | 误判 0 |

**第三轮还有一个比检出率更扎人的结果：** 读者对 4 条**真人帖**答"不确定"，
对 8 条机器稿一次犹豫都没有。机器稿的机器味，比真人帖的真人味还明显。

**并且第三轮测的不是当前 pipeline。** 那 8 篇写于 13:20 之前，而观点接入在之后。
接了观点的稿子当时只有 2 篇，一篇都没进包。第四轮已经建好：同一批事实包各生成
两版（看得到观点/看不到观点），4:4 混进 8 条真人帖，答案键记录组别，等人填。

## 八·五、Skill 的实际使用情况

项目本地 `.agents/skills/` 装了 6 个，锁定清单在 `skill-audit/skills.lock.json`。
**截至本文，日常流程没有任何一个通过 Skill 机制被调用。**

| skill | 状态 | 说明 |
|---|---|---|
| `financial-persona-distillation` | **只作文档引用** | 它的 evaluation contract 被引进代码注释，例如「AI-pattern flags 不构成机器写作的证据」这条直接约束了 `content/tells.py` 的上报口径。但没有作为可执行 skill 调用 |
| `x-twitter-scraper`（Xquik）| 未用 | 没有配置可用凭证与成本估计。X 关键词搜索走 Apify |
| `yfinance-data` | 未用 | 行情与财报走 Nasdaq 日历 + Finnhub |
| `earnings-recap` | 未用 | 同上 |
| `estimate-analysis` | 未用 | 同上 |
| `huggingface-trackio` | 未用 | 它是给训练打点的，而这里没有训练在跑 |

采集、去重聚类、X 搜索、观点接入、闸门全部是直接实现的代码。

**一个待决的重复：** `yfinance-data` / `earnings-recap` / `estimate-analysis`
都是基于 Yahoo Finance，与刚接通的 Finnhub 功能重叠；而项目规范写明
**Yahoo 只能补充，不能替代 IR、SEC、电话会原文**。这三个是否保留值得讨论。

## 九、没做的部分

- **没有定时器。** 每次采集都是手敲命令。crontab 空
- **事件还没接进 `opportunities.py`** —— 采到的新闻还没变成写作任务
- **视频转写是断的。** `evidence_loop/` 里那条链跑通过（yt-dlp 公开发现、
  真人字幕优先、带时间戳 cue、说话人分离模型在位、3 份完整转写），但和 live 链路没连
- **同语言去重靠模型才抓得到。** 规则版找到 0 条并报告"可能这批确实没有"，
  模型版找到 27 组——是规则漏了
- **`originality` 还是纯正则**，大概率和 `reader_spec` 一样漏
- **第三个人设 `trading` 从未产出过稿件**，虽然它的 donor 指派与证据是完整的
- **视觉角色三个 persona 全未指派**，配图整条没有在跑
- **没有自动发帖、账号运营、互动、增长**，也不打算有。产品到人工审核与内容交接为止

## 成本

| 项 | 单价 | 说明 |
|---|---|---|
| 写作 | ~$0.15/篇 | relay2/gpt-5.5，$5/$30 每百万 token |
| 去重裁决 | ~$0.55 / 270 对 | |
| 文风闸门 | ~$0.002/篇 | claude-sonnet-5，**故意与写手不同家族** |
| 向量化 | $0 | 本机 CPU |
| X 搜索 | $0.0004/条 | Apify |

硬上限在 `ml/budget.py`，**发请求之前**估算，超了直接拒绝而不是事后发现。
上限当前 $50，已用约 $4.4。

---

# 附录：数据来源明细

## A. 语料里到底有谁

62 位 donor，3,925 条帖子。**但分布极不均匀，这一点比总数重要得多。**

### 中文侧：5 个人撑起全部 1,376 条

| handle | 中文帖 | beat |
|---|---|---|
| phyrexni | 470 | crypto / 宏观 |
| qinbafrank | 412 | 宏观与资金流 |
| michael_qqq2025 | 281 | 个股交易 |
| xingpt | 122 | 半导体供应链 |
| kovainvest | 83 | 个股 |
| aleabitoreddit | 8 | 市场心理（其余 520 条是英文）|

**中文频道完全建立在这 5 个人之上。** 其中 michael_qqq2025 的帖子里有相当比例是
在报自己的仓位与收益率，作为「知识/推理」来源价值有限——`live/opinions.py` 里
每侧每作者最多取 2 条的限制就是为此加的：按时间排序会让中文侧 5 条全是他一个人。

### 英文侧：57 个人，但是一条长尾

| handle | 帖数 |
|---|---|
| aleabitoreddit | 520 |
| beth_kindig | 142 |
| globalmktobserv | 104 |
| RaoulGMI | 66 |
| JimMarous / EricBalchunas | 59 |
| JeffSnider_EDU / Convertbond | 58 |
| tradexwhisperer | 52 |
| garyblack00 / citrini | 50 / 51 |
| …… 中段 30 余人，各 20–50 条 …… | |
| charliebilello | 10 |
| LynAldenContact | 8 |
| jam_croissant | 2 |
| Ritholtz | 1 |

**20 位 donor 的样本量 ≤22 条。** 在这个量级上算不出可信的风格区间——
`live/style.py` 会把样本不足的 donor 标为 `usable: false`，但这意味着
英文账号能真正学到的人远少于 57。

这正是"英文账号读起来碎片化"的数据成因：
中文侧是少数人的深度，英文侧是多数人的浅层。

### 两个集合不要搞混

| | 数量 | 作用 |
|---|---|---|
| **轮询名单** | 12 个账号 | 每次 `collect.py` 去网络拉新帖，5,206 条 |
| **语料 donor** | 62 位 | 用于学风格/习惯/立场，3,925 条 |
| `learning_accounts` | 50 个 | 只进语料，**不轮询**，所以内容是静态的 |

轮询的 12 个：

```
中文  phyrexni(crypto_macro)  qinbafrank(macro_flows)  aleabitoreddit(market_psychology)
      michael_qqq2025(equities)  kovainvest(equities)  xingpt(semis_supply_chain)
英文  beth_kindig(tech_equities)  globalmktobserv(macro)  citrini(thematic)
      ericjackson(tech_equities)  rjccapital(equities)  tradexwhisperer(trading)
```

**只有这 12 个人的观点是"现在"的。** 另外 50 位的语料停在导入那一刻，
学风格可以，"他现在怎么看"不行。

## B. 新闻源清单

全部免费、无需 key（SEC 除外，需真实联系 User-Agent，已获用户授权用其邮箱）。
`max_age_hours` 是各源自己的过期阈值，超过即报失败而非"今天没新闻"。

| 源 | 语言 | 首采 | 过期阈值 | URL |
|---|---|---|---|---|
| cn_investing | 中 | 20 | 6h | `cn.investing.com/rss/news.rss` |
| cn_investing_stocks | 中 | 10 | 12h | `cn.investing.com/rss/news_285.rss` |
| panews | 中 | 100 | 6h | `panewslab.com/rss.xml?lang=zh&type=NEWS` |
| investing | 英 | 18 | 6h | `investing.com/rss/news.rss` |
| seekingalpha | 英 | 9 | 12h | `seekingalpha.com/market_currents.xml` |
| cointelegraph | 英 | 30 | 6h | `cointelegraph.com/rss` |
| coindesk | 英 | 25 | 12h | `coindesk.com/arc/outboundfeeds/rss` |
| theblock | 英 | 20 | 24h | `theblock.co/rss.xml` |
| fed_press | 英 | 20 | 168h | `federalreserve.gov/feeds/press_all.xml` |
| sec_8k | 英 | 40 | 24h | EDGAR `getcurrent&type=8-K` Atom |

Fed 给 168 小时（一周）是因为央行本来就可以几天不说话，
那不是源故障；crypto 快讯给 6 小时，超过就是真的断了。

### 测过但不能用的

| 源 | 状态 |
|---|---|
| WSJ Markets RSS | **HTTP 200，最新条目 2025-01-27** — 死了一年零八个月 |
| 律动 BlockBeats | 官方文档的 v1/v2 端点**全部返回 `{"status":0,"data":[]}`** |
| Blockworks | feed 有响应但无任何带日期条目（2026-03 关停新闻部门）|
| CNBC | 403 |
| Yahoo Finance | 429 限流 |
| Reuters | 401 |
| 界面新闻 | 404 |
| 财联社电报 | 200 但内容不在静态 HTML 里 |
| RSSHub 华尔街见闻 | 403（公共实例被限）|
| X 关键词搜索（twitter CLI）| 404，**2026-09-24 复测仍然如此** |

前三个是这套 `max_age_hours` 机制存在的理由：它们都会返回 200。

## C. 一手文件源（写稿必须落到这一层）

```
bls_empsit   bls.gov/news.release/empsit.nr0.htm   就业报告
bls_cpi      bls.gov/news.release/cpi.nr0.htm      CPI
bls_ppi      bls.gov/news.release/ppi.nr0.htm      PPI
fed_press    federalreserve.gov/newsevents/...     Fed 新闻稿
```

BLS 对匿名 User-Agent 返回 403，所以走 jina reader 代理取同一个公开页面，
不把任何人的身份放进 header。

来源排序低于 2.0（发行人 / 通讯社 / 监管机构）的事实包**不写稿**。

## D. 其他通路

| 通路 | 状态 | 成本 |
|---|---|---|
| Apify X 关键词搜索 | 可用，中英文都能搜 | $0.0004/条，月额度 $500 剩 ~$445 |
| Nasdaq 财报日历 | 可用，110 场/14 天 | 免费，但是未公开接口 |
| Finnhub | **key 已到位，quote / earnings / company-news 三个端点实测通** | 免费档 60 次/分 |
| SEC EDGAR | 已启用 | 免费 |
| 视频（yt-dlp）| 链路跑通，3 份完整转写，**未接 live** | 免费 |
