# 时效性尽调：从「不知道发生了什么」到「盘前 AMD」

测试日期 **2026-09-24**。所有状态均为当日实测，不是读文档得出的结论。
源的可用性会变（下面就有一个返回 200 但内容停在 2025 年的例子），
复核时重跑本文末尾的命令，不要沿用这张表。

## 一、为什么现在做不到

| 环节 | 状态 |
|---|---|
| 定时触发 | 无。`crontab -l` 空，`~/Library/LaunchAgents/` 无相关项 |
| 新闻源 | 无。只有 12 个 X 账号轮询 + 4 个发布页（BLS 就业/CPI/PPI、Fed 新闻稿）|
| 财报日历 | 无 |
| 盘前行情 / 异动 | 无 |
| 推送 | 无 |

结论不是「做得慢」，是**系统不知道事件发生了**。它只能等某个被关注的账号
发帖谈起它，而且要等人手动跑一次 `live/collect.py`。

## 二、源的实测结果

### 可用，免费，无需 key，无需身份

| 源 | 语言 | 最新条目 | 用途 |
|---|---|---|---|
| `https://www.investing.com/rss/news.rss` | EN | 2026-09-24 05:49 | 通用财经快讯 |
| `https://cn.investing.com/rss/news.rss` | **中文** | 2026-09-24 05:48 | 中文频道的主力候选 |
| `https://cn.investing.com/rss/news_285.rss` | 中文 | 2026-09-24 02:51 | 股票新闻分类 |
| `https://seekingalpha.com/market_currents.xml` | EN | 2026-09-24 01:51 | 美股盘中快讯 |
| `https://www.federalreserve.gov/feeds/press_all.xml` | EN | 200 | 已在 sources.json |
| `https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD` | — | 当日有效 | **财报日历**，带 `time-pre-market` / `time-after-hours`、EPS 预期、预测机构数 |
| `https://api.nasdaq.com/api/market-info` | — | 当日有效 | 盘前开盘时间与倒计时 |

Nasdaq 这两个是未公开文档的接口，且需要带浏览器 User-Agent 才返回。
它们随时可能改或关，**接入时必须把「拿不到」当成正常分支处理**，不能让
一次 404 静默变成「今天没有财报」。

### 不可用

| 源 | 状态 | 说明 |
|---|---|---|
| `feeds.a.dj.com/rss/RSSMarketsMain.xml` | **假活** | HTTP 200，内容停在 **2025-01-27**。只看状态码会把它当成可用源 |
| `cnbc.com/.../rss.html` | 403 | |
| `finance.yahoo.com/news/rssindex` | 429 | 限流 |
| `reuters.com/markets/rss` | 401 | |
| `jiemian.com/rss.xml` | 404 | |
| `rsshub.app/wallstreetcn/live/global` | 403 | 公共实例被限；自建 RSSHub 可绕过，是额外一套服务 |
| `cls.cn/telegraph`（财联社电报）| 200 但是 HTML | 内容不在静态 HTML 里，需要另找其 JSON 接口或渲染 |
| X 关键词搜索 | 404 | **已于 2026-09-24 复测，`sources.json` 的记录仍然准确**。`twitter search` 返回 `Twitter API error (HTTP 404)`，发现只能按账号轮询 |

WSJ 那条是本次尽调最有用的一个发现：**HTTP 200 不代表源是活的。**
任何新增源都必须校验最新条目的时间戳，把「超过 N 小时没有新条目」当作故障上报。

### 需要你决定才能用

| 源 | 卡在哪 |
|---|---|
| **SEC EDGAR**（8-K 实时、全文检索）| 免费、无需 key，但 SEC 要求 User-Agent 里带**真实联系方式**。CLAUDE.md 明确禁止编造身份。用你的邮箱是你的决定，我不会替你填 |
| **Finnhub**（新闻 + 财报日历）| 免费档 60 次/分钟，但需注册拿 key，且条款写明仅限个人非商业用途；财报日历在免费档常被限制。注册是开账号，按 CLAUDE.md 我不会自作主张 |

## 三、定时怎么做

macOS 上用 **launchd**，不用 cron，理由是笔记本会睡：

- `StartCalendarInterval`（给一个字典数组，如 `Minute: 0` 和 `Minute: 30`）：
  机器睡过去的触发会在唤醒后补跑一次，这是默认行为且无法关闭。
- `StartInterval`（如 1800 秒）：睡眠期间的触发**直接丢失**，不补。
  另有现场报告称间隔超过 5–10 分钟后任务会在跑几次之后停止。

所以用 `StartCalendarInterval`。两个必须注意的点：

1. launchd 的环境是最小化的，不读 `.zshrc`，`PATH` 里没有你平时的东西。
   `ProgramArguments` 必须写**绝对路径的 venv python**，本项目是
   `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation/.venv/bin/python`。
