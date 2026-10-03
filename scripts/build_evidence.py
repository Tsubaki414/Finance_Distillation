from pathlib import Path
import json,re,hashlib,datetime
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'data/evidence';records=[]
 for key in ['bls-july','bls-august','bls-calendar']:
  path=out/f'{key}.web-capture.json';d=json.loads(path.read_text());content=d['content']
  lines={int(n):s.strip() for n,s in re.findall(r'L(\d+):\s*(.*?)(?=L\d+:|\Z)',content,re.S)}
  selected={n:s for n,s in lines.items() if (190<=n<=310 if key!='bls-calendar' else 202<=n<=265)}
  record={'id':key,'publisher':'U.S. Bureau of Labor Statistics','url':d['url'],'observed_at':d['observed_at'],'acquisition':'web.run text capture; direct HTTP connector failed','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_lines':selected,'full_document_captured':False}
  records.append(record)
 by={r['id']:r for r in records}
 def fact(fid,value,unit,period,sid,pattern):
  found=[{'line':n,'text':s} for n,s in by[sid]['source_lines'].items() if re.search(pattern,s,re.I)]
  if not found:raise ValueError('Missing source match '+fid)
  return {'id':fid,'value':value,'unit':unit,'period':period,'source_id':sid,'spans':found,'extraction':'rule match plus curator-checked structured value','status':'observed_primary_source'}
 old=[fact('payroll_2026_07',-23000,'persons','2026-07','bls-july',r'July \(-23,000\)'),fact('unemployment',4.1,'percent','2026-07','bls-july',r'unemployment rate.*4.1')]
 new=[fact('payroll_2026_07',21000,'persons','2026-07','bls-august',r'July was revised.*21,000'),fact('payroll_2026_08',162000,'persons','2026-08','bls-august',r'162,000'),fact('unemployment',4.1,'percent','2026-08','bls-august',r'unchanged at 4.1'),fact('payroll_2026_06',31000,'persons','2026-06','bls-august',r'20,000 to \+31,000')]
 snapshots=[{'id':'july-release','published_at':'2026-08-07T08:30:00-04:00','title':'July employment release: historical evidence replay','source_ids':['bls-july'],'facts':old},{'id':'august-release','published_at':'2026-09-04T08:30:00-04:00','title':'August employment release and July revision','source_ids':['bls-august'],'facts':new}]
 calendar=by['bls-calendar'];matches=[{'line':n,'text':s} for n,s in calendar['source_lines'].items() if re.search(r'11 Consumer Price|08:30|All times',s)]
 scheduled={'id':'cpi-2026-09-11','kind':'planned_event','title':'August CPI release','scheduled_at':'2026-09-11T08:30:00-04:00','source_id':'bls-calendar','source_spans':matches,'result':None,'note':'Schedule only; future result is unknown.'}
 (out/'registry.json').write_text(json.dumps({'sources':records,'snapshots':snapshots,'scheduled':[scheduled]},ensure_ascii=False,indent=2))
 print(json.dumps({'sources':len(records),'snapshots':len(snapshots),'facts':len(old)+len(new),'planned_events':1}))
if __name__=='__main__':main()
