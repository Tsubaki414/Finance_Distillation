# 运行手册

当前为交接冻结；本轮只执行只读核验和迁移。下面含历史已执行命令和未来恢复命令，**不是要求接手立即运行整表**。除“安全核验”外，其余操作先等用户恢复实施。`python` 一律指本项目 `.venv/bin/python`，不使用系统 3.14 替代。

```sh
cd /Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation
```

## 已保留环境

Python 3.12.14；macOS Apple Silicon，本机内存限制不适合同时跑 MLX LLM、ASR、多个模型。mlx 0.32.2、mlx-lm 0.31.3、FastAPI 0.141.1、uvicorn 0.52.4、sentence-transformers 6.0.1、scikit-learn 1.9.0、torch 2.14.0、numpy 2.5.2、mlx-whisper 0.4.3；精确全量依赖见 handover/requirements.freeze.txt 与 runtime-versions.json。旧 requirements.versions.txt 不包含后来 ASR 全部依赖，不当最新锁。

ffmpeg `/opt/homebrew/bin/ffmpeg`；yt-dlp `/Users/fionama/.local/bin/yt-dlp`；字幕 JS runtime 在 `/Users/fionama/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`。它们属本机外部依赖，没有把全局软件移入工程。官方三个全局 skills 同理；项目六个 .agents/skills 已迁移。

旧根路径兼容链接保留，确保 venv console shebang 和日志/锁里历史绝对路径仍可解析。新根 `.venv/bin/python -B handover/test_invariants.py` 已执行成功。不承诺此 venv 可直接复制到 Linux 或另一台 Mac。

## 凭证名称（只检查存在，不打印值）

| 名称 | 用途/当前限制 |
|---|---|
| XQUIK_API_KEY | 唯一选定的新 X 采集 API；没有已运行采集/成本估计 |
| RAPIDAPI_KEY | 原工程授权 RapidAPI；只能使用已授权范围，不能当 Xquik key |
| APIFY_API_TOKEN | 历史导入来自 Apify；当前不混跑新的 X 采集器 |
| SEC_EDGAR_USER_AGENT | SEC 真实联系方式/User-Agent；MCP 当前禁用，不虚构身份 |
| HF_TOKEN | 公共模型下载不需要；已有工具使用 token=False/禁隐式凭证 |
| OPENAI_API_KEY / GROQ_API_KEY | 当前本地 LLM/ASR 不使用；不能自动付费兜底 |

存在性报告只针对当前进程环境，不表示 `.env` 没有 key。用户允许读取的 RapidAPI env 在原 Finance_Stocks_KOL 工程；交接不打开、不复制、更不迁移它。运行时按授权安全注入值，禁止将值写进 prompt、命令回显、代码或交接。

## 安全核验（现在可运行）

```sh
sh scripts/verify_handover.sh
.venv/bin/python -B handover/test_invariants.py
```

两者无外网、无付费、无数据修改；第一条唯一写入 handover/verification.json，第二条不写文件。SQLite mode=ro，不 import backend；前者再次全量校验迁移前 hash。exit 0=检查到的门槛全部通过，1=交接完整性失败，2=完整性通过但产品验收仍 FAIL/UNKNOWN，3=核验程序异常。Git 未初始化记录 UNKNOWN/null，不造 branch 或 clean 状态。

不要运行 scripts/validate_slice.py 作为“安全单元测试”：它 import app、发本地 POST、保存 diagram/报告；当前旧生成断言也不符合新标准。

## 恢复运行命令表

