"""Start only this project's localhost services; reuse healthy instances, never kill others."""
from pathlib import Path
import os,sys,subprocess,time,signal,json
import httpx
ROOT=Path(__file__).resolve().parents[1]
owned=[]
def request(port,path):
    try:
        with httpx.Client(trust_env=False,timeout=2) as c:
            response=c.get(f'http://127.0.0.1:{port}{path}');response.raise_for_status();return response.json()
    except Exception:return None
def spawn(args,log_name,env):
    log=(ROOT/'runs'/log_name).open('a');p=subprocess.Popen([sys.executable,*args],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);owned.append((p,log));return p
def wait_for(port,path,process,timeout):
    for _ in range(timeout):
        result=request(port,path)
        if result is not None:return result
        if process.poll() is not None:raise RuntimeError(f'Local service failed; inspect runs/start-{port}.log. No other process was stopped.')
        time.sleep(1)
    raise RuntimeError(f'Local service readiness timed out on {port}')
def stop(*_):
    for p,log in owned:
        if p.poll() is None:p.terminate()
    for p,log in owned:
        try:p.wait(timeout=10)
        except subprocess.TimeoutExpired:pass
        log.close()
    sys.exit(0)
def main():
    env=dict(os.environ);env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',MLX_METAL_GPU_ARCH='applegpu_g16g')
    config=json.loads((ROOT/'active-generator.json').read_text()) if (ROOT/'active-generator.json').exists() else {'model_role':'comparison'}
    role=config['model_role']
    if role not in ['comparison','modern']:raise RuntimeError('Unknown active model role')
    port=8683 if role=='modern' else 8682
    model=ROOT/'.runtime/models'/role
    if not (model/'config.json').exists():raise RuntimeError('Pinned local model missing. No automatic download or paid fallback is performed.')
    models=request(port,'/health')
    if models is not None and models!={'status':'ok'}:raise RuntimeError('Unexpected model service; nothing changed')
    if models is None:
        if any(request(other,'/health') for other in [8681,8682,8683] if other!=port):raise RuntimeError('Another task model is running. To avoid memory pressure this launcher does not start two models or stop an existing one.')
        args=['-m','mlx_lm','server','--model',str(model),'--host','127.0.0.1','--port',str(port),'--allowed-origins','http://127.0.0.1:8680','--max-tokens','1200','--decode-concurrency','1','--prompt-cache-size','1','--prompt-cache-bytes','600000000']
        if role=='modern':args+=['--chat-template-args','{"enable_thinking":false}']
        p=spawn(args,f'start-{port}.log',env)
        wait_for(port,'/health',p,120)
    status=request(8680,'/api/status')
    if status is not None and status.get('x_collector',{}).get('selected')!='Xquik':raise RuntimeError('Unexpected service on 8680; nothing changed')
    if status is None:
        p=spawn(['-m','uvicorn','app:app','--app-dir',str(ROOT/'backend'),'--host','127.0.0.1','--port','8680'],'start-8680.log',env);wait_for(8680,'/api/status',p,30)
    print('Open the existing Chrome window at http://127.0.0.1:8680 . X collection and SEC MCP remain disabled pending their required inputs.',flush=True)
    if not owned:
        print('Both local services were already running; no processes changed.');return
    print('Ctrl-C stops only services launched by this command.',flush=True)
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    while all(p.poll() is None for p,_ in owned):time.sleep(1)
    stop()
if __name__=='__main__':main()
