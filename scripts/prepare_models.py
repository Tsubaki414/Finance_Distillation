from pathlib import Path
import os,json,datetime
ROOT=Path(__file__).resolve().parents[1]
os.environ['HF_HOME']=str(ROOT/'.runtime/hf-cache')
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_XET']='1'
from huggingface_hub import HfApi,snapshot_download

models=[('generator','mlx-community/Qwen2.5-1.5B-Instruct-4bit'),('embedding','sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')]
records=[]
for role,repo in models:
    info=HfApi(token=False).model_info(repo)
    dest=ROOT/'.runtime/models'/role
    snapshot_download(repo_id=repo,revision=info.sha,local_dir=dest,token=False,
        allow_patterns=['*.json','*.safetensors','*.model','*.txt','README.md'],
        ignore_patterns=['onnx/*','openvino/*'],max_workers=3)
    files=[p for p in dest.rglob('*') if p.is_file() and '.cache' not in p.parts]
    records.append({'role':role,'repo':repo,'revision':info.sha,'local_path':str(dest.relative_to(ROOT)),
                    'bytes':sum(p.stat().st_size for p in files),'file_count':len(files),'remote_code':False,'inference_only':True})
    print(json.dumps(records[-1]),flush=True)
(ROOT/'model-lock.json').write_text(json.dumps({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'models':records},indent=2))
