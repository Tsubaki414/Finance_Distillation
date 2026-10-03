from pathlib import Path
import json,datetime,sys,shutil
R=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation');sys.path.insert(0,str(R/'scripts'))
from handover_checks import sha
PAYLOAD=json.loads(Path('/private/tmp/finance_handover_outputs.json').read_text())
v=json.loads((R/'handover/verification.json').read_text())
assert v['exit_code']==PAYLOAD['exit_code']==2
def write_new(name,text):
 p=R/name;p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists(),name;p.write_text(text)
write_new('handover/verification-output.txt',PAYLOAD['final_output'])
write_new('handover/verification-initial-output.txt',PAYLOAD['initial_output'])
manifest_path=R/'handover/manifest.json';shutil.copyfile(manifest_path,R/'handover/manifest.pre-verification.json')
m=json.loads(manifest_path.read_text());m['generated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
external_versions={'node_bundled':{'path':'/Users/fionama/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node','version':'v24.19.0','probe_exit_code':0},'ffmpeg':{'path':'/opt/homebrew/bin/ffmpeg','version':'8.1','probe_exit_code':0},'yt-dlp':{'path':'/Users/fionama/.local/bin/yt-dlp','version':'2026.07.04','probe_exit_code':0}}
m['runtime_versions']['external_runtime_version_probe']=external_versions
m['test_commands_results']=[{'command':'sh scripts/verify_handover.sh','attempt':'initial','exit_code':1,'counts':{'PASS':6,'FAIL':9,'UNKNOWN':3},'evidence':'handover/verification-initial.json','note':'Verifier distribution-name normalization error; installed sherpa_onnx misread as missing sherpa-onnx. Preserved before correction.'},{'command':'sh scripts/verify_handover.sh','attempt':'final','exit_code':v['exit_code'],'counts':v['counts'],'evidence':'handover/verification.json','output':'handover/verification-output.txt'},{'command':v['safe_test_command'],'exit_code':v['safe_tests_exit_code'],'tests_run':8,'result':'PASS','evidence':'verification.json checks.artifact_unit_tests.detail.output'}]
m['verification_report_sha256']=sha(R/'handover/verification.json')
m['verification_scope']='Frozen handover integrity; static audit findings apply to files whose migration hashes were rechecked. Not an E2E acceptance suite for future implementations.'
m.update(migration_result='PASS',migration_files=81389,migration_symlinks=129,migration_bytes=13557049648)
manifest_path.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
rt=json.loads((R/'handover/runtime-versions.json').read_text());rt['external_runtime_version_probe']=external_versions
(R/'handover/runtime-versions.json').write_text(json.dumps(rt,ensure_ascii=False,indent=2)+'\n')
inputs=[]
cm=json.loads((R/'data/corpus_manifest.json').read_text())
for p in cm['inputs']:
 path=Path(p['path']);inputs.append({'path':str(path),'purpose':'Historical provider import; needed only to rerun initial import','exists':path.is_file(),'recorded_sha256':p['sha256'],'current_sha256':sha(path) if path.is_file() else None,'moved':False,'modified':False})
cat=json.loads((R/'evidence_loop/catalog.json').read_text());path=Path(cat['source_path'])
inputs.append({'path':str(path),'purpose':'Candidate workbook; allowed columns only, never subjective appraisal','exists':path.is_file(),'recorded_sha256':cat['source_sha256'],'current_sha256':sha(path) if path.is_file() else None,'moved':False,'modified':False})
inputs.append({'path':'/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Stocks_KOL/.env','purpose':'Authorized RapidAPI input for resumed work; outside this project','contents_read_in_handover':False,'moved':False,'modified':False,'sha256':None})
inputs.append({'path':'/Users/fionama/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_65o7zhuwdhkq22_f8f0/msg/file/2026-09/Reads 2.zip','purpose':'User original cold-library input; prior audit retained in historical_workspace','moved':False,'modified':False,'current_sha256':None})
write_new('handover/external-inputs.json',json.dumps({'inputs':inputs,'global_dependencies':'Global skills, bundled Node, ffmpeg and yt-dlp remain system dependencies; not project-owned files.','input_contents_not_copied_to_public_services':True},ensure_ascii=False,indent=2)+'\n')
for name in ['finance_distillation_migrate.py','build_finance_handover.py','finance_handover_docs.py','finance_handover_finish_docs.py','finance_handover_outputs.json']:
 src=Path('/private/tmp')/name
 if src.exists():
  dst=R/'handover/build-tools'/name;dst.parent.mkdir(exist_ok=True);assert not dst.exists();src.rename(dst)
write_new('handover/build-tools/README.md','# 交接构建记录\n\n这些脚本记录本次迁移和交接，包含本机旧绝对路径。不是产品入口，不要重跑；目标存在时会拒绝覆盖。业务失败记录没有被改写。核验使用 scripts/verify_handover.sh。\n')
summary='''# 最终交接报告

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
'''+PAYLOAD['final_output'].rstrip()+'''\n```

完整 JSON 在 verification.json，纯文本在 verification-output.txt，迁移逐文件清单在 migration.json。核验脚本只写 verification.json，不下载、不联网、不调用模型、不改业务文件。产品失败项基于静态代码审计和已复核的冻结hash，不是未来新实现的E2E验收套件；恢复开发需要新的验收测试和运行版本。

## Claude Code 前三个动作

1. 读 CLAUDE.md、CURRENT_STATE_AUDIT、KNOWN_FAILURES，核验冻结状态，保留全部失败和旧稿隔离；确认用户恢复实施再写产品代码。
2. 修复旧稿接口/训练/评估旁路、完整事实包和表格审核、计划JSON截断/中断恢复。先用一个新run证明 source→donor→profile→retrieval→独立plan→draft→逐句证据→评估，再运行同证据五组实验。
3. 补足真实donor与300人工标注、3 Bili ASR/说话人/校正；用五名KOL同热点与10来源Evergreen完成图谱、三persona、自动证据更新和前端回放，不缩减原验收。

## 创建和修改范围

以下为交接文件清单。除用户授权的迁移、兼容链接和停止本项目进程，交接未改业务源码、语料、旧输出或模型记录。新增核验器/交接报告的修订不属于业务修改。原任务书副本和SHA在 requirements；旧报告没有被本次报告覆盖。
'''
write_new('handover/REPORT.md',summary)
selfpath=Path('/private/tmp/finance_handover_finalize.py')
if selfpath.exists():selfpath.rename(R/'handover/build-tools/finance_handover_finalize.py')
created=[]
for base in [R/'handover',R/'docs']:
 for p in base.rglob('*'):
  if p.is_file():created.append(str(p.relative_to(R)))
created+=['CLAUDE.md','scripts/handover_checks.py','scripts/verify_handover.py','scripts/verify_handover.sh','handover/deliverables.json'];created=sorted(set(created))
p=R/'handover/REPORT.md';p.write_text(p.read_text()+'\n'+'\n'.join('- `'+n+'`' for n in created)+'\n')
inventory={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository_root':str(R),'new_handover_files':[{'path':n,'bytes':(R/n).stat().st_size,'sha256':sha(R/n)} for n in created if n!='handover/deliverables.json'],'excluded_self':'handover/deliverables.json','business_files_modified_during_handover':[],'migration_original_inventory':'handover/migration.json','final_verification_exit_code':v['exit_code']}
(R/'handover/deliverables.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'repository_root':str(R),'handover_files':len(created),'final_verification_exit_code':v['exit_code'],'report':'handover/REPORT.md','entry':'CLAUDE.md','migration_result':'PASS'},ensure_ascii=False))
