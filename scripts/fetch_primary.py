from pathlib import Path
import json,datetime,hashlib,re,time
import httpx
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
SOURCES={
 'bls-july':'https://www.bls.gov/news.release/archives/empsit_08072026.htm',
 'bls-august':'https://www.bls.gov/news.release/empsit.nr0.htm',
 'bls-calendar':'https://www.bls.gov/schedule/2026/09_sched.htm'}
out=ROOT/'data/evidence';out.mkdir(parents=True,exist_ok=True)
for key,url in SOURCES.items():
 started=datetime.datetime.now(datetime.timezone.utc).isoformat();timer=time.monotonic()
 try:
  response=httpx.get(url,timeout=35,follow_redirects=True,headers={'User-Agent':'FinancialPersonaResearch/0.1 public data research'})
  response.raise_for_status();body=response.content;digest=hashlib.sha256(body).hexdigest()
  soup=BeautifulSoup(body,'html.parser');pre=soup.find('pre')
  text=pre.get_text(' ',strip=False) if pre else soup.get_text(' ',strip=True)
  (out/(key+'-'+digest[:12]+'.html')).write_bytes(body)
  record={'evidence_id':key+'-'+digest[:12],'source_key':key,'url':url,'observed_at':started,'raw_sha256':digest,'raw_path':key+'-'+digest[:12]+'.html','text':text,'primary_source':True,'publisher':'U.S. Bureau of Labor Statistics','rights_status':'public_government_release','transport':'httpx','http_status':response.status_code}
  (out/(key+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
  ledger={'operation':'primary_public_source_fetch','url':url,'started_at':started,'status':response.status_code,'bytes':len(body),'sha256':digest,'duration_seconds':round(time.monotonic()-timer,2),'paid_api':False}
 except Exception as e:ledger={'operation':'primary_public_source_fetch','url':url,'started_at':started,'status':'failed','error_type':type(e).__name__,'paid_api':False}
 with (ROOT/'runs/api_run_ledger.jsonl').open('a') as f:f.write(json.dumps(ledger)+'\n')
 print(json.dumps(ledger),flush=True)
