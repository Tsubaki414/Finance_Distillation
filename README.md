# Finance Distillation

共享金融观点库驱动的多账号内容流水线：把公开合规来源蒸馏成 **判断先行** 的专业金融人设草稿，覆盖宏观、产业、加密、短线结构、图表与投资哲学。

当前默认分支：`fd-phase0`。`main` 为进入本阶段前的基线快照。

## 产品形态

```
来源接入 → 抽取内容单元 → 选题与路由 → 人设立场（观点账本）→ 成稿 → 软质检 → 可审草稿
```

- **共享观点库：** 来自研报、宏观数据、公司文件、播客转写、链上/期权公开数据、机构备忘录等渠道；单元带日期与授权等级。
- **判断层：** 每条草稿先形成账号立场（方向、信心、期限、条件），再写成帖；同一主题可对照账号历史观点，避免天天换脸。
- **跨号仲裁：** 同一天、同一结论只保留最对口的人设，其余标记 HOLD，允许方向相反的真实分歧。
- **语气与情绪：** 每张人设有招牌写法卡；情绪强度按人设分高 / 中 / 低三档。
- **主张接地：** 按句检查是否支持主张、是否编共识、是否把类比当证据；过火表述会触发一次重写。

成稿默认模型见 `live/stage_models.json`（compose 使用 Gemini；其他阶段使用 Claude，失败时自动回退并留痕）。

## 十个人设

| ID | 语言 | 定位 | 核心题材 | 情绪档 |
|----|------|------|----------|--------|
| `zh_macro` | 中文 | 宏观与数据流评论 | 美联储、通胀、就业、汇率、关税、中国政策、油价 | 中 |
| `en_macro` | 英文 | Macro / data flow | Fed、通胀、就业、日元与汇率、关税、油价 | 低 |
| `zh_industry` | 中文 | 个股与产业机制 | AI 资本开支、财报、供应链、产业政策 | 中 |
| `en_industry` | 英文 | Stocks / industry | AI capex、财报、产业与供应链 | 中 |
| `crypto_macro_zh` | 中文 | 加密宏观 | BTC、稳定币、监管、宏观联动 | 高 |
| `crypto_macro_en` | 英文 | Crypto macro | BTC、稳定币、监管、链上数据 | 高 |
| `trading_shortterm` | 英文 | 短线市场结构 | 期权仓位、dealer 对冲、资金流、技术结构 | 高 |
| `market_data_charts` | 英文 | 图表驱动的市场数据 | 广度、情绪、资金流、历史对比 | 高 |
| `investing_philosophy` | 英文 | 投资哲学 | 风险、行为、长期原则 | 低 |
| `single_stock_deepdive_en` | 英文 | 单股速评 | 财报与公司文件的第一判断 | 低 |

另有一条辅助线 `en_morris_archive`：把有价值的历史中文思路精选到英文读者，不冒充原作者人设。

每个人设在仓库中对应：

- `live/accounts.json` — 账号元数据、题材 beats、来源偏好
- `live/personas/<id>.json` — 人设卡
- `live/personas/signature_cards/` — 招牌开场 / 收尾 / 禁忌等硬约束

## 流水线要点

### 选题

- 事实类与观点 / 机制 / 格言类配比；池中有非事实单元时，包内至少带 1 条。
- 数据作证据，不作正文骨架；第一句必须是判断。

### 观点账本

- 只记录看法（subject、direction、信心等），不记录仓位。
- 有旧观点时优先延续或明确改判；新稿与旧观点冲突时给出提示。

### 质检（软优先）

- 模板句、清单体研报腔、确定性超过原观点、编造共识、类比当证据等。
- 高情绪人设可触发一次情绪向重写；中低档以提醒为主，避免严谨号被「硬情绪」带偏。

### 日更

- `scripts/cron/daily_ingest.sh`：按渠道拉取与抽取，默认成本上限约 $8。
- 短线侧已接入 Cboe put/call、VVIX/SKEW、SqueezeMetrics、Moontower 等公开日更源。

## 仓库内容

| 包含 | 说明 |
|------|------|
| `live/` 代码与配置 | 适配器、抽取、立场、成稿、质检、仲裁、情绪分档 |
| `live/accounts.json` / `personas/` | 十人设定义与招牌写法 |
| `scripts/` | 测试、日更、备份等 |
| `tests/` | 单元与回归测试 |

大型运行数据（内容单元库、donor 帖子语料、本地书籍源、观点账本运行态）留在运行环境，通过 `.gitignore` 与代码分离；clone 后按环境变量配置密钥并拉取 / 同步数据即可使用。

环境变量示例：`GEMINI_RELAY_API_KEY`、`RELAY_API_KEY`、`TYPESAFE_API_KEY`，以及各数据源所需 key。模型与阶段映射见 `live/stage_models.json`。

## 快速开始

```bash
git clone https://github.com/Tsubaki414/Finance_Distillation.git
cd Finance_Distillation
git checkout fd-phase0
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 按仓库依赖安装
export GEMINI_RELAY_API_KEY=... RELAY_API_KEY=...
bash scripts/run_tests.sh
```

## 分支

- **`fd-phase0`** — 当前开发与演示分支（判断先行改造、跨号仲裁、主张接地、情绪分档、来源署名清理等）
- **`main`** — Phase 0 前冻结快照

## 相关路径

- 人设与账号：`live/accounts.json`、`live/personas/`
- 成稿模型：`live/stage_models.json`
- 情绪分档：`live/emotion_tiers.json`
- 来源显示名：`live/source_display.json`
- 日更：`scripts/cron/daily_ingest.sh`
