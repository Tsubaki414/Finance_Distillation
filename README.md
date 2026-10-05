# Finance Distillation

Mango Labs 金融内容蒸馏流水线：共享观点库 → 判断先行的人设账号 → 可审稿草稿。  
当前工作分支：`fd-phase0`（也是 GitHub 默认分支）。`main` 是 Phase 0 前基线快照。

**状态：** 可本地演示「来源 → 内容单元 → 立场 → 成稿 → 软质检」。尚未绑定真实发帖账号，未做人工验收，未自动发布。

## 这套系统做什么

1. 从合规来源拉取 / 抽取内容单元（带日期、授权等级）
2. 为人设选题（观点类 + 事实类配比；跨号同结论仲裁）
3. 立场层结合观点账本（只记看法，不记仓位）
4. 按人设语气卡成稿（Gemini 默认，失败回退 Claude）
5. 软质检：模板句、过火表述、主张接地、情绪分档（高/中/低）

不做：粉丝增长、赛马指标、未经人工确认的发帖。

## 仓库里有什么 / 没有什么

| 已上传 | 未上传（gitignore） |
|--------|---------------------|
| 代码、配置、人设卡、渠道注册、测试 | `live/store/` 内容单元库 |
| 脚本与文档 | `live/donors/posts/`、`tags/` 帖子语料 |
| | `live/sources/` 书籍 PDF 等 |
| | `store/view_ledger/` 观点账本运行数据 |
| | `.env`、密钥、本地虚拟环境 |

密钥只通过环境变量注入，例如：`GEMINI_RELAY_API_KEY`、`RELAY_API_KEY`、`TYPESAFE_API_KEY`、`APIFY_TOKEN`、`RAPID_X_API_KEY`。仓库内不应出现明文 key。

## 快速开始

```bash
cd Finance_Distillation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 若文件存在；否则按项目依赖安装
cp .env.example .env              # 若有示例文件；自行填入 key
bash scripts/run_tests.sh         # 基线约 22 个既有失败，勿新增
```

成稿模型默认见 `live/stage_models.json`（compose → Gemini；其他阶段 → Claude）。

常用脚本：

- `bash scripts/cron/daily_ingest.sh` — 日更拉取（默认成本上限约 $8）
- `scripts/backup_live.py` — 备份 live 数据目录

## 人设与账号外壳

流水线侧有约 10 个内容人设（语气卡、选题、样稿）。  
**尚未**配置真实 X 账号的头像 / 显示名 / handle / bio；需要时另导出账号包装包给运营配号。

## 分支说明

- `fd-phase0` — 当前开发与演示分支（判断先行改造、跨号仲裁、主张检查、情绪分档等）
- `main` — 进入 Phase 0 前的冻结快照

## 注意

- 私有仓库；内部演示用，勿公开外传未脱敏样稿中的未公开研报内容。
- 券商研报署名策略见 `live/source_display.json`（默认不点名机构，写「券商研报 / sell-side research」）。
- 大数据与语料在运行机本地，clone 后需自行同步或重新拉取。
