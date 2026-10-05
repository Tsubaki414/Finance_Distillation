"""Daily, isolated source gathering and incremental, budgeted ingestion."""
from __future__ import annotations
import fcntl
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def bounded_fetch(fetch, timeout):
    result = queue.Queue()
    def worker():
        try: result.put((True, fetch()))
        except Exception as exc: result.put((False, exc))
    # Daemon workers never hold up exit and have no access to the store or ledger.
    threading.Thread(target=worker, daemon=True).start()
    try: ok, value = result.get(timeout=timeout)
    except queue.Empty: raise TimeoutError('channel wall-clock cap exceeded')
    if not ok: raise value
    return value


DEFAULT_TIMEOUTS={'podcast:':900}
DEFAULT_EXTRACT_MODEL='claude-opus-5'
# List prices per 1M tokens (input, output) for the ledger when extract runs on a non-default relay model.
EXTRACT_MODEL_RATES={'claude-sonnet-5':(3.0,15.0)}


def _relay_config():
    from live.erisedai_distillation_client import relay_config
    return relay_config()


def extract_client(directory, *, model=None, allow_nondefault=False):
    """Relay client for EXTRACT. The validated default is claude-opus-5; another model needs allow_nondefault=True
    (CLI: --extract-model M --allow-nondefault-extract-model) and only overrides the extract stage."""
    import copy
    from live import stage_models
    from live.erisedai_distillation_client import ErisedaiClient, PROVIDER
    from ml import budget
    cfg=_relay_config()
    if model and model!=DEFAULT_EXTRACT_MODEL:
        if not allow_nondefault:
            raise ValueError(f'extract model {model} is not the validated default; pass allow_nondefault (--allow-nondefault-extract-model)')
        table=copy.deepcopy(stage_models.load())
        table['stages']=dict(table.get('stages') or {},extract={'model':model,'temperature':0.0})
        table['accepted_response_models'][model]=[model,'anthropic/'+model]
        cfg['stage_models']=table
    client=ErisedaiClient(directory,configuration=cfg)
    if model in EXTRACT_MODEL_RATES:
        budget.PRICES[PROVIDER+'/'+model]=EXTRACT_MODEL_RATES[model]
    return client



def known_urls(store, state):
    """Membership test for source URLs/ids already in the store or seen by any channel."""
    seen=set()
    path=Path(store)/'units.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                src=json.loads(line).get('source') or {}
                seen.update(v for v in (src.get('url'),src.get('id')) if v)
    for entry in (state.get('channels') or {}).values():
        seen.update(entry.get('seen') or [])
    return seen.__contains__


def default_fetchers(state, store=ROOT/'live/store/content_units'):
    from scripts import run_content_adapters as adapters
    from live.adapters import channels, edgar, feeds, fred
    from live import registry
    names = ['fed','fomc','bls','treasury','fred','nyfed','cftc','cboe','options_flow','farside',
             'defillama','glassnode','oaktree','wallstreetcn']
    def gather(name):
        args = SimpleNamespace(adapters=[name], tickers=[], newsletter_extract=999,
                               wscn_n=10, rss_n=2, channel_limit=3)
        text, data = adapters.gather(args, {'adapters':{}})
        return {'sources':text, 'batches':data}
    fetchers = {name:lambda name=name:gather(name) for name in names}
    fetchers['fred'] = lambda:fred.fetch_series('UNRATE')
    for ticker in dict.fromkeys(['MU','NVDA'] + adapters.MEGACAP):
        cid = 'edgar:'+ticker
        last = state.get('channels',{}).get(cid,{}).get('last_run')
        fetchers[cid] = lambda ticker=ticker,last=last: edgar.fetch(
            ticker, forms=('8-K','10-Q','10-K'), earnings_only=False, limit=100,
            max_age_days=None if last else 10, since=last)
    for ch in channels.select_channels(channels.load_channels(ROOT/'live/channels.json'), modes=channels.DEFAULT_MODES):
        if registry.source_licence_tier(ch['channel_id']) in ('A','B'):
            fetchers[ch['channel_id']] = lambda ch=ch:channels.fetch_channel(ch,limit=3)
    for feed in adapters.newsletter_feeds():
        if registry.source_licence_tier(feed['id']) in ('A','B'):
            prefix='rss_fulltext' if feed['id'] in adapters.RSS_FULLTEXT else 'newsletters'
            fetchers[prefix+':'+feed['id']] = lambda feed=feed:feeds.fetch_newsletter(feed,limit=2)
    from live.adapters import podcast_local
    known=known_urls(store,state)
    for ch in channels.load_channels(ROOT/'live/channels.json'):
        if ch['mode']=='podcast_audio' and registry.source_licence_tier(ch['channel_id']) in ('A','B'):
            fetchers['podcast:'+ch['channel_id']] = lambda ch=ch: podcast_local.fetch(ch,limit=1,known=known)
    return fetchers


