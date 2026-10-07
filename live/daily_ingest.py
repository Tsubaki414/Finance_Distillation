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
from datetime import datetime, timedelta, timezone
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
# Oct 6 (Fiona): full-article EXTRACT is config-driven - live/stage_models.json "extract" (gemini-3.1-pro-preview on
# micuapi, documented fallback claude-opus-5 on error / no channel / quota / unset key). FD_EXTRACT_MODEL overrides.
LEGACY_EXTRACT_MODEL='claude-opus-5'
# List prices per 1M tokens (input, output) for the ledger when extract runs on a non-default relay model.
EXTRACT_MODEL_RATES={'claude-sonnet-5':(3.0,15.0)}
DEFAULT_EST_USD_PER_DOC=0.83   # opus-era measured average (relay $/extract), used when the stage sets no estimate


def _relay_config():
    from live.erisedai_distillation_client import relay_config
    return relay_config()


def extract_table(environ=None):
    """The stage table EXTRACT runs on (stage_models.json + FD_EXTRACT_* env overrides)."""
    import os
    from live import stage_models
    return stage_models.from_env(stage_models.load(), os.environ if environ is None else environ)


def extract_plan(table=None):
    """{'model','fallback','route_host','est_usd_per_doc'} for the configured EXTRACT stage."""
    from live import stage_models
    table=table or extract_table()
    entry=(table.get('stages') or {}).get('extract') or {}
    fb=stage_models.fallback(table,'extract')
    route=stage_models.route(table,'extract')
    return dict(model=stage_models.for_stage(table,'extract')['model'],fallback=fb['model'] if fb else None,
                route_host=route['base_url'].split('/')[2] if route else None,
                est_usd_per_doc=float(entry.get('est_usd_per_doc') or DEFAULT_EST_USD_PER_DOC),
                fallback_est_usd_per_doc=float(((entry.get('fallback') or {}).get('est_usd_per_doc')) or DEFAULT_EST_USD_PER_DOC))


def validated_extract_models(table=None):
    """Models EXTRACT may run on without the explicit opt-in: the configured primary and its documented fallback."""
    plan=extract_plan(table)
    return {m for m in (plan['model'],plan['fallback'],LEGACY_EXTRACT_MODEL) if m}


def extract_client(directory, *, model=None, allow_nondefault=False):
    """Relay client for EXTRACT. The configured stage (stage_models.json "extract") runs by default. --extract-model M
    pins one model for the extract stage (no route, no fallback): the configured primary / fallback / claude-opus-5
    are validated; another model needs allow_nondefault=True (CLI: --allow-nondefault-extract-model)."""
    from live import stage_models
    from live.erisedai_distillation_client import ErisedaiClient, PROVIDER
    from ml import budget
    cfg=_relay_config()
    table=extract_table()
    plan=extract_plan(table)
    if model and model!=plan['model']:
        if model not in validated_extract_models(table) and not allow_nondefault:
            raise ValueError(f'extract model {model} is not the validated default; pass allow_nondefault (--allow-nondefault-extract-model)')
        table=stage_models.copy_of(table)
        table['stages']=dict(table.get('stages') or {},extract={'model':model,'temperature':0.0})
        table['accepted_response_models'][model]=sorted(set(table['accepted_response_models'].get(model,[]))|{model,'anthropic/'+model})
    cfg['stage_models']=table
    client=ErisedaiClient(directory,configuration=cfg)
    if model in EXTRACT_MODEL_RATES:
        budget.PRICES[PROVIDER+'/'+model]=EXTRACT_MODEL_RATES[model]
    return client


