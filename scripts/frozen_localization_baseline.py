"""Run the saved production code in a separate interpreter for an honest shadow.

Uses the same configured relay and budget module. No copied credentials, queue,
corpus or account writes. Input source is passed on stdin, never in shell text.
"""
import json
from pathlib import Path
import subprocess
import sys
import re


def run(source,directory,code_root,project_root):
    directory=Path(directory).resolve();code_root=Path(code_root).resolve();project_root=Path(project_root).resolve()
    if not (code_root/'live/distillation.py').is_file():raise ValueError('Missing frozen baseline code')
    script='''
import json,sys
from pathlib import Path
code_root,project_root,directory=map(Path,sys.argv[1:])
sys.path.insert(0,str(project_root));sys.path.insert(0,str(code_root))
from live.distillation import Pipeline,export
from live import writer_backend
writer_backend.ROOT=project_root
result=Pipeline(directory/'artifacts').run(json.loads(sys.stdin.read()))
export(result,directory)
'''
    subprocess.run([sys.executable,'-B','-c',script,str(code_root),str(project_root),str(directory)],
                   input=json.dumps(source,ensure_ascii=False),text=True,check=True)
    result=json.loads((directory/'metadata.json').read_text())
    # The frozen version predates typed quota failures. Read its actual saved
    # transport errors to stop this shadow too; never rewrite the old attempt.
    failed=[json.loads(p.read_text()) for p in (directory/'artifacts/calls').glob('*.json')]
    if any(c.get('status')=='failed' and re.search(r'额度不足|预扣费额度失败|insufficient[_ ]quota|insufficient.*(?:balance|credit)',c.get('error',''),re.I) for c in failed):
        result['external_block']='provider_quota'
        (directory/'baseline_external_block.json').write_text(json.dumps({'reason':'provider_quota','derived_from':'saved baseline call errors'}))
    return result
