from pathlib import Path
import os, json, hashlib, datetime, subprocess, time, signal
workspace=Path('/Users/fionama/Documents/Codex/2026-09-06/new-chat')
src=workspace/'outputs/vertical-slice'
dst=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Distillation')
assert src.is_dir() and not src.is_symlink()
assert dst.is_dir() and not any(dst.iterdir()), 'Target must be empty; refusing overwrite'
assert not (src/'historical_workspace').exists()
command=subprocess.run(['ps','-p','64057','-o','command='],capture_output=True,text=True).stdout.strip()
if command:
    assert command=='.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8680', 'PID identity changed'
    os.kill(64057,signal.SIGTERM)
    for _ in range(50):
        if not subprocess.run(['ps','-p','64057','-o','pid='],capture_output=True,text=True).stdout.strip():break
        time.sleep(.1)
    else:raise RuntimeError('Backend did not stop; no files moved')
print('Project backend stopped; building complete SHA-256 inventory.',flush=True)
entries=[]
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def inventory(base,prefix):
    for current,dirs,files in os.walk(base,followlinks=False):
        for name in list(dirs)+files:
            p=Path(current)/name;relative=p.relative_to(base);target=str(Path(prefix)/relative)
            if p.is_symlink():
                entries.append({'source':str(p),'destination_relative':target,'kind':'symlink','link_target':os.readlink(p)})
            elif p.is_file():
                s=p.stat();entries.append({'source':str(p),'destination_relative':target,'kind':'file','bytes':s.st_size,'sha256':digest(p),'inode':s.st_ino,'device':s.st_dev})
inventory(src,'')
for p in workspace.iterdir():
    if p.name=='outputs':continue
    if p.is_dir():inventory(p,'historical_workspace/'+p.name)
    elif p.is_file():entries.append({'source':str(p),'destination_relative':'historical_workspace/'+p.name,'kind':'file','bytes':p.stat().st_size,'sha256':digest(p),'inode':p.stat().st_ino,'device':p.stat().st_dev})
for p in (workspace/'outputs').iterdir():
    if p==src:continue
    if p.is_dir():inventory(p,'historical_workspace/outputs/'+p.name)
    elif p.is_file():entries.append({'source':str(p),'destination_relative':'historical_workspace/outputs/'+p.name,'kind':'file','bytes':p.stat().st_size,'sha256':digest(p),'inode':p.stat().st_ino,'device':p.stat().st_dev})
print('Inventoried '+str(len(entries))+' files and symlinks. Moving without overwrites.',flush=True)
for p in list(src.iterdir()):p.rename(dst/p.name)
src.rmdir();src.symlink_to(dst,target_is_directory=True)
archive=dst/'historical_workspace';archive.mkdir();(archive/'outputs').mkdir()
for p in list(workspace.iterdir()):
    if p.name=='outputs':continue
    t=archive/p.name;p.rename(t);p.symlink_to(t,target_is_directory=t.is_dir())
for p in list((workspace/'outputs').iterdir()):
    if p==src:continue
    t=archive/'outputs'/p.name;p.rename(t);p.symlink_to(t,target_is_directory=t.is_dir())
print('Move complete; checking every file hash and every symlink.',flush=True)
failures=[]
for e in entries:
    p=dst/e['destination_relative']
    if e['kind']=='symlink':ok=p.is_symlink() and os.readlink(p)==e['link_target']
    else:ok=p.is_file() and p.stat().st_size==e['bytes'] and digest(p)==e['sha256']
    if not ok:failures.append(e['destination_relative'])
handover=dst/'handover';handover.mkdir(exist_ok=True)
report={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_workspace':str(workspace),'original_project_root':str(src),'repository_root':str(dst),'method':'same-volume rename; old entry paths retained only as compatibility symlinks','original_input_projects_moved':False,'backend_stopped_pid':64057,'entries':entries,'regular_files':sum(e['kind']=='file' for e in entries),'symlinks':sum(e['kind']=='symlink' for e in entries),'bytes':sum(e.get('bytes',0) for e in entries),'hash_mismatches':failures,'result':'PASS' if not failures else 'FAIL'}
(handover/'migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['repository_root','regular_files','symlinks','bytes','hash_mismatches','result']},ensure_ascii=False),flush=True)
raise SystemExit(0 if not failures else 1)