def trim_source(source, max_chars):
    """Cut long text at a paragraph boundary before EXTRACT (keeps daily spend per source bounded)."""
    text=source.get('original_text') or ''
    if not max_chars or len(text)<=max_chars: return source
    from live.adapters.common import digest, paragraphs
    kept=[p for p in paragraphs(text) if p['end']<=max_chars]
    text=text[:kept[-1]['end']] if kept else text[:max_chars]
    return dict(source, original_text=text, source_hash=digest(text), truncated=True)


def priority(channel, source):
    ids=channel+' '+str(source.get('source_id',''))
    if any(x in ids for x in ('cftc','cboe','ch096','ch095','ch094','ch093')): return 0
    if 'wallstreetcn' in ids or source.get('source_language')=='zh' or any(x in ids for x in ('ch008','ch001')): return 1
    if any(x in ids for x in ('edgar','ch021','ch019')): return 2
    return 3


def run(*, store=ROOT/'live/store/content_units', runs_dir='/workspace/x/ingest_runs',
        inbox='/workspace/x/ingest_inbox', cost_cap_usd=8.0, channel_timeout=90, channel_timeouts=None,
        max_extract=40, max_source_chars=5000, extract_model=None, allow_nondefault_extract_model=False, per_channel_max=2, no_dashboard=False, dry_run=False, only=None,
        fetchers=None, extract=None, jev=None, backup=None, refresh=None, state_path=None):
    from ml import budget
    from live import content_store, jev_front, registry
    from scripts.run_content_adapters import filter_known, ingest_batches
    store, runs_dir, inbox = Path(store),Path(runs_dir),Path(inbox)
    state_path=Path(state_path) if state_path else store.parent/'ingest_state.json'
    runs_dir.mkdir(parents=True,exist_ok=True)
    started=datetime.now(timezone.utc); clock=time.monotonic()
    summary=dict(status='ok',started_at=started.isoformat(),steps=[],channels=[],
                 new_units_by_persona={},fresh_by_persona_before={},fresh_by_persona_after={},
                 cost_usd=dict(relay=0,jev=0,total=0,cap=cost_cap_usd),failing_channels=[],deferred=[])
    lock=(runs_dir/'daily_ingest.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        summary.update(status='locked',finished_at=datetime.now(timezone.utc).isoformat(),runtime_s=0)
        return summary
    old_budget=budget.STORE,budget.LEDGER,budget.DISTILLATION_RUNS
    ledger=None
    def step(name, action):
        t=time.monotonic()
        try:
            action(); entry=dict(id=name,status='ok',error=None)
        except Exception as exc: entry=dict(id=name,status='failed',error=f'{type(exc).__name__}: {exc}')
        entry['seconds']=time.monotonic()-t; summary['steps'].append(entry)
        return entry['status']=='ok'
    def command(*args, **kwargs): subprocess.run(args,check=True,**kwargs)
    def fresh_counts():
        from scripts.freshness_report import build_report
        if not (store/'units.jsonl').exists(): return {}
        return {p:c['fresh'] for p,c in build_report(store)['personas'].items()}
    try:
        if not step('backup',backup or (lambda:command(sys.executable,str(ROOT/'scripts/backup_live.py')))):
            summary['status']='backup_failed'; return summary
        summary['fresh_by_persona_before']=fresh_counts()
        state=json.loads(state_path.read_text()) if state_path.exists() else {'channels':{}}
        fs=default_fetchers(state,store) if fetchers is None else fetchers
        if only:
            fs={k:v for k,v in fs.items() if k in only or k.split(':')[0] in only or ('channels' in only and k.startswith('ch'))}
        tasks=[]
        for cid,fetch in fs.items():
            t=time.monotonic(); ch=dict(id=cid,status='ok',new_items=0,units=0,seconds=0,error=None)
            summary['channels'].append(ch)
            try:
                limit=next((v for k,v in (channel_timeouts or DEFAULT_TIMEOUTS).items() if cid.startswith(k)),channel_timeout)
                out=bounded_fetch(fetch,limit)
                ch['status']=out.get('status','ok')
                batches=out.get('batches',[])
                sources=out.get('sources',[])
                if out.get('units'):
                    batches += [(s,[u for u in out['units'] if u.get('source_hash')==s['source_hash']],s['adapter']) for s in sources]
                    sources=[]
                seen=set(state['channels'].get(cid,{}).get('seen',[]))
                failed=state['channels'].get(cid,{}).get('failed',{})
                rank=0
                for s,units,adapter in [(s,None,s.get('adapter',cid)) for s in sources]+list(batches):
                    keys=[str(s.get(k)) for k in ('id','url','source_hash') if s.get(k)]
                    if seen.intersection(keys) or not filter_known([s],store)[0]: continue
                    if any(failed.get(k,0)>=2 for k in keys): continue
                    if units is None and per_channel_max and rank>=per_channel_max: continue
                    ch['new_items']+=1; tasks.append((ch,s,units,adapter,keys,rank)); rank+=1
            except Exception as exc:
                ch.update(status='timeout' if isinstance(exc,TimeoutError) else 'failed',error=f'{type(exc).__name__}: {exc}')
                summary['failing_channels'].append(cid)
            ch['seconds']=time.monotonic()-t
            print(f"[gather] {cid} {ch['status']} new={ch['new_items']} {ch['seconds']:.0f}s",file=sys.stderr,flush=True)
        summary['steps'].append(dict(id='gather',status='ok'))
        summary['steps'].append(dict(id='incremental',status='ok',new_items=len(tasks)))
        if dry_run: summary['status']='dry_run'; return summary
        budget.STORE=runs_dir/(started.strftime('%Y%m%d')+'-'+uuid.uuid4().hex)/'ledger'
        budget.LEDGER=budget.STORE/'spend.json';ledger=budget.LEDGER
        budget.DISTILLATION_RUNS=budget.STORE/'distillation_spend.jsonl'
        atomic_json(ledger,dict(cap_usd=cost_cap_usd,spent_usd=0,calls=0,reservations={}))
        db=content_store.ContentStore(store); before={r['unit_id'] for r in db.units()}
        if extract is None:
            from live.jev_review_client import JevReviewClient
            from live import content_units
            client=extract_client(budget.STORE.parent/'extract_calls',model=extract_model,allow_nondefault=allow_nondefault_extract_model)
            summary['extract_model']=extract_model or DEFAULT_EXTRACT_MODEL
            jev=jev or JevReviewClient(budget.STORE.parent/'jev_calls')
            def extract(s):
                return content_units.extract(s,client,licence_tier=registry.source_licence_tier(s['source_id']),publisher=s.get('publisher'))['units']
        if jev is not None:
            delegate = jev
            class CappedJev:
                def review(self, state, questions):
                    result = delegate.review(state, questions)
                    if result.get('error_code') == 'budget_exceeded':
                        raise budget.BudgetExceeded('Jev estimate exceeds daily cap')
                    return result
            jev = CappedJev()
        capped=False; extracted=0
        for ch,s,units,adapter,keys,rank in sorted(tasks,key=lambda task:(priority(task[0]['id'],task[1]),task[5])):
            t=time.monotonic()
            if capped or (units is None and extracted>=max_extract):
                reason='deferred_cost_cap' if capped else 'deferred_max_extract'
                ch['status']=reason; summary['deferred'].append(dict(id=s['id'],channel=ch['id'],status=reason));continue
            try:
                if units is None:
                    s=trim_source(s,max_source_chars); extracted+=1
                    try: units=extract(s)
                    except budget.BudgetExceeded: raise
                    except Exception as exc:
                        # Output hit the token ceiling: one retry on half the text (EXTRACT output scales with input).
                        if 'finish_reason' not in str(exc) or len(s.get('original_text') or '')<1200: raise
                        s=trim_source(s,len(s['original_text'])//2); units=extract(s)
                routing=jev_front.route_sources([dict(id=s['id'],title=s.get('title') or '',publisher=s.get('publisher'),snippet=s.get('original_text','')[:400])],jev=jev)
                result=ingest_batches(db,[(s,units,adapter)],routing,jev=jev)
                ch['units']+=result['added']
                entry=state['channels'].setdefault(ch['id'],{'seen':[]})
                entry['seen']=list(set(entry['seen'])|set(keys))
            except budget.BudgetExceeded:
                capped=True;ch['status']='deferred_cost_cap'
                summary['deferred'].append(dict(id=s['id'],channel=ch['id'],status='deferred_cost_cap'))
            except Exception as exc:
                ch.update(status='failed',error=f'{type(exc).__name__}: {exc}')
                fails=state['channels'].setdefault(ch['id'],{'seen':[]}).setdefault('failed',{})
                for k in keys: fails[k]=fails.get(k,0)+1
                if ch['id'] not in summary['failing_channels']:summary['failing_channels'].append(ch['id'])
            ch['seconds']+=time.monotonic()-t
            print(f"[extract] {ch['id']} {s['id']} {ch['status']} units={ch['units']}",file=sys.stderr,flush=True)
        summary['steps'].append(dict(id='extract',status='ok',extracted=extracted,deferred=len(summary['deferred'])))
        for ch in summary['channels']:
            if ch['status']=='ok':state['channels'].setdefault(ch['id'],{'seen':[]})['last_run']=started.isoformat()
        atomic_json(state_path,state)
        def ingest_inbox():
            if only and 'reportgem' not in only: return
            for path in sorted((inbox/'reportgem').glob('*.json')):
                payload=json.loads(path.read_text());items=payload if isinstance(payload,list) else [payload]
                for item in items:
                    s=item['source'];ingest_batches(db,[(s,item['units'],'reportgem_daily')],{},jev=jev)
                processed=path.parent/'processed';processed.mkdir(exist_ok=True)
                target=processed/path.name
                if target.exists():target=processed/(path.stem+'-'+uuid.uuid4().hex+'.json')
                path.replace(target)
        step('inbox',ingest_inbox)
        from scripts.dedup_store import dedup_store
        from scripts.backfill_freshness import backfill
        step('dedup',lambda:dedup_store(store))
        step('freshness',lambda:backfill(store,write=True))
        rows=content_store.ContentStore(store).units()
        summary['new_units_by_persona']=dict(Counter(p for r in rows if r['unit_id'] not in before for p in (r.get('tag_personas') or r['personas'])))
        summary['fresh_by_persona_after']=fresh_counts()
        step('refresh',refresh or (lambda:command(sys.executable,str(ROOT/'scripts/freshness_report.py'),'--store',str(store),'--out-json','/workspace/x/fd_freshness_report.json','--out-md','/workspace/x/fd_freshness_report.md')))
        if not no_dashboard:
            step('dashboard',lambda:(command('/usr/bin/python3','build_dashboard.py',cwd='/workspace/x/dashboard'),command('/usr/bin/python3','shot.py',cwd='/workspace/x/dashboard')))
        return summary
    except Exception as exc:
        summary['status']='failed'
        summary['steps'].append(dict(id='runner',status='failed',error=f'{type(exc).__name__}: {exc}'))
        return summary
    finally:
        if ledger and ledger.exists():
            data=json.loads(ledger.read_text());reservations=data.get('reservations',{})
            jev_cost=sum(v.get('cost',v.get('estimate',0)) for v in reservations.values() if str(v.get('model','')).startswith('typesafe/'))
            total=data.get('spent_usd',0)
            summary['cost_usd'].update(total=total,jev=jev_cost,relay=total-jev_cost)
        budget.STORE,budget.LEDGER,budget.DISTILLATION_RUNS=old_budget
        summary.update(finished_at=datetime.now(timezone.utc).isoformat(),runtime_s=time.monotonic()-clock)
        atomic_json(runs_dir/(started.strftime('%Y%m%d')+'.json'),summary)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
