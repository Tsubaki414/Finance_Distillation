# 仓库地图

实际根目录 `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`。无 .git。`historical_workspace` 是迁移保留的旁支材料，不能从中启动“产品”。旧路径兼容链接是本机迁移支持，不是可移植部署方案。

| 路径 | 实际用途与有效性 |
|---|---|
| frontend/index.html、app.js、style.css | 原四页 UI，默认 corpus；app.js fetch 本地 API。没有新 Desk、滑杆、Claim Graph 或 evidence_loop 前端 |
| backend/app.py | FastAPI 入口，挂载前端，读取静态 corpus/registry/旧 profiles，SQLite CRUD；通用生成被 acceptance gate 关闭 |
| backend/guarded.py | 旧生成/验证器，仍有可调用旧逻辑；不是有效生成基准 |
| scripts/ | 原采集导入、清洗、ML、模型、财务补充、生成、报告工具；handover_checks/verify_handover 为本次只读审计新增 |
| evidence_loop/ | 后续真实事实包、五轴画像、检索、协议、未完成生成、视频/视觉新工作；尚未整合前后端和调度 |
| data/raw_posts.jsonl、clean_posts.jsonl | 当前唯一 X 原始导入/清洗主文件；每行真实来源记录；不要把同一数据在 imports 的多版本相加 |
| data/corpus_manifest.json、imports/ | 输入文件 hash、导入 run、覆盖；旧导入快照保留 |
| data/lab.sqlite | 一个 records 表（下文）；无 normalized Event/Claim Graph schema |
| data/post_classification_review.csv | 517 规则银标复核，human_label 0；不是人工标注数据 |
| data/evidence/ | 旧 BLS 摘要 web-capture/registry、NVIDIA 原 PDF 与截图；固定 snapshot，旧 F1–F3 不能满足完整事实 |
| data/finance_supplement/ | Yahoo 和 NVIDIA 官方来源补充，外部第三方数据角色有限 |
| knowledge_profiles/、style_profiles/、content_habit_profiles/ | 旧画像版本，API 当前仍读这里；部分 LLM/规则局部提取，不能代表新五轴全部生效 |
| evidence_loop/profiles/、versions/ | 12 真实观测 donor，46 空语料候选，特征 n/method/post IDs/版本；index/reading-notes 非 donor |
| evidence_loop/experiments/ | protocol、routing、retrieval、4 cases；3 failed/1 interrupted，15 格计划未完成 |
| evidence_loop/sources/ | 原完整文本 acquisition/current/versioned packets，51 facts/616 blocks |
| evidence_loop/transcripts/ | 7 metadata、原始 VTT、完整文本、cue IDs、149 segments、Bili m4a/wav、发现/采集/失败 logs、audio model locks |
| evidence_loop/visual/ | 24 真实图片 .img（实际 JPEG/PNG）和 hash/像素/AI 目检；不是 24 张生成图片 |
| evidence_loop/quarantine/ | 45 无效稿 registry/排除策略；baseline-registry.json 已为 tombstone |
| personas/ | 旧 macro/industry/risk JSON；新 protocol 第三个 key 为 trading，不能直接当旧 risk API 已升级 |
| generated_samples/ | 45 旧无效稿件 JSON 原样保留，严禁训练/评估/产品计数 |
| ml_experiments/ | 真实 A/B 分析、embedding 缓存、银标预测、Trackio、notebook；D generation 和旧 blind 数据无效 |
| topic_clusters/、donor_compatibility_matrix.json | embedding 聚类及 donor 分布/相似度；非事件/立场/传播图谱 |
| cross_language_tests/ | 旧双向生成和自动评审；不完整事实包/无人审核，不合格 |
| runs/model_calls/、api_run_ledger.jsonl | 实际本地模型请求/响应、运行记录；失败/started 保留；API ledger 不能与 model_calls 重复计数 |
| runs/ 其余 | 旧测试/截图/自动审稿/更新回放；时间与输入各自冻结，不证明当前验收 |
| skill-audit/、.agents/skills/ | 锁定审计及六个项目 skill；安装证据≠对应产品能力完成 |
| .runtime/ | 模型权重/缓存，约 10.4 GB；模型锁在根目录和 transcripts；本机版本已保留 |
| .venv/ | Python 3.12.14 的本机环境，约 1.6 GB；console script 可能引用旧绝对路径；跨机器需重建 |
| historical_workspace/work/ | 原 scratch、repo-audit、npm/uv cache、临时依赖等，约 1.4 GB；有审计的未执行上游仓库 |
| historical_workspace/outputs/ | Phase 0 架构评审、静态 demo、旧 38 MB ZIP、早期资源方案；全部历史，不是新产品 |
| handover/、docs/、CLAUDE.md | 本次交接：来源、要求、事实状态、迁移哈希、运行手册、机器核验，不增加产品功能 |

