from pathlib import Path
import json,datetime,time,hashlib
import yfinance as yf
ROOT=Path(__file__).resolve().parents[1]
def main():
 dest=ROOT/'data/finance_supplement';dest.mkdir(exist_ok=True);yf.set_tz_cache_location(str(ROOT/'.runtime/yfinance-cache'));ticker=yf.Ticker('NVDA');results={};ledger=[]
 for field in ['earnings_history','earnings_estimate','revenue_estimate']:
  started=time.monotonic();row={'provider':'yfinance / Yahoo Finance','ticker':'NVDA','operation':field,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'role':'supplementary consensus; never replaces IR/SEC/call originals','credential_source':'library-owned public Yahoo session; no user credentials or browser cookies','explicit_api_fee':0,'license':'commercial reuse not established'}
  try:
   df=getattr(ticker,field);data=json.loads(df.to_json(orient='table',date_format='iso')) if df is not None else None;row.update(status='completed' if df is not None and len(df) else 'empty',rows=len(df) if df is not None else 0);results[field]={'run':row,'data':data}
  except Exception as e:row.update(status='failed',rows=0,error=type(e).__name__+': '+str(e)[:300]);results[field]={'run':row,'data':None}
  row['duration_seconds']=round(time.monotonic()-started,3);ledger.append(row);print(json.dumps({k:row[k] for k in ['operation','status','rows']}),flush=True)
 (dest/'nvda.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 with (ROOT/'runs/api_run_ledger.jsonl').open('a') as f:
  for row in ledger:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 # A recap must bind a company primary source and comparable GAAP/non-GAAP periods first.
 recap={'ticker':'NVDA','yahoo_rows':{k:v['run']['rows'] for k,v in results.items()},'verified_earnings_recap':None,'reason':'Yahoo rows alone cannot establish the official release, metric basis, timestamp, or call wording. Bind IR/SEC/call originals before producing recap.','price_reaction':None,'reaction_method':'Use first tradable close after verified release vs last pre-release close; never arbitrary +/-5-day endpoints.','estimate_analysis':{'consensus_available':results['earnings_estimate']['run']['rows']>0,'not_a_forecast':True,'zero_or_negative_denominator':'show absolute difference; percentage comparison withheld','thresholds':'No unvalidated bullish/bearish 0.7 heuristic.'}}
 (dest/'earnings-recap-and-estimate-analysis.json').write_text(json.dumps(recap,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
