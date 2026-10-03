# 最终交接报告

项目已迁移到 `/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation`。Claude Code 应打开该根目录，先读 `CLAUDE.md`。源码直接在根目录，历史材料在 `historical_workspace/`；旧 `outputs/vertical-slice` 只保留兼容符号链接。原 KOL 工程、.env、Excel、Reads ZIP 未迁移或改写，明细见 external-inputs.json。

迁移 81,389 个普通文件、129 个符号链接、13,557,049,648 bytes，逐文件 SHA-256 在迁移后和最终核验均一致。包括模型、虚拟环境、缓存、语料、旧稿和失败日志。没有发布/部署/push。无 Git 仓库，branch、commit、dirty_files=null，不能称工作区 clean。实验、模型和后台已停止。

## 已验证、失败和未知

| 类型 | 结论 |
|---|---|
| 已验证 | 必需交接文件、依赖、Python语法、全部迁移hash、8个真实数据完整性测试；raw2647/clean1825、12个有语料donor；3 YouTube/149 segments；727本地调用记录（722 completed/2 failed/3 started） |
| 未通过 | donor逐人深度和原创/语言配额、真人标签/审核、五组新实验、Bili transcript/说话人/校正/跨平台去重、Intelligence Desk/可解释人设、Claim Graph/Evergreen/自动更新、完整旧稿隔离 |
| 未知 | Git metadata不适用而为null；完整表格/事实语义复核；当前完整浏览器验收；部分历史wire请求数、分页深度和费用 |
| 有效内容 | 有效稿0，legacy_invalid_output45（另有37旧拒绝尝试）；真人评审0；3个新计划截断失败、另1格交接时中断，没有有效generation baseline |

当前核验 PASS 7 / FAIL 8 / UNKNOWN 3，最终退出码 **2**；安全单元测试退出 **0**。2表示冻结文件完整性通过、产品未达到验收标准。

首次核验因 sherpa_onnx 与 sherpa-onnx 名称匹配错误退出1，仅修复新增核验器，没有安装或修改依赖。初次 JSON 和完整输出保留在 verification-initial.json / verification-initial-output.txt，没有抹去失败。最终原样输出如下。

## 最终实际执行输出

命令：`sh scripts/verify_handover.sh`

```text
Finance Distillation handover verification (offline, read-only inputs)
Artifact checks complete; verifying all migrated files against their pre-move hashes.
ROOT /Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation
GIT not a Git repository; branch=null commit=null dirty_files=null
DATA raw=2647 clean=1825 authors=12 human_labels=0
CLEAN_LANGUAGES {"en": 510, "et": 1, "ja": 10, "zh": 1304}
DRAFTS valid=0 legacy_invalid=45 human_reviews=0
VIDEO_READY {"youtube": 3} segments=149
MODEL_CALL_RECORDS {"completed": 722, "failed": 2, "started": 3}
ENV_PRESENT {"APIFY_API_TOKEN": false, "GROQ_API_KEY": false, "HF_TOKEN": false, "OPENAI_API_KEY": false, "RAPIDAPI_KEY": false, "SEC_EDGAR_USER_AGENT": false, "XQUIK_API_KEY": false}
PASS required_files
UNKNOWN git_metadata
PASS dependencies
PASS python_syntax
PASS artifact_unit_tests
PASS migration_all_file_hashes
PASS frontend_backend_entries
FAIL twelve_qualified_donors
FAIL human_annotations_and_review
UNKNOWN source_complete_semantic_review
FAIL five_group_ablation
FAIL three_youtube_three_bilibili
FAIL speakers_financial_correction_crossplatform_dedup
FAIL intelligence_desk_and_explainable_personas
FAIL claim_graph_evergreen_update_pipeline
FAIL legacy_isolation_all_routes
UNKNOWN live_ui_acceptance
PASS marker_and_api_location_inventory
COUNTS {"FAIL": 8, "PASS": 7, "UNKNOWN": 3}
SAFE_TEST_EXIT_CODE 0
REPORT handover/verification.json
EXIT_CODE 2
```

完整 JSON 在 verification.json，纯文本在 verification-output.txt，迁移逐文件清单在 migration.json。核验脚本只写 verification.json，不下载、不联网、不调用模型、不改业务文件。产品失败项基于静态代码审计和已复核的冻结hash，不是未来新实现的E2E验收套件；恢复开发需要新的验收测试和运行版本。

## Claude Code 前三个动作

1. 读 CLAUDE.md、CURRENT_STATE_AUDIT、KNOWN_FAILURES，核验冻结状态，保留全部失败和旧稿隔离；确认用户恢复实施再写产品代码。
2. 修复旧稿接口/训练/评估旁路、完整事实包和表格审核、计划JSON截断/中断恢复。先用一个新run证明 source→donor→profile→retrieval→独立plan→draft→逐句证据→评估，再运行同证据五组实验。
3. 补足真实donor与300人工标注、3 Bili ASR/说话人/校正；用五名KOL同热点与10来源Evergreen完成图谱、三persona、自动证据更新和前端回放，不缩减原验收。

## 创建和修改范围

以下为交接文件清单。除用户授权的迁移、兼容链接和停止本项目进程，交接未改业务源码、语料、旧输出或模型记录。新增核验器/交接报告的修订不属于业务修改。原任务书副本和SHA在 requirements；旧报告没有被本次报告覆盖。

- `CLAUDE.md`
- `docs/ACCEPTANCE_TESTS.md`
- `docs/CONTENT_PIPELINES.md`
- `docs/CURRENT_STATE_AUDIT.md`
- `docs/DATA_LINEAGE.md`
- `docs/KNOWN_FAILURES.md`
- `docs/REPOSITORY_MAP.md`
- `docs/RUNBOOK.md`
- `docs/VIDEO_TRANSCRIPT_PIPELINE.md`
- `handover/REPORT.md`
- `handover/api-evidence.json`
- `handover/build-tools/README.md`
- `handover/build-tools/build_finance_handover.py`
- `handover/build-tools/finance_distillation_migrate.py`
- `handover/build-tools/finance_handover_docs.py`
- `handover/build-tools/finance_handover_finalize.py`
- `handover/build-tools/finance_handover_finish_docs.py`
- `handover/build-tools/finance_handover_outputs.json`
- `handover/deliverables.json`
- `handover/external-inputs.json`
- `handover/freeze.json`
- `handover/manifest.json`
- `handover/manifest.pre-verification.json`
- `handover/migration.json`
- `handover/requirements.freeze.txt`
- `handover/requirements/01-original-project-brief.txt`
- `handover/requirements/02-visual-brief.txt`
- `handover/requirements/03-real-vertical-slice-correction.txt`
- `handover/requirements/04-handover-request.txt`
- `handover/requirements/index.json`
- `handover/runtime-versions.json`
- `handover/state-snapshot.json`
- `handover/test_invariants.py`
- `handover/verification-initial-output.txt`
- `handover/verification-initial.json`
- `handover/verification-output.txt`
- `handover/verification.json`
- `scripts/handover_checks.py`
- `scripts/verify_handover.py`
- `scripts/verify_handover.sh`