## API routes（AST 读取，未启动服务）

| 方法 | 路由 | 函数 | 位置 |
|---|---|---|---|
| GET | `/api/status` | `status` | backend/app.py:47 |
| GET | `/api/corpus` | `corpus` | backend/app.py:49 |
| GET | `/api/profiles/{donor}` | `profiles` | backend/app.py:53 |
| GET | `/api/personas` | `personas` | backend/app.py:57 |
| GET | `/api/experiments` | `experiments` | backend/app.py:59 |
| GET | `/api/finance-supplement` | `finance_supplement` | backend/app.py:61 |
| GET | `/api/evidence-image/nvidia-income.png` | `evidence_image` | backend/app.py:63 |
| GET | `/api/evidence-original/nvidia-10q.pdf` | `evidence_original` | backend/app.py:65 |
| GET | `/api/promotion-audit` | `promotion_audit` | backend/app.py:67 |
| GET | `/api/editorial-reviews/{rid}` | `editorial_reviews` | backend/app.py:69 |
| POST | `/api/personas` | `edit_persona` | backend/app.py:75 |
| GET | `/api/events` | `events` | backend/app.py:86 |
| POST | `/api/evidence` | `ingest` | backend/app.py:90 |
| POST | `/api/generate` | `generate_api` | backend/app.py:138 |
| GET | `/api/drafts` | `drafts` | backend/app.py:144 |
| GET | `/api/drafts/{rid}` | `draft` | backend/app.py:146 |
| POST | `/api/edits` | `edit` | backend/app.py:152 |
| GET | `/api/history` | `history` | backend/app.py:158 |
| GET | `/api/chart/{rid}.svg` | `chart` | backend/app.py:166 |
| GET | `/api/diagram/{rid}` | `get_diagram` | backend/app.py:180 |
| GET | `/api/diagram-image/{rid}.svg` | `diagram_image` | backend/app.py:199 |
| POST | `/api/diagram` | `diagram` | backend/app.py:201 |
| GET | `/api/export/{rid}` | `export` | backend/app.py:210 |
| GET | `/api/blind` | `blind` | backend/app.py:222 |
| POST | `/api/blind-review` | `review` | backend/app.py:239 |
| GET | `/` | `index` | backend/app.py:244 |

## 数据库与调用

```sql
CREATE TABLE records (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
```

当前 kind：legacy_invalid_output 45、quarantined-generation 37、evidence 2、edit 2、diagram 3。draft/human-review 都为 0。payload 是 JSON，无数据库外键强制 provenance。`get(rid)` 不限制 kind，因此隔离存在旁路。审计用 SQLite `mode=ro`；不要 import app 作为“只读测试”，它的 db() 会建表。

模型调用统一位置 `scripts/model_client.py:call`，POST localhost `/v1/chat/completions`。三个模型角色 baseline/comparison/modern 只是旧运行时命名；其中 baseline 字样不能使旧稿成为实验基准。System prompt 在同文件；旧 prompt 在 backend/app.py、guarded.py、scripts/run_generation_experiments.py；新 prompt 在 evidence_loop/run_experiments.py。精确调用 prompt、temperature、seed、max_tokens、model revision 和响应在每个 runs/model_calls JSON。

## 固定值、fixture 与重复路径

- historical_workspace/outputs/architecture-review 中 review-demo 等是 Phase 0 static concept；以前报告与 ZIP 原样保留，不能用作现阶段验收。
- data/evidence/registry.json 和 scripts/build_evidence.py 有手填事件/摘要；固定 July→August replay 不等于自动更新。
- evidence_loop/build_event.py 固定本次 BLS 标题、月份措辞及 next_update；prepare_experiments.py 固定 embedding cache 文件名及初始三个问题。事件真实来源与硬编码解析逻辑必须分开描述。
- backend 图表针对固定 payroll/旧稿布局；app.js 默认 corpus/JSON 编辑；新文件的存在不代表前端使用。
- ml_experiments/baseline-v*、旧 D/blind/evaluation_report、generated_samples、cross_language_tests 中的生成结论全部依 `legacy_invalid_output` 政策处理；历史分类/attribution 原始预测可供诊断，不可混成新 generation baseline。
- 同一 post 在主文件、imports、model prompt 中重复保存不增加语料量；相同事件五组才可比较，而不是跨旧版本比指标。

原始迁移合计 81,389 文件、129 symlink、13,557,049,648 bytes（包含本机环境、缓存）。细到每文件 bytes/SHA-256 的 inventory 在 handover/migration.json。不要发布或上传整个目录：原始媒体元数据可能带已过期签名 URL，且模型/环境不是代码交付必需文件。本次仅本地迁移，没有对外传输。
