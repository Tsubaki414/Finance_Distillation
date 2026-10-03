"""Freeze a balanced recent *existing* intake window; no collection or queue writes."""
import argparse
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from live.distillation_source import digest,now

def freeze(rows,end,hours,per_source):
    start=end-timedelta(hours=hours);by_source={};invalid_dates=0
    for row in rows:
        stamp=row.get('published_at')
        try:date=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        except (AttributeError,ValueError):
            try:date=parsedate_to_datetime(stamp)
            except (AttributeError,ValueError,TypeError):invalid_dates+=1;continue
        if date.tzinfo is None:invalid_dates+=1;continue
        if not start<=date<=end:continue
        key=row.get('source_id') or row.get('author_id') or row.get('author_name') or row.get('url')
        by_source.setdefault(key,[]).append((date,row))
    selected=[];seen=set()
    for key in sorted(by_source,key=str):
        count=0
        for date,row in sorted(by_source[key],key=lambda r:r[0],reverse=True):
            body=row.get('original_text',row.get('text',''));h=digest(body)
            if not body or h in seen:continue
            seen.add(h);selected.append({'case':'intake-'+h[:16],'source':row,'split':'prospective_shadow','human_labels':None})
            count+=1
            if count>=per_source:break
    return {'frozen_at':now(),'window_start':start.isoformat(),'window_end':end.isoformat(),
            'per_source':per_source,'rows_with_unusable_dates':invalid_dates,
            'selection':'recent existing intake only; no quality filtering','cases':selected}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=ROOT/'live/store/analysis_corpus.jsonl')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--until',required=True)
    p.add_argument('--hours',type=float,default=24);p.add_argument('--per-source',type=int,default=2);a=p.parse_args()
    end=datetime.fromisoformat(a.until.replace('Z','+00:00'))
    if end.tzinfo is None or a.hours<=0 or a.per_source<=0:p.error('Timezone and positive window/limit required')
    raw=a.input.read_text();rows=[json.loads(s) for s in raw.split('\n') if s.strip()]
    result=freeze(rows,end,a.hours,a.per_source);result.update(input_ref=str(a.input),input_hash=digest(raw))
    with a.out.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'cases':len(result['cases']),'out':str(a.out),'input_unchanged':digest(a.input.read_text())==result['input_hash']}))

if __name__=='__main__':main()
