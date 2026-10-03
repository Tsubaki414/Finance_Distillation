# 实际状态审计

核验根目录为 `Finance_Distillation`。依据代码、JSON/JSONL、只读 SQLite、原始响应和当前核验，不依据旧 README/报告自称的完成度。`verified_working` 只适用于具体已执行子能力，不等于产品验收。全面机器统计见 `handover/state-snapshot.json`，API 证据见 `handover/api-evidence.json`；最新复核见 `handover/verification.json`。

下表“复跑命令”中 V = `sh scripts/verify_handover.sh`；其余命令仅供用户恢复实施后使用，副作用在 RUNBOOK 中。不能在交接期执行采集、生成或重建历史数据。

| 能力声明 | 实际状态 | 代码位置 | 数据证据 | 可复跑命令 | 结论 |
|---|---|---|---|---|---|
| X/KOL 真实采集 | partial | scripts/import_corpus.py；backend/app.py:47 | raw 2647，clean 1825，12 donor；5 份外部历史输入 | V；python scripts/import_corpus.py（会重写） | 真实导入；仅早期另有 6 次 RapidAPI 单页探测，新 Xquik 请求 0 |
| 翻页、回填、定期更新 | not_implemented | import_corpus.py 仅按已有记录截取；Xquik 仅文档 | complete_180d 全 false | V；无已实现新采集命令 | 最多 500 条限额不等于完整回填；无调度器或持久游标 |
| YouTube/Bilibili 采集与字幕 | partial | evidence_loop/discover_video.py、acquire_video.py、acquire_audio.py、transcript_pipeline.py | 7 metadata；3 YT/149 segment；3 Bili 音频/0 transcript | V；python evidence_loop/transcript_pipeline.py | 字幕分段运行过，ASR/说话人没有运行 |
| 财报与权威来源 | partial | fetch_primary.py、finance_supplement.py；evidence_loop/build_event.py | BLS 39 页文本衍生件，51 fact/616 block；NVIDIA 10-Q PDF；Yahoo 3 补充操作 | V；python scripts/fetch_primary.py | BLS 二进制 403；完整表格未逐格规范；SEC MCP 禁用 |
| 清洗、推广去除、去重 | partial | import_corpus.py、promotion_policy.py | raw/clean、raw_source_ref、runs/promotion-cleanup.json | V；python scripts/audit_promotions.py（写报告） | 同作者精确去重、规则过滤真实；跨作者语义去重/完整 thread 重构不足，非真人金标 |
| 五轴 donor profile | partial | evidence_loop/build_profiles.py | 12 个有样本/46 个仅候选，feature n/method/post IDs/versions | V；python evidence_loop/build_profiles.py（写） | 表层经验统计，非已验证知识能力或推理习惯；23 帖阅读样本、24 图目检均为 AI 检视 |
| ML 分类/聚类/attribution | partial | scripts/run_ml.py、classify_comparison.py | A/B 指标、真实 embedding、topic_clusters | V；python scripts/run_ml.py（写） | 训练/推理真实；规则银标和 6 作者时间划分结果，不是蒸馏效果 |
| multi-donor 检索组合 | partial | evidence_loop/prepare_experiments.py | routing/retrieval：3 persona×3 donor×2 exemplars、角色权重、版本 | V；python evidence_loop/prepare_experiments.py（写） | 真实检索已完成；multi-donor 条件尚未调用，未证明成稿效果 |
| 实际 LLM 调用 | verified_working | scripts/model_client.py | 727 attempt 文件：722 completed/2 failed/3 started，722 响应 | V；只读 model_calls | 是本地 MLX 真调用；completed 仅表示收到响应，含不合法 JSON 和无效旧稿 |
| 独立分析计划 | broken | evidence_loop/run_experiments.py | 4 新 plan 响应；3 length 截断，1 JSON 可解析；0 新完成稿 | V；生成命令当前暂停 | 每格独立调用设计存在；未完成三 persona 的有效独立研究 |
| 证据引用/donor influence | broken | run_experiments.py 后半段；backend 旧 F1–F3 路径 | 无新完成句级 ledger；旧稿全部无效 | V；无完整链路复跑成功证据 | 实際输入追踪和自报使用不同于因果 attribution；lineage broken |
| 跨语言蒸馏 | broken | scripts/run_generation_experiments.py、backend/guarded.py | cross_language_tests/* 历史调用 | V；旧流程不得再作基准 | 用旧不完整事实包，无真人评审；新完整证据跨语言尚未执行 |
| 热点/叙事发现 | not_implemented | 现有固定事件 registry；embedding 聚类 | 无执行的 Claim Card/Event Graph | V | 主题聚类不等于共识、分歧、首发或动量 |
| Evergreen 提取/冲突图 | not_implemented | 历史 knowledge enrichment 仅局部框架 | 无 Atomic Principle/Conflict Graph/resurfacing run | V | 视频摘要/框架候选不满足交易原则系统 |
| 图片与图表 | partial | backend/app.py chart_svg/diagram_svg；build_profiles.py | 真 PDF 截图、SVG、24 原图（22 eligible） | V；已有图函数仅旧稿 | 确定性渲染有证据；统一图形、缺 persona grammar/更新闭环 |
| 前端后端连接 | partial | frontend/app.js；backend/app.py | runs/live-api-verification.json 等历史结果；可静态追 routes | V；python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680 | 曾连接真实导入与模型；新 evidence_loop 未接 UI；迁移后停止服务，未浏览器验收 |
| 自动化 pipeline | not_implemented | start_local.py 仅启动服务器；新 main() 为手工批脚本 | 无 source→opportunity→review→update 定时/事件 run | V | 顺序 CLI 不是后台事件调度；无失败重试和证据触发回放 |
| 评测/真人审核 | partial | A/B 脚本、review API；新协议 | 517 规则复核中 300 scored/217 abstained；human=0；新 15 格未完成 | V；只读评测 JSON | 存在真实 ML 诊断，产品盲测、事实忠实度、编辑成本未验证 |

## 逐作者规模

“原创”列按现存 provider 的 `post_type=original` 和规则金融标签保守计数，不代表真人确认。大量 quote 可能含有原创评论，应人工核验字段含义后单独报告，不能把所有 clean 当原创或臆改标签。仅 2 人达到该严格计数 150；所有人 180 天完整性均未证实。目标语言名单不能覆盖实际语言：alea 主要 en，部分 ja/et 标签可能错误。

| donor | raw | clean（含 quote/reply） | 严格原创金融规则计数 | clean 语言 | raw 时间覆盖 |
|---|---:|---:|---:|---|---|
| aleabitoreddit | 455 | 404 | 240 | en:399, ja:1, zh:4 | 2026-06-07 → 2026-09-05 |
| beth_kindig | 20 | 18 | 15 | en:18 | 2026-08-30 → 2026-09-05 |
| citrini | 20 | 1 | 1 | en:1 | 2026-08-27 → 2026-09-05 |
| ericjackson | 20 | 3 | 3 | en:3 | 2026-09-04 → 2026-09-05 |
| globalmktobserv | 20 | 10 | 7 | en:10 | 2026-09-04 → 2026-09-05 |
| kovainvest | 405 | 226 | 99 | en:56, et:1, ja:3, zh:166 | 2026-06-07 → 2026-09-05 |
| michael_qqq2025 | 435 | 338 | 182 | en:16, ja:4, zh:318 | 2026-06-08 → 2026-09-04 |
| phyrexni | 500 | 357 | 13 | ja:1, zh:356 | 2026-07-22 → 2026-09-05 |
| qinbafrank | 406 | 312 | 12 | zh:312 | 2026-07-01 → 2026-09-05 |
| rjccapital | 20 | 3 | 2 | en:3 | 2026-08-18 → 2026-09-01 |
| tradexwhisperer | 20 | 4 | 3 | en:4 | 2026-09-04 → 2026-09-05 |
| xingpt | 326 | 149 | 131 | ja:1, zh:148 | 2026-06-08 → 2026-09-05 |

原始 URL/ID/作者 ID/时间/hash 字段当前非空；`collected_at` 缺失 2527/2647，`provider_run_id` 缺失 120。thread_id 非空仍不能证明父帖、quote 对象和传播关系齐全。raw 是继承的 normalized provider payload，不是所有原始 HTTP 响应。

## API 请求实证与未知项

| 对象 | 已记录数量与结果 | 分页 | 保存位置/限制 |
|---|---|---|---|
| RapidAPI twitter241 早期探测 | 6 HTTP，6×200；PhyrexNi、vikramskr、fi56622380 各 profile+timeline | 3 timeline pages；每人 1 页 | historical_workspace/outputs/architecture-review/evidence/rapidapi_probe.json；保存 preview/metadata，完整 wire body 未保留；费用 unknown |
| 现有 corpus 历史 Apify/RapidAPI | 5 输入文件、6 次本地 import，新增网络请求 0 | 原始采集请求数/pages unknown | data/corpus_manifest.json、data/imports、api_run_ledger；不能从 2647 条反推请求数 |
| 新 Xquik | 0 请求、0 pages | 0 | 已选定但缺 key/可审计成本；不是 RapidAPI 的别名 |
| 本地 MLX | 727 attempt 文件，722 成功响应、2 调用失败、3 started | 不适用 | runs/model_calls；ledger 重复同 run ID 不再累加；started 不能证明 dispatch；API 费 0，不含硬件 |
| 旧 BLS 抓取 | 3 次操作失败，日志未存具体 HTTP status | 不适用 | runs/api_run_ledger.jsonl；没有补造 403 |
| 新完整 BLS | 2 HTTP：原 PDF 403、Jina 文本 200 | 39 页源文，非 39 请求 | evidence_loop/sources/acquisition.json；hash 是衍生文本，不是 PDF |
| NVIDIA 官方链接 PDF | 2 HTTP：302、200 | 1 文件 | runs/official-pdf-capture.json 与原 PDF |
| Yahoo NVDA | 3 operation 成功，各 4 rows | wire 请求数 unknown | earnings_history/earnings_estimate/revenue_estimate；库缓存可复用 HTTP，不把 operation 数当请求数 |
| X 图片 | 24 HTTP 200 | 不适用 | evidence_loop/visual/assets.json；并非新增 X timeline |
| 视频发现 | 3 YT CLI 查询，各最多 5 条；2 Bili search HTTP 200 | Bili 各 page=1；YT 内部 HTTP unknown | transcripts/discovery/runs.json 和响应 |
| Bili metadata/player | 3 视频×3 HTTP，9×200；无匿名字幕 | 不适用 | transcripts/acquisitions/BV*.json 保存每个请求状态与 hash |
| YT 字幕/音频与 Bili 音频 | 3 YT 字幕成品；4 YT 音频失败；3 Bili 音频成功 | wire 总数 unknown | acquisition/audio logs；部分重试覆盖之前文件，完整尝试次数已无法证明 |
| SEC EDGAR MCP | 0 调用，禁用 | 0 | runs/sec-mcp-preflight.json |
| 其他公共研究/权重下载 | 总请求数 unknown | unknown | 审计文件和模型锁证明现存文件，不证明完整网络账本 |

不能因为累计 API 操作多就声称有效蒸馏。模型调用中的绝大多数来自旧生成和分类诊断，新闭环有效稿仍为 0。