2. 检查用 `launchctl print gui/$(id -u)/<label>`，能看到上次退出码和下次触发时间。
   加载用 `launchctl bootstrap gui/$(id -u) <plist>`，`launchctl load` 已废弃。

## 四、架构：别自己发明

公开实践里这条流水线是稳定的形状（一个日处理约 1000 篇、事件在发布后
10–15 分钟内浮现的系统，LLM 成本每天几美元，因为向量化在本地跑）：

```
抓取(增量,带水位) → 去重 → 聚类成事件 → 打分 → 写作 → 人工审核
```

对本项目的映射：

| 阶段 | 现状 |
|---|---|
| 抓取 | `live/collect.py` 已是 append-only + 水位（`first_seen_run`），**只差新闻源** |
| 去重 | 需要新建。公开做法是分层：先 URL/内容 hash，再用向量余弦抓通稿改写 |
| 聚类成事件 | 需要新建 |
| 打分 | `live/hotspots.py` + `live/opportunities.py` **已经有了**，且是按自身基线算的 |
| 写作 | `live/write.py` 已有，本轮刚接上观点输入 |
| 审核 | `ml/human_review.py` 已有 |

**缺的是中间两段，不是整条链。**

去重必须分层的原因：同一条通稿被多家媒体发出来，URL 不同、正文接近，
只靠 hash 去不掉。这正是 investing.com 这类聚合源会大量出现的情况。

### 本地算力够，不用花钱

已确认在位：

- `.runtime/models/embedding/` 有本地向量模型
- `sentence_transformers` / `scikit-learn` / `numpy` 都已安装
- `:8683` **当前正在运行**（`/health` 返回 `{"status":"ok"}`）

> 注意：CLAUDE.md 写的是 `:8683 已停止`，实测与之不符。本文不改那份文件，
> 只记录实测。**在替代方案验证通过前不要杀掉 `:8683`。**

所以去重和聚类可以完全本地跑，零调用成本，符合公开实践里
「向量化在本地、LLM 只用在最后合成」的成本结构。

### 公开实践里踩过的坑，值得直接抄

- **先质检再去重**，不合格的记录隔离而不是丢弃。与本项目既有纪律一致。
- **向量模型一换，几何就变**，去重、聚类、缓存全部受影响。换模型等于重建索引，
  且跨越换模型时点的时间区间不能直接比较。
- 小模型做改写会**补出原文没有的细节**。本项目的 slot 审计已经在防这个。
- 每源限条数 + 滚动回看，**不保证高峰期不漏**，也不保证长时间断线后能补齐。
  覆盖率要如实上报，不能假装完整。

## 五、建议的落地顺序

1. **先加源，不加定时。** 接 investing.com 中英 + seekingalpha + Nasdaq 财报日历，
   每个源都带「最新条目时间戳」校验，超时未更新即上报故障。手动跑几天，
   看真实量级和噪声。
2. **再做去重与聚类。** 有了真实流量才知道阈值该定在哪，
   现在定就是又一次凭空发明参数。
3. **最后才上 launchd。** 一个会自己跑的后台任务，在链路没验证前只会
   悄悄产出一堆没人看的东西。

「盘前 AMD」具体怎么被触发，按这三步走完后是这样：
财报日历提前知道 AMD 哪天盘前报（Nasdaq 接口的 `time-pre-market` 标记）→
当天盘前时段提高轮询频率 → 新闻源和 X 账号的新内容聚成一个事件 →
`opportunities.py` 打分 → 写作 → 进待审核。

## 六、需要你决定的三件事

1. **SEC EDGAR 用不用你的邮箱做 User-Agent。** 不用就没有 8-K 实时流，
   财报原文只能等发布页或二手源。
2. **要不要注册 Finnhub 免费 key。** 不注册的话，财报日历只能靠 Nasdaq
   那个未公开接口，单点且随时可能断。
3. **要不要在你机器上装常驻定时任务。** 建议按上面的顺序，最后再装。

## 复核命令

```sh
# 源是否还活着（看的是时间戳，不是状态码）
for u in https://www.investing.com/rss/news.rss \
         https://cn.investing.com/rss/news.rss \
         https://seekingalpha.com/market_currents.xml; do
  echo "== $u"; curl -s -m 15 "$u" | grep -oE "<pubDate>[^<]*" | head -2
done

# 财报日历
curl -s -H "User-Agent: Mozilla/5.0" \
  "https://api.nasdaq.com/api/calendar/earnings?date=$(date +%Y-%m-%d)" | head -c 300

# X 关键词搜索是否仍然 404
twitter search "NVDA" -n 3 --json
```
