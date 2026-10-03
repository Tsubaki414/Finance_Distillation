"""Audited local stdio entry. No network until an explicit contact identity exists."""
from pathlib import Path
import os,re,sys,time,threading,logging,json,datetime
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
identity=os.environ.get('SEC_EDGAR_USER_AGENT','')
if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@)]+',identity) or 'example.com' in identity:
    print('SEC MCP disabled: provide a real SEC_EDGAR_USER_AGENT contact identity.',file=sys.stderr)
    sys.exit(2)
os.environ['SEC_EDGAR_TOOLKIT_CACHE_DIR']=str(ROOT/'.runtime/sec-cache')
logging.getLogger('sec_edgar_toolkit').setLevel(logging.WARNING)
import requests
from urllib3.util.retry import Retry
original_send=requests.Session.send
gate=threading.Lock();last=[0.0]
def guarded_send(session,request,**kwargs):
    parsed=urlsplit(request.url)
    if parsed.scheme!='https' or parsed.hostname not in {'www.sec.gov','data.sec.gov','efts.sec.gov'}:raise RuntimeError('SEC network allowlist rejected destination')
    kwargs.update(timeout=30,allow_redirects=False)
    # Disable adapter retries, so every attempted send passes the same throttle.
    session.get_adapter(request.url).max_retries=Retry(total=0)
    request.headers['User-Agent']=identity
    with gate:
        time.sleep(max(0,1.0-(time.monotonic()-last[0])));last[0]=time.monotonic()
        response=original_send(session,request,**kwargs)
    with (ROOT/'runs/api_run_ledger.jsonl').open('a') as f:f.write(json.dumps({'provider':'sec_edgar_mcp','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':parsed.hostname,'path':parsed.path,'status_code':response.status_code,'contact_redacted':True})+'\n')
    if 300<=response.status_code<400:raise RuntimeError('SEC redirect requires endpoint review')
    return response
requests.Session.send=guarded_send
from sec_edgar_mcp.server import main
if __name__=='__main__':main()