| 命令（项目根执行） | 外部 API/费用 | 写入及输入→输出 | 执行证据/限制 |
|---|---|---|---|
| `.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680` | 无外网/0 API费 | 读 corpus/personas/SQLite；app 可能建表，后续 POST 会写 DB | 迁移前真实运行；迁移时已停止，迁移后未启动 |
| 在现有 Chrome 打开 `http://127.0.0.1:8680` | localhost/0 | 前端同源由后端提供，无 npm dev server | 旧 UI，未完成新 evidence_loop 展示；不要改用 ambient IAB |
| `.venv/bin/python scripts/start_local.py` | 本地模型/0 API费 | 启动模型+后端，写 runs/start-*.log | 先前启动成功；会占内存，交接期不运行。默认 modern :8683，seed/temp 在 client |
| `.venv/bin/python scripts/import_corpus.py` | 无新 API/0 | 读原外部工程 5 snapshot →备份旧 import后重写 raw/clean/manifest，append ledger | 已运行 6 次。当前冻结不可重跑；缺外部输入则不可移植复现 |
| `.venv/bin/python scripts/audit_promotions.py` | 无/0 | 读 clean→推广检查报告 | 历史执行；会重写旧报告，不在交接运行 |
| `.venv/bin/python evidence_loop/import_sources.py` | 无/0 | 只读原 Excel 允许列→catalog | 已执行；不读主观评价，目标文件会重写 |
| `.venv/bin/python evidence_loop/discover_video.py` | YouTube/Bili 公共接口；无显式API费 | 固定 seeds/search→discovery响应/log | 已执行；不是持续发现；重跑覆盖部分日志 |
| `.venv/bin/python evidence_loop/acquire_video.py` | 公共视频 metadata/字幕；无显式API费 | 已选视频→info/VTT/acquisition | 已执行，存在 429/无字幕；先改 append-only 再复跑 |
| `.venv/bin/python evidence_loop/acquire_audio.py` | 公共视频音频；无显式API费 | metadata→m4a/WAV/audio-runs | 已执行：Bili 3 成功，YT 4 失败；不要掩盖403或取Cookie绕过 |
| `.venv/bin/python evidence_loop/transcript_pipeline.py` | 无外网；0 | 现有 VTT→cues/全文/segments/index | 已执行：3 YT/149 segments；会重写版本，后续先版本化 |
| `.venv/bin/python evidence_loop/transcript_pipeline.py --asr` | 设计为本地ASR/说话人，权重已在本地；无付费API | 音频→ASR/diarization与分段，GPU/CPU开销 | 从未运行，未知运行错误；当前4个YT缺audio，先补按视频失败隔离/跳过，不能直接宣称此命令可完成6视频 |
| `.venv/bin/python scripts/fetch_primary.py` | BLS 公共网页；0显式费 | 网络→data/evidence；错误记ledger | 曾3失败；不是完整表格抽取器 |
| `.venv/bin/python scripts/finance_supplement.py` | Yahoo/NVDA；0显式费，不保证商业授权 | NVDA历史/预期→finance_supplement和ledger | 真实3 operation成功；不能替代IR/SEC/电话会 |
| `.venv/bin/python evidence_loop/build_event.py` | 不联网/0 | 现有 BLS 全文→51fact/616block packet | 已执行；固定月份措辞、表格/时间 bug，重跑前修复并新版本 |
| `.venv/bin/python scripts/run_ml.py` | 禁网本地embedding/传统模型/0 | raw/clean→A/B/聚类/旧profile/CSV/Trackio | 真实执行；会重写当前指标甚至人工标注CSV，恢复前保护标注与输出版本 |
| `.venv/bin/python scripts/classify_comparison.py` | 本地模型 :8682/0 | 真实帖子→LLM分类请求/预测指标 | 历史已执行；新模型服务需对应启动，不能同时挤占全部内存 |
| `.venv/bin/python evidence_loop/build_profiles.py` | 本地规则/像素与现有标注/0 | clean/reading-notes/images→5轴profiles/versions | 已执行；当前不消费视频，不是端到端蒸馏 |
| `.venv/bin/python evidence_loop/prepare_experiments.py` | 本地embedding/0 | facts+profiles+固定cache→routing/retrieval/protocol | 已执行；会覆盖 protocol、需修hash绑定/时间泄漏，新建run不能覆盖失败 |
| `.venv/bin/python evidence_loop/run_experiments.py` | 本地 :8683/0API费 | 同事实/协议→plans/drafts/cases/model_calls | 实际3失败1中断，未完成；现有 main 对已存在失败/中断格直接跳过，不会自动重试；恢复后先修复并新protocol/run |
| `.venv/bin/python -m json.tool ml_experiments/A_finance_classification.json` | 无/0 | 读→stdout | 可查看真实银标指标，非真人质量 |
| `.venv/bin/python -m json.tool handover/verification.json` | 无/0 | 读最新核验→stdout | 当前验收事实入口 |

### 新 X 真实采集

当前**没有已实现、已运行的新 Xquik timeline/backfill CLI**，不能编造一个命令。审计和 API endpoint 文档位于 `.agents/skills/x-twitter-scraper/references/`，代码/网络/凭证/成本审计见 skill-audit。恢复后先在同一选定方案内做真实分页与费用估计、持久 cursor/运行账本，再在已授权预算内运行；不得改用另一套 X collector 来制造“通过”。Phase 0 RapidAPI probe 只有 6 请求，不能重跑它充当 backfill。

### 重建依赖/模型（本次未运行）

本机完整 venv 和模型已经迁移，不需要下载安装。另一台同架构环境可用下列命令新建隔离环境，不能覆盖现有 `.venv`：

```sh
python3.12 -m venv .venv-rebuild
.venv-rebuild/bin/python -m pip install --no-cache-dir -r handover/requirements.freeze.txt
```

外网 PyPI，可能下载较大 wheel、写新环境；无显式付费 API。此完整版本集合来自实际 importlib.metadata，不是经全新机器安装验证的可移植 lock；部分 macOS/MLX wheel 平台限定。原 venv 无 pip 模块，不要在其中直接 `python -m pip` 假设可用。

模型精确 revision/file hashes：model-lock.json、comparison-model-lock.json、modern-model-lock.json、transcripts/audio-model-lock.json。已有 prepare_* 脚本会查询当时远端 latest，再下载并覆盖锁，不是对旧 revision 的复现命令；当前不要重跑。恢复迁移到新机器时用已有 lock 的 repo+revision 定向下载、核对 hash，禁 trust_remote_code/隐式token。下载有带宽/磁盘成本，不能误称无成本。

## 导出与交付

本次完整本地项目目录就是可接手包。只导出交接文档（不含 raw 媒体响应、凭证、模型）可执行：

```sh
tar -czf handover-review.tar.gz CLAUDE.md docs handover
```

此命令无 API/0 API费，写项目根的新归档；未在交接运行。完整项目已在本地迁移，未上传或部署。

**当前没有合格内容可导出给运营。** backend `/api/export/{rid}?audit=true` 仍能打包旧稿，仅供失败审计。恢复服务后验证隔离旁路的只读请求示例：

```sh
curl --fail 'http://127.0.0.1:8680/api/drafts/draft-45b14189a954?audit=true'
```

无外部 API/0费，不写数据；迁移后未执行。不能把该响应/旧 ZIP 当有效内容。等新完整 source/donor/plan/draft/ledger/QA/human review 合格后再实现正式 Content Package 导出（正文、数据、图片/spec、来源、图注/alt、版本、失效条件）。