def extract_fit(*, cost_cap_usd, flash_budget_usd, max_extract, extract_model=None, injected=False, est_usd_per_doc=None):
    """Paid document extracts expected to fit: min(max_extract, docs budget // est $/doc) (persona_minimum window).

    est comes from stage_models.json "extract" (the pinned model's / fallback's estimate for --extract-model);
    injected extract (tests) uses DEFAULT_EST_USD_PER_DOC unless est_usd_per_doc is given. Planning only: the
    ledger cap is what limits spend."""
    docs_budget=max(0.0,float(cost_cap_usd)-float(flash_budget_usd or 0))
    model=extract_model
    if est_usd_per_doc is not None:
        est=float(est_usd_per_doc)
    elif injected:
        est=DEFAULT_EST_USD_PER_DOC
    else:
        try:
            plan=extract_plan()
            if extract_model and extract_model!=plan['model']:
                est=plan['fallback_est_usd_per_doc'] if extract_model==plan['fallback'] else DEFAULT_EST_USD_PER_DOC
            else:
                est,model=plan['est_usd_per_doc'],plan['model']
        except Exception:
            est=DEFAULT_EST_USD_PER_DOC
    fit=min(int(max_extract),int(docs_budget//est)) if est>0 else int(max_extract)
    return dict(docs_budget_usd=round(docs_budget,4),est_usd_per_doc=est,max_extract=max_extract,fit=fit,extract_model=model)


def extract_fallbacks(client):
    """Count EXTRACT calls that ran on the documented fallback (records written by ErisedaiClient)."""
    n,reasons=0,Counter()
    for call in getattr(client,'calls',None) or []:
        if call.get('stage')!='extract': continue
        try: rec=json.loads(Path(call['path']).read_text())
        except (OSError,ValueError,KeyError): continue
        if rec.get('model_fallback'):
            n+=1; reasons[str(rec.get('fallback_reason') or '')[:80]]+=1
    return dict(calls=sum(1 for c in getattr(client,'calls',None) or [] if c.get('stage')=='extract'),fallback=n,
                reasons=dict(reasons.most_common(3)))



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
    # v10 (Fiona approved 10/6): 华尔街见闻 global/macro desk articles (ch142), same adapter as us-stock.
    from live.adapters import wallstreetcn
    fetchers['ch142_wscn_global'] = lambda:wallstreetcn.fetch(limit=10,channel='global-channel')
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


# ---------------- v10 (Oct 6): 7x24 flashes + tier-C headline leads ----------------
FLASH_BUDGET_USD=1.75     # ring-fenced inside cost_cap_usd (Fiona: $1.5-2 of the $10 daily cap)
FLASH_BATCH_SIZE=20
FLASH_MAX=150             # flashes extracted per run at most (~$0.005 each measured; see flash_extract)
FLASH_WINDOW_HOURS=26
FLASH_DEDUPE_HOURS=6
FLASH_FETCH_N=100
FLASH_RECENT_KEEP=800


def _parse_ts(value):
    try: return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (TypeError,ValueError): return None


def gather_flashes(state, *, now, known=None, fetch=None, window_hours=FLASH_WINDOW_HOURS,
                   dedupe_hours=FLASH_DEDUPE_HOURS, flash_max=FLASH_MAX, n=FLASH_FETCH_N, lead_hooks=()):
    """No LLM. Fetch the 3 flash outlets, drop seen / promo / old, dedupe across outlets and against
    recently extracted flashes, order (topic relevance + tier-C lead hook boost), cap at flash_max.
    -> dict(selected, overflow, dropped, outlets)."""
    from live.adapters import flashes
    from live import news_hook
    fetch=fetch or flashes.fetch
    fs=state.get('flashes') or {}
    since=now-timedelta(hours=window_hours)
    seen=set(fs.get('seen') or [])
    gathered,outlets=[],[]
    for cid in flashes.OUTLETS:
        row=dict(id=cid,status='ok',fetched=0,new=0,error=None)
        try:
            out=fetch(cid,n=n,since=since)
            row['status']=out.get('status','ok'); row['fetched']=len(out.get('sources') or [])
            for src in out.get('sources') or []:
                if src['id'] in seen or (known and (known(src['id']) or (src.get('url') and known(src['url'])))): continue
                gathered.append(src); row['new']+=1
        except Exception as exc:
            row.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        outlets.append(row)
    # flashes the previous run could not afford (flash budget / flash_max) come back while still in window
    ids={s['id'] for s in gathered}
    for src in fs.get('pending') or []:
        ts=_parse_ts(src.get('published_at'))
        if src['id'] not in ids and src['id'] not in seen and ts and ts>=since:
            gathered.append(dict(src,also_reported_by=list(src.get('also_reported_by') or []),pending_from_previous=True))
    recent=[r for r in fs.get('recent') or [] if (_parse_ts(r.get('published_at')) or now)>=now-timedelta(hours=max(dedupe_hours,window_hours))]
    kept,dropped=flashes.dedupe(gathered,hours=dedupe_hours,recent=recent)
    leads=set(lead_hooks or ())
    def boost(src):
        hit=bool(leads & news_hook.hooks(src['original_text']))
        src['lead_hook']=hit
        return 2 if hit else 0
    ordered=sorted(kept,key=lambda src:(-(flashes.relevance(src)+boost(src)+(1 if src.get('pending_from_previous') else 0)),
                                        -((_parse_ts(src.get('published_at')) or now).timestamp())))
    cap=max(0,int(flash_max))
    return dict(selected=ordered[:cap],overflow=ordered[cap:],dropped=dropped,outlets=outlets)


def flash_client(directory):
    """Relay client for the extract_flash stage (live/stage_models.json: claude-sonnet-5 at 3/15 per 1M)."""
    from live.erisedai_distillation_client import ErisedaiClient
    return ErisedaiClient(directory,configuration=_relay_config())


def extract_flashes(db, selected, *, client, jev, budget, cost_cap_usd, flash_budget_usd, batch_size,
                    state, now, extract_batch=None):
    """Batched cheap EXTRACT inside the ring-fenced flash budget. Returns (stats, pending_sources)."""
    from live import flash_extract, jev_front, registry
    from scripts.run_content_adapters import ingest_batches
    extract_batch=extract_batch or flash_extract.extract_batch
    fs=state.setdefault('flashes',{})
    start=budget.spent()
    fence=min(float(cost_cap_usd),start+max(0.0,float(flash_budget_usd)))
    budget.set_cap(fence)
    stats=dict(selected=len(selected),extracted=0,with_units=0,units_added=0,calls=0,prompt_tokens=0,completion_tokens=0,
               dropped_units=0,failed_flashes=[],budget_usd=float(flash_budget_usd),fence_cap_usd=round(fence,4),
               deferred_flash_budget=0)
    pending=[]
    seen=set(fs.get('seen') or []); recent=list(fs.get('recent') or [])
    try:
        groups=flash_extract.batches(selected,batch_size)
        for gi,group in enumerate(groups):
            tier=registry.source_licence_tier(group[0]['source_id']) or 'B'
            try:
                result=extract_batch(group,client,licence_tier=tier,stats=stats)
            except budget.BudgetExceeded:
                pending=[s for g in groups[gi:] for s in g]; stats['deferred_flash_budget']=len(pending)
                break
            stats['extracted']+=len(group)
            items=[(src,result.get(src['id']) or [],src['adapter']) for src in group]
            with_units=[it for it in items if it[1]]
            stats['with_units']+=len(with_units)
            if with_units:
                routing=jev_front.route_sources([dict(id=src['id'],title=src.get('title') or '',publisher=src.get('publisher'),
                                                      snippet=src['original_text'][:400]) for src,_,_ in with_units],jev=jev)
                try:
                    stats['units_added']+=ingest_batches(db,with_units,routing,jev=jev)['added']
                except budget.BudgetExceeded:
                    # Jev ran out inside the fence: these flashes are re-tried next run
                    pending=[s for s,_,_ in with_units]+[s for g in groups[gi+1:] for s in g]
                    stats['deferred_flash_budget']=len(pending)
                    break
            for src in group:
                seen.add(src['id'])
                recent.append(dict(id=src['id'],text=src['original_text'][:300],published_at=src.get('published_at')))
    finally:
        budget.set_cap(cost_cap_usd)
        fs['seen']=sorted(seen)[-5000:] if len(seen)>5000 else sorted(seen)
        fs['recent']=recent[-FLASH_RECENT_KEEP:]
        fs['last_run']=now.isoformat()
    stats['cost_usd']=round(budget.spent()-start,4)
    stats['usd_per_flash']=round(stats['cost_usd']/stats['extracted'],5) if stats['extracted'] else None
    stats['failed_flashes']=len(stats['failed_flashes'])
    return stats,pending


def run(*, store=ROOT/'live/store/content_units', runs_dir='/workspace/x/ingest_runs',
        inbox='/workspace/x/ingest_inbox', cost_cap_usd=10.0, channel_timeout=90, channel_timeouts=None,
        max_extract=60, max_source_chars=5000, extract_model=None, allow_nondefault_extract_model=False, per_channel_max=2, no_dashboard=False, dry_run=False, only=None,
        fair_share_floor=2, persona_minimum=True, est_usd_per_doc=None,
        flash_budget_usd=FLASH_BUDGET_USD, flash_batch_size=FLASH_BATCH_SIZE, flash_max=FLASH_MAX,
        flash_window_hours=FLASH_WINDOW_HOURS, flash_dedupe_hours=FLASH_DEDUPE_HOURS, flashes=True, news_leads=True,
        flash_fetch=None, flash_extract_batch=None, flash_llm=None, news_collect=None,
        x=True, x_budget_usd=None, x_window_hours=None, x_max=None, x_per_source_max=None, x_batch_size=None,
        x_rapid=None, x_apify=None, x_subs=None, x_extract_batch=None, x_llm=None,
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
        # v8 (Oct 6): items the previous run deferred go first and bypass per_channel_max.
        from live import ingest_priority
        prev=ingest_priority.previous_deferred(runs_dir)
        state=json.loads(state_path.read_text()) if state_path.exists() else {'channels':{}}
        fs=default_fetchers(state,store) if fetchers is None else fetchers
        if only:
            fs={k:v for k,v in fs.items() if k in only or k.split(':')[0] in only or ('channels' in only and k.startswith('ch'))}
        tasks=[]; gathered_ids=set()   # v10: one article can sit in two feeds (华尔街见闻 us-stock + global)
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
                    if s.get('id') and s['id'] in gathered_ids: continue
                    if any(failed.get(k,0)>=2 for k in keys): continue
                    prior=bool(prev['ids'].intersection(keys))
                    if units is None and per_channel_max and rank>=per_channel_max and not prior: continue
                    ch['new_items']+=1; tasks.append((ch,s,units,adapter,keys,rank)); rank+=1; gathered_ids.add(s.get('id'))
            except Exception as exc:
                ch.update(status='timeout' if isinstance(exc,TimeoutError) else 'failed',error=f'{type(exc).__name__}: {exc}')
                summary['failing_channels'].append(cid)
            ch['seconds']=time.monotonic()-t
            print(f"[gather] {cid} {ch['status']} new={ch['new_items']} {ch['seconds']:.0f}s",file=sys.stderr,flush=True)
        summary['steps'].append(dict(id='gather',status='ok'))
        summary['steps'].append(dict(id='incremental',status='ok',new_items=len(tasks)))
        fit_estimate=None
        if persona_minimum:
            fit_estimate=extract_fit(cost_cap_usd=cost_cap_usd,flash_budget_usd=flash_budget_usd if flashes else 0,
                                     max_extract=max_extract,extract_model=extract_model,injected=extract is not None,
                                     est_usd_per_doc=est_usd_per_doc)
        tasks,plan=ingest_priority.order_tasks(tasks,summary['fresh_by_persona_before'],prev['ids'],
                                               floor=fair_share_floor,legacy_priority=priority,
                                               fit=fit_estimate['fit'] if fit_estimate else None)
        summary['ordering']=dict(previous_run=prev['run'],previous_deferred=len(prev['ids']),
                                 prior_deferred_gathered=sum(r['prior_deferred'] for r in plan),
                                 fair_share_floor=fair_share_floor,plan=plan,fit_estimate=fit_estimate,
                                 persona_minimum=[r['persona'] for r in plan if r['phase']=='persona_minimum'])
        # v10: tier-C headline leads (no LLM; titles/hooks only, never content units) then 7x24 flashes.
        lead_hooks=set()
        # Injected `fetchers` (tests / ad-hoc runs) skip the live leads/flash fetch unless their own fakes are given.
        if news_leads and (not only or 'news' in only) and (fetchers is None or news_collect is not None):
            def collect_leads():
                from live import news
                out=(news_collect or news.collect)(dry_run=dry_run)
                lead_hooks.update(out.get('lead_hooks') or {})
                summary['news_leads']=dict(new_items=out.get('new_items',0),failing=out.get('failing',[]),
                                           lead_hooks=out.get('lead_hooks') or {},licence_tier='C',usage='topic_only')
            step('news_leads',collect_leads)
        flash_plan=None
        if flashes and (not only or 'flashes' in only) and (fetchers is None or flash_fetch is not None):
            known=known_urls(store,state) if (store/'units.jsonl').exists() else None
            flash_plan=gather_flashes(state,now=started,known=known,fetch=flash_fetch,window_hours=flash_window_hours,
                                      dedupe_hours=flash_dedupe_hours,flash_max=flash_max,lead_hooks=lead_hooks)
            summary['channels'] += [dict(id=o['id'],status=o['status'],new_items=o['new'],units=0,seconds=0,error=o['error'])
                                    for o in flash_plan['outlets']]
            summary['failing_channels'] += [o['id'] for o in flash_plan['outlets'] if o['status']=='failed']
            reasons=Counter(d['reason'] for d in flash_plan['dropped'])
            summary['flashes']=dict(budget_usd=float(flash_budget_usd),cap_usd=cost_cap_usd,
                                    docs_budget_usd=round(cost_cap_usd-min(cost_cap_usd,float(flash_budget_usd)),2),
                                    outlets=flash_plan['outlets'],selected=len(flash_plan['selected']),
                                    overflow_flash_max=len(flash_plan['overflow']),duplicates=reasons.get('duplicate',0),
                                    seen_earlier=reasons.get('seen_earlier',0),lead_hook_boosted=sum(1 for x in flash_plan['selected'] if x.get('lead_hook')),
                                    batches=-(-len(flash_plan['selected'])//max(1,flash_batch_size)),
                                    preview=[dict(id=x['id'],outlet=x['source_id'],published_at=x.get('published_at'),
                                                  original_outlet=x.get('original_outlet'),echo=len(x.get('also_reported_by') or []),
                                                  lead_hook=x.get('lead_hook',False),text=x['original_text'][:60])
                                             for x in flash_plan['selected'][:15]])
        # Oct 7 (fd20): account-scoped X sources, last 24h originals (RapidAPI, Apify fallback; no LLM here).
        from live import x_daily
        x_budget=x_daily.X_BUDGET_USD if x_budget_usd is None else float(x_budget_usd)
        x_plan=None
        if x and (not only or 'x' in only) and (fetchers is None or x_rapid is not None or x_apify is not None):
            def gather_x():
                nonlocal x_plan
                known=known_urls(store,state) if (store/'units.jsonl').exists() else None
                x_plan=x_daily.gather(state,now=started,known=known,subs=x_subs,rapid=x_rapid,apify=x_apify,
                                      window_hours=x_window_hours or x_daily.X_WINDOW_HOURS,
                                      per_source_max=x_per_source_max or x_daily.X_PER_SOURCE_MAX,
                                      x_max=x_daily.X_MAX if x_max is None else x_max)
                summary['x']=dict(budget_usd=x_budget,sources=len(x_plan['sources']),
                                  fetched_sources=sum(1 for r in x_plan['sources'] if r['provider']),
                                  by_provider=dict(Counter(r['provider'] for r in x_plan['sources'] if r['provider'])),
                                  skipped_tier_c=sum(1 for r in x_plan['sources'] if str(r['status']).startswith('skipped_tier')),
                                  failed=[dict(handle=r['handle'],error=r['error']) for r in x_plan['sources'] if r['status']=='failed'],
                                  posts_fetched=sum(r['fetched'] for r in x_plan['sources']),
                                  selected=len(x_plan['selected']),overflow=len(x_plan['overflow']),filtered=x_plan['filtered'],
                                  rapid_requests=x_plan['requests'],apify=x_plan['apify'],
                                  per_handle=[{k:r[k] for k in ('handle','provider','status','fetched','kept','new')} for r in x_plan['sources']
                                              if r['provider'] or r['status']=='failed'])
            step('x_gather',gather_x)
        summary['ordering']['budget_split']=dict(cap_usd=cost_cap_usd,flash_ring_fence_usd=float(flash_budget_usd) if flash_plan else 0.0,
                                                 x_ring_fence_usd=x_budget if x_plan else 0.0,
                                                 order=['flashes (ring-fenced)','pre_extracted','timely (prior-deferred first)',
                                                        'fair_share_floor','rest','transcripts_last'],
                                                 note='unused flash budget rolls over to documents')
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
            xplan=extract_plan(client.stage_models)
            summary['extract_model']=xplan['model']
            summary['extract_fallback_model']=xplan['fallback']
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
        if flash_plan and flash_plan['selected'] and flash_budget_usd>0:
            def run_flashes():
                fclient=flash_llm or flash_client(budget.STORE.parent/'flash_calls')
                stats,pending=extract_flashes(db,flash_plan['selected'],client=fclient,jev=jev,budget=budget,
                                              cost_cap_usd=cost_cap_usd,flash_budget_usd=flash_budget_usd,
                                              batch_size=flash_batch_size,state=state,now=started,
                                              extract_batch=flash_extract_batch)
                summary['flashes'].update(stats)
                keep=lambda x:{k:v for k,v in x.items() if k not in ('lead_hook',)}
                state.setdefault('flashes',{})['pending']=[keep(x) for x in pending+flash_plan['overflow']][:400]
                for o in summary['channels']:
                    if o['id'] in {x['source_id'] for x in flash_plan['selected']}:
                        o['units']=None   # per-flash units are in summary['flashes']
            step('flashes',run_flashes)
        elif flash_plan is not None:
            state.setdefault('flashes',{})['pending']=[x for x in flash_plan['overflow']][:400]
        if x_plan and x_plan['selected'] and x_budget>0:
            def run_x():
                xclient=x_llm or flash_client(budget.STORE.parent/'x_calls')
                stats,pending=x_daily.extract(db,x_plan['selected'],client=xclient,budget=budget,cost_cap_usd=cost_cap_usd,
                                              x_budget_usd=x_budget,batch_size=x_batch_size or x_daily.X_BATCH_SIZE,
                                              state=state,now=started,extract_batch=x_extract_batch,subs=x_subs)
                summary['x'].update(stats)
                summary['x']['deferred']=len(pending)+len(x_plan['overflow'])
            step('x_extract',run_x)
        capped=False; extracted=0
        for ch,s,units,adapter,keys,rank in tasks:   # v8: ingest_priority order (fair-share floor)
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
        if 'client' in locals() and client is not None:
            summary['extract_calls']=extract_fallbacks(client)
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
        def crypto_subbeats():
            from live import beat_rules
            db2=content_store.ContentStore(store)
            tags=beat_rules.crypto_subbeat_tags(db2.units())
            db2.set_persona_tags(tags,.7)
            summary['crypto_subbeats']=dict(units_tagged=len(tags))
        step('crypto_subbeats',crypto_subbeats)
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
