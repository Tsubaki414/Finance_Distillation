from pathlib import Path
import os,json,datetime
ROOT=Path(__file__).resolve().parents[1]
os.environ.update(HF_HOME=str(ROOT/'.runtime/hf-cache'),HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1')
from huggingface_hub import HfApi,snapshot_download
repo='mlx-community/Qwen3.5-4B-MLX-4bit';info=HfApi(token=False).model_info(repo,files_metadata=True)
selected=[f for f in info.siblings if f.rfilename.endswith(('.safetensors','.json','.txt','.model','.jinja')) or f.rfilename=='README.md'];expected=sum(f.size or 0 for f in selected)
if expected>3_500_000_000:raise RuntimeError('Public model exceeds the 3.5GB download bound')
dest=ROOT/'.runtime/models/modern'
snapshot_download(repo,revision=info.sha,local_dir=dest,token=False,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja','README.md'],max_workers=2)
files=[p for p in dest.rglob('*') if p.is_file() and '.cache' not in p.parts]
lock={'role':'modern_generator','repo':repo,'revision':info.sha,'local_path':str(dest.relative_to(ROOT)),'bytes':sum(p.stat().st_size for p in files),'file_count':len(files),'remote_code':False,'inference_only':True,'license':'apache-2.0 per model card','reason':'Observed Qwen2.5-7B consistency and instruction-following failures; evaluate a newer frozen architecture, no training','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'runtime_support':'installed mlx_lm.models.qwen3_5 handles text_config and removes vision weights for text-only inference','thinking_enabled':False}
(ROOT/'modern-model-lock.json').write_text(json.dumps(lock,indent=2));print(json.dumps(lock))
