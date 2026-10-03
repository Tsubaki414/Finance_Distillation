# Demo Notes · Content Intelligence

## 打开

后端未运行时：`.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680`

| 路由 | 内容 |
|---|---|
| **`http://127.0.0.1:8680/`** | **默认首页：Content Intelligence 工作台（Today）** |
| `/#workspace` | 直接进入 BLS Opportunity Workspace |
| `/demo` | **307 重定向到 `/`**。旧书签不会再落到审计页 |
| `/system-status` | 原工程审计页，已降级，不再是默认入口 |
| `/legacy` | 原 4 页 corpus UI，保留未删 |

截图：`runs/demo-screenshots/today-1440x900.png`、`workspace-1440.png`。

## 60 秒点击顺序

1. **首屏**（10s）念标题 "What deserves attention now?"。右上角三个图例：Real evidence / Illustrative / Unavailable。1440×900 内同时看到 Narrative Pulse、Upcoming Catalysts、Opportunity Queue。
2. **Narrative Pulse**（10s）左侧大卡 `DIVERGING · Real evidence`：美国就业市场。共识行"Labour demand is cooling, not collapsing"，分歧行"participation drop 是 discouragement 还是 demographics"。右侧两张斜纹卡标 `Illustrative`，明说没有数据。
3. **What KOLs are saying**（8s）真实原帖节选，不是分数表。qinbafrank 两条谈非农与劳动力市场走弱，phyrexni 直接评论非农数据。每条带作者、话题标签、日期。
4. **Opportunity Queue**（7s）第一条 `Real evidence`，右侧 `Blocked` 标签 + `Open workspace`。点它。
5. **Workspace 左栏**（8s）Official facts 51 条，展开可见 `payroll 162,000`、`participation 61.6`。点 KOL voices 展开真实 post 相关度。
6. **中栏**（10s）Lead question 是模型自己的独立提问。Angles 中 `Participation and part time` 标红 `missing from draft`。正文每句尾部带 fact ID。
7. **右栏**（7s）切换三个 persona；五个 donor role 全部 `Not yet retrieved`。底部 `Blocked · 5 issues` 点 Review 展开，第一条即 `0.44 万` vs `4.4 万`。

## Real / Illustrative / Unavailable

**Real evidence（有本地 artifact）**
- BLS 事实包 51 条 typed facts，每条带精确字符 span（`sources/packets/`）
- **18 条 KOL 真实原帖正文**，按 Macro / Earnings / Positioning 三个话题分组，含作者与日期（`retrieval.json` + `raw_posts.jsonl`）
- 6 位 donor 的 point-in-time 画像；12 位有样本，事件时点仅 6 位可用（`profiles_v2/`）
- 稿件 9 句 evidence ledger 与 5 条人工 QA 发现（`cases/case-a29c6b6c0325.json`）
- Evergreen：192 文件、182 万字、三池、44 个独立来源（`evergreen/`）
- 下次 Employment Situation 日期，逐字引自 8 月发布原文
- **真实财报日历**：Micron 10-01、Alphabet 10-29、Amazon 10-30、AMD 11-04、Applied Opto 11-06、Nvidia 11-18。yfinance 1.7.0 取自 Yahoo，8 次请求、0 费用、缓存 12 小时（`data/finance_supplement/earnings_calendar.json`）
- **话题动量**：近 14 天 vs 前 14 天，Labour market +7.5pp、AI capex +1.7pp，词表可审计
- **标的讨论榜**：NVDA 77(+44)、BTC 73、MU 21、AVGO 17(+15)，由 $cashtag 与名称词典抽取

**Illustrative（只有结构，没有数据）**
- Opportunity Queue 第 2、3 条
- 顶栏 market / language / range 切换按钮（改变选中态，不筛数据）

注：Narrative Pulse 与 Upcoming Catalysts 已全部改为真实数据，不再有 Illustrative 卡。
- 顶栏的 market / language / range 切换按钮（改变选中态，不筛数据）

**Unavailable（能力未建）**
- 传播层：谁最早提出、谁在传播。回复父帖解析为 0，1,510 条引用帖中 1,412 条缺被引作者
- 跨语言信息差：未实现对齐
- KOL 立场分类：赞成与反对未经分类器判定，页面明写 `Stance not classified`
- Evergreen 原则检索：尚未抽取任何原子原则
- Donor 角色分配：五个槽位全为 `Not yet retrieved`
- 配图生成：图表生成器写死为 payroll 柱状图
- 机构研究源：未接入

## 已知限制

- BLS 是**历史回放**，非实时。唯一产出的稿件是 `qa_failed_regression_case`，页面全程标 `Blocked`，不得展示为成功案例。
- 三个 persona 目前指向同一首选 donor，组合无区分度。
- 左侧导航中 Drafts & Visuals、Library & Updates、Collector Inbox、Pipeline Runs、Settings 为占位，点击显示明确说明，不是空白页。
- 所有 QA 结论为 `model_reviewed`，真人审核 0 条。
- 本轮未装依赖、未改 pipeline、未运行生成。

## 实现备注

后端 CSP 为 `style-src 'self'`，会拦截内联 `<style>` 与 `style=` 属性。样式全部走外部 CSS 文件，动态宽度用 CSSOM 赋值。CSP 未放宽。
