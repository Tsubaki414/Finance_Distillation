from pathlib import Path
import os,json,datetime
ROOT=Path(__file__).resolve().parents[1]
os.environ.update(HF_HOME=str(ROOT/'.runtime/hf-cache'),HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1')
from huggingface_hub import HfApi,snapshot_download
repo='mlx-community/Qwen2.5-7B-Instruct-4bit';info=HfApi(token=False).model_info(repo,files_metadata=True)
selected=[f for f in info.siblings if f.rfilename.endswith(('.safetensors','.json','.txt','.model')) or f.rfilename=='README.md'];expected=sum(f.size or 0 for f in selected)
if expected>6_000_000_000:raise RuntimeError('Comparison model exceeds the 6GB download bound')
dest=ROOT/'.runtime/models/comparison'
snapshot_download(repo,revision=info.sha,local_dir=dest,token=False,allow_patterns=['*.json','*.safetensors','*.txt','*.model','README.md'],max_workers=2)
files=[p for p in dest.rglob('*') if p.is_file() and '.cache' not in p.parts]
lock={'role':'comparison_generator','repo':repo,'revision':info.sha,'local_path':str(dest.relative_to(ROOT)),'bytes':sum(p.stat().st_size for p in files),'file_count':len(files),'remote_code':False,'inference_only':True,'reason':'Observed 1.5B structured-output and numeric-fidelity failures; model-size inference comparison, no training','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(ROOT/'comparison-model-lock.json').write_text(json.dumps(lock,indent=2));print(json.dumps(lock))
