"""Mind-map FILL tier (Oct 16, Fiona): the LAST tier of the 'fill slot' logic.

Tier order for an account's day: (1) fresh standalone drafts (compose rounds) + reply / quote-big-account drafts (engagement
slot), (2) 回看 / 常青 archive drafts (live/archive_lookback.fill_gaps, FD_ARCHIVE), (3) THIS: a mind map of a long-form
source (blog / YouTube / X-video transcript / book summary, stored by live/longform_src.py), only for an account that still
has NO ready standalone row after (1) and (2) (the same slot rule as the archive tier: engagement rows do not count, an
archive row does). Mind maps are not an account; they are a post type (post_kind 'mindmap').

Switch: FD_MINDMAP_FILL=1 (default OFF). Caps: FD_MINDMAP_MAX_PER_DAY (4 maps / Beijing day), 1 per account and day,
FD_MINDMAP_BUDGET_USD (1.0 model spend per run), FD_MINDMAP_ACCOUNTS (csv; OVERRIDES the tone list), FD_MINDMAP_ATTEMPTS (3 sources
tried per account). Rows: post_kind / post_type 'mindmap', media[0] kind 'mindmap' (PNG, 2400 px wide), caption = row text,
credit + source recorded in row['mindmap'] and the image footer, freshness-exempt (live/fresh_hold.py), yieldable to a fresh
standalone (live/archive_fallback.py). Never publishes.

Oct 16 (Fiona, 'account tone decides'): (a) an account that has only reply / quote rows is NOT filled (the fill is for a
genuinely absent standalone, not for a reply-only day); (b) only accounts in live/mindmap_accounts.json (analytical /
educational / long-term personas) are eligible, unknown accounts are not, FD_MINDMAP_ACCOUNTS overrides; (c) a map whose
source topic is off the account's lane (live/lane_fit) is held 'off_lane'.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from live.mindmap import gen, render

ROOT = Path(__file__).resolve().parents[2]
POST_KIND = 'mindmap'
LABEL = '思维导图'
ID_PREFIX = 'mm-'


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_MINDMAP_FILL', '0') == '1'


def _int(name, default, env=None):
    try:
        return int((env if env is not None else os.environ).get(name, default))
    except ValueError:
        return default


def store_dir():
    return Path(os.environ.get('FD_MINDMAP_STORE') or ROOT / 'live' / 'store' / 'mindmap')


def _now():
    return datetime.now(timezone.utc)


def is_mindmap(row):
    return row.get('post_kind') == POST_KIND or str(row.get('id') or '').startswith(ID_PREFIX)


# ---------------------------------------------------------------- ledger (source use)

def ledger_rows():
    p = store_dir() / 'ledger.jsonl'
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def record_use(day, account, item_id, draft_id, **extra):
    p = store_dir() / 'ledger.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    from live import lanes   # Oct 16: flock'd append
    lanes.locked_append(p, json.dumps({'day': str(day), 'account': account, 'item': item_id, 'draft': draft_id, **extra},
                                      ensure_ascii=False))


# ---------------------------------------------------------------- account tone gate (Oct 16)

TONE_FILE = ROOT / 'live' / 'mindmap_accounts.json'


def tone_accounts(path=None):
    """Account ids whose persona tone allows a mind map (analytical / educational / long-term). Missing / bad file -> none."""
    try:
        return {str(x) for x in json.loads(Path(path or TONE_FILE).read_text()).get('eligible', [])}
    except (OSError, ValueError, AttributeError):
        return set()


def eligible(account_id, env=None, path=None):
    """(ok, why). FD_MINDMAP_ACCOUNTS (csv) overrides the tone list; an account in neither is not eligible."""
    raw = (env if env is not None else os.environ).get('FD_MINDMAP_ACCOUNTS', '')
    allow = {x.strip() for x in raw.split(',') if x.strip()}
    if allow:
        return (account_id in allow), ('FD_MINDMAP_ACCOUNTS' if account_id in allow else 'not in FD_MINDMAP_ACCOUNTS')
    if account_id in tone_accounts(path):
        return True, 'tone list'
    return False, 'tone: not in live/mindmap_accounts.json (unknown / hype / trader tone)'


def lane_check(acct, item):
    """Topic fit of the SOURCE (its title + topic tag, not the generated map) vs the account's lane, via live/lane_fit.
    {'ok', 'why', 'detail'}; ok when lane_fit has no objection."""
    from live import lane_fit
    text = f"{item.get('title') or ''} {item.get('topic') if item.get('topic') not in (None, 'general') else ''}".strip()
    chk = lane_fit.macro_check(acct, text)
    if chk.get('ok') and lane_fit.is_niche(acct):
        chk = lane_fit.packet_check(acct, text)
    return chk


# ---------------------------------------------------------------- account / source fit

CRYPTO_WORDS = re.compile(r'crypto|btc|bitcoin|defi|airdrop|meme|perp|onchain|stable|sol_|eth|altcoin|币|链|空投|加密', re.I)


def acct_is_crypto(acct):
    return bool(CRYPTO_WORDS.search(' '.join(str(acct.get(k) or '') for k in ('id', 'beat'))))


def topic_fits(topic, acct):
    """Source topic (crypto | investing | macro | ai | general) vs the account's lane."""
    crypto = acct_is_crypto(acct)
    ident = f"{acct.get('id', '')} {acct.get('beat', '')}".lower()
    if topic in (None, '', 'general'):
        return True
    if topic == 'crypto':
        return crypto
    if topic == 'macro':
        return (not crypto) or 'macro' in ident or '宏观' in ident
    if topic == 'trading':
        return bool(re.search(r'trad|option|vol|期权|交易|k线|perp|arb|套利|funding|stock|个股|美股', ident))
    if topic == 'ai':
        return bool(re.search(r'ai|tech|industry|科技|半导体', ident))
    if topic == 'investing':
        return (not crypto) or bool(re.search(r'invest|longterm|newbie|philosophy|新手|长期', ident))
    return True


def video_fits(item, acct):
    """X-video transcripts: only the FD_VIDEO_SRC accounts, and only money / mind-set content."""
    from live import video_src
    if acct['id'] not in video_src.accounts():
        return False
    head = f"{item.get('title', '')}"
    if video_src.EXCLUDE.search(head):
        return False
    return bool(video_src.MONEY_MIND.search(head))


def usable(item, acct, *, used_by_acct, uses, min_chars=None):
    if item['id'] in used_by_acct or uses.get(item['id'], 0) >= _int('FD_MINDMAP_ITEM_MAX_USES', 3):
        return False
    lang = 'zh' if str(item.get('lang', 'en')).startswith('zh') else 'en'
    need = min_chars or (1500 if lang == 'zh' else 2500)
    if int(item.get('chars') or 0) and int(item['chars']) < need:
        return False
    if item.get('kind') == 'x_video':
        return video_fits(item, acct)
    return topic_fits(item.get('topic'), acct)


def rank(items, acct):
    """Same-language sources first (no translation), then newest."""
    want = 'zh' if str(acct.get('lang', 'zh')).startswith('zh') else 'en'
    return sorted(items, key=lambda m: (0 if str(m.get('lang', 'en'))[:2] == want else 1,
                                        -(datetime.fromisoformat(str(m['published_at']).replace('Z', '+00:00')).timestamp()
                                          if m.get('published_at') else 0)))


# ---------------------------------------------------------------- slot gate

def ready_standalone(day, account, base=None):
    from live import archive_fallback, compose_inbox
    return [r for r in compose_inbox.rows(str(day), account=account, base=base)
            if archive_fallback._ready(r) and archive_fallback.is_standalone(r)]


def archive_fallback_standalone(row):
    from live import archive_fallback
    return archive_fallback.is_standalone(row)


def gate(account, day, *, base=None, made_today=0):
    """(run?, reason)."""
    from live import compose_inbox
    if made_today >= _int('FD_MINDMAP_MAX_PER_DAY', 4):
        return False, f"day cap {_int('FD_MINDMAP_MAX_PER_DAY', 4)} mind maps reached"
    rows = compose_inbox.rows(str(day), account=account, base=base)
    if any(is_mindmap(r) and not r.get('superseded') for r in rows):
        return False, 'already has its mind map for the day'
    reply_only = [r for r in rows if not r.get('superseded') and not r.get('held') and not archive_fallback_standalone(r)]
    ready = ready_standalone(day, account, base)
    if reply_only and not ready:
        return False, f'reply-only account ({len(reply_only)} reply / quote row(s), no standalone): not filled (Fiona 16 Oct)'
    if ready:
        return False, f'slot rule: {len(ready)} ready standalone draft(s) (fresh / archive) already fill the slot'
    return True, 'no ready standalone draft after the fresh + archive tiers'


def maps_today(day, base=None):
    from live import compose_inbox
    return sum(1 for r in compose_inbox.rows(str(day), base=base) if is_mindmap(r) and not r.get('superseded'))


# ---------------------------------------------------------------- row

def inbox_row(acct, item, result, day, run_id, *, post_time, png_info, rel_png, tree_path):
    data = result['data']
    held = any(f['level'] == 'hard' for f in result['findings'])
    did = f"{ID_PREFIX}{run_id[-6:]}-{acct['id']}-{hashlib.sha1(item['id'].encode()).hexdigest()[:8]}"[:80]
    sha = hashlib.sha256(Path(png_info['path']).read_bytes()).hexdigest()
    caption = result['caption']
    hard = sorted({f['code'] for f in result['findings'] if f['level'] == 'hard'})
    row = {'id': did, 'day': str(day), 'run_id': run_id, 'account_id': acct['id'], 'no': acct.get('no'),
           'name': acct.get('name'), 'beat': acct.get('beat'), 'lang': acct.get('lang'),
           'post_kind': POST_KIND, 'post_type': POST_KIND, 'label': LABEL, 'draft_origin': 'mindmap',
           'text': caption, 'body': caption, 'attribution_line': 'none (own voice; credit is in the image footer + row.mindmap)',
           'post_format': {'type': 'mindmap', 'length': 'single', 'thread_parts': 1},
           'post_mode': 'original', 'post_mode_why': 'mindmap fill tier (long-form source summary)',
           'suggested_post_time_london': post_time,
           'angle': {'id': 'mindmap', 'lens': 'mind map of a long-form source'}, 'angle_why': 'mindmap_fill',
           'draft_status': 'needs_review' if held else 'draft_ready', 'status': 'held' if held else 'ok', 'error': None,
           'why': 'mindmap fill: no ready standalone after fresh + archive tiers', 'held': held,
           'hold_reason': ('hard: ' + ','.join(hard)) if held else None,
           'findings': [{'code': f['code'], 'level': f['level'], 'detail': f.get('detail')} for f in result['findings']],
           'stance': {'decision': 'mindmap', 'account_view': None, 'subject': data['title'], 'direction': None},
           'source': {'id': item['id'], 'source_id': item.get('source_id'), 'publisher': item.get('name'),
                      'title': item.get('title'), 'url': item.get('url'), 'published_at': item.get('published_at'),
                      'lang': item.get('lang'), 'kind': item.get('kind'),
                      'same_language': str(item.get('lang', ''))[:2] == str(acct.get('lang', ''))[:2]},
           'mindmap': {'version': gen.VERSION, 'lang': data['lang'], 'title': data['title'], 'nodes': result['stats']['nodes'],
                       'levels': max(l for _n, l in render.walk(data['branches'])), 'branches': len(data['branches']),
                       'stats': {k: v for k, v in result['stats'].items()},
                       'attribution': {'author': item.get('author'), 'publisher': item.get('name'), 'title': item.get('title'),
                                       'url': item.get('url'), 'published_at': item.get('published_at'), 'kind': item.get('kind'),
                                       'footer': data['footer']},
                       'source_item': item['id'], 'source_text_sha256': item.get('sha256'),
                       'render': {k: png_info.get(k) for k in ('css_w', 'css_h', 'overlaps', 'overflow')},
                       'tree_json': tree_path, 'freshness': 'exempt (evergreen-like)'},
           'media': [{'kind': 'mindmap', 'chart_type': 'mindmap', 'path': rel_png, 'sha256': sha,
                      'alt': f"Mind map: {data['title']} ({item.get('name')})", 'refreshed_at': _now().isoformat(timespec='seconds'),
                      'data_sources': [{'name': item.get('name'), 'url': item.get('url')}]}],
           'media_plan': {'wanted': 'mindmap', 'status': 'made'},
           'models': sorted({m for m in [(result.get('raw') or {}).get('response_model')] if m}),
           'spend_usd': result.get('spend_usd'), 'publishable': False}
    return row


# ---------------------------------------------------------------- run

def run(account_ids, day, *, inbox_base=None, media_out=None, runs_dir=None, ask=None, pool_items=None, write=True,
        log=print, force=False, accounts=None, budget_usd=None, renderer=None, client_cost=None):
    """Make mind-map rows for the accounts that pass the slot gate. `ask(messages)->(dict, raw)` and `pool_items` are test
    seams (default: Gemini compose client, longform_src.pool())."""
    from live import archive_lookback as al, compose_inbox, fd_accounts, fresh_hold, longform_src, posting_habits as ph, registry
    day = date.fromisoformat(str(day))
    run_id = 'mm' + _now().strftime('%Y%m%dT%H%M%S')
    out_dir = Path(runs_dir or store_dir() / 'runs') / day.isoformat() / run_id
    roster = {a['id']: a for a in (accounts or fd_accounts.rows(al.ACCOUNTS))}
    budget = float(budget_usd if budget_usd is not None else os.environ.get('FD_MINDMAP_BUDGET_USD', 1.0))
    summary = {'day': day.isoformat(), 'run_id': run_id, 'accounts': {}, 'model_usd': 0.0, 'made': 0}
    state = {'client': None}

    def default_ask(messages):
        if state['client'] is None:
            state['client'], _t = al.make_client(out_dir / 'calls')
        # Flash stage (FD_MINDMAP_STAGE, default 'stance'): the pro compose stage times out (HTTP 524 after ~125 s) on this
        # ~4-6k-token JSON output through the relay; flash answers in well under a minute.
        from live.model_json import parse_object
        last = None
        for _attempt in range(2):
            try:
                r = state['client'](os.environ.get('FD_MINDMAP_STAGE', 'stance'), messages, 14000)
                if r.get('model_fallback') or not str(r.get('response_model') or '').startswith('gemini-'):
                    raise RuntimeError(f"non-Gemini response {r.get('response_model')}")
                return parse_object(r['text']), r
            except ValueError as exc:   # unparsable JSON: one retry
                last = exc
        raise last

    ask = ask or default_ask
    # flat-rate relays report $0: count a conservative per-call estimate so the run budget still binds
    est_call = float(os.environ.get('FD_MINDMAP_EST_USD_PER_CALL', 0.02))
    cost_of = client_cost or (lambda: max(al._cost(state['client']), est_call * len(state['client'].calls)) if state['client'] else 0.0)
    items = pool_items if pool_items is not None else longform_src.pool()
    ledger = ledger_rows()
    uses = {}
    for r in ledger:
        uses[r['item']] = uses.get(r['item'], 0) + 1
    made_today = maps_today(day, inbox_base)
    render_fn = renderer or render.render_png
    spent = 0.0
    import time as _time
    t0 = _time.monotonic()
    run_tries = 0
    max_tries = _int('FD_MINDMAP_MAX_TRIES_PER_RUN', 12)
    wall_s = float(os.environ.get('FD_MINDMAP_WALL_S', 1500))
    for aid in account_ids:
        if run_tries >= max_tries or _time.monotonic() - t0 > wall_s:
            summary['stopped'] = f'run cap: {run_tries} source tries / {_time.monotonic() - t0:.0f}s'
            log(f"[mindmap] stop: {summary['stopped']}")
            break
        info = summary['accounts'].setdefault(aid, {})
        acct = roster.get(aid)
        ok_acct, why_acct = eligible(aid)
        if acct is None or not ok_acct:
            info['skip'] = 'not in roster' if acct is None else why_acct
            continue
        if not force:
            ok, why = gate(aid, day, base=inbox_base, made_today=made_today)
            info['gate'] = why
            if not ok:
                log(f'[{aid}] mindmap skip: {why}')
                continue
        used_by = {r['item'] for r in ledger if r['account'] == aid}
        cands = rank([m for m in items if usable(m, acct, used_by_acct=used_by, uses=uses)], acct)
        info['candidates'] = len(cands)
        tries = 0
        for item in cands:
            if tries >= _int('FD_MINDMAP_ATTEMPTS', 3):
                break
            if spent >= budget:
                info['skip'] = f'run budget ${budget:.2f} spent'
                break
            if run_tries >= max_tries or _time.monotonic() - t0 > wall_s:
                break
            tries += 1
            run_tries += 1
            before = cost_of()
            try:
                text = longform_src.read_text(item)
                item = {**item, 'sha256': hashlib.sha256(text.encode()).hexdigest()}
                voice = al.voice_summary(aid)
                res = gen.make_tree(ask, acct, voice, text, item)
            except Exception as exc:   # noqa: BLE001 - one source / account never sinks the others
                res = {'status': 'error', 'why': f'{type(exc).__name__}: {str(exc)[:160]}', 'findings': []}
            res['spend_usd'] = round(cost_of() - before, 6)
            spent += res['spend_usd']
            info.setdefault('tries', []).append({'item': item['id'], 'status': res['status'], 'why': res.get('why'),
                                                 'spend_usd': res['spend_usd']})
            if res['status'] == 'skip':
                record_use(day, aid, item['id'], None, status='skip', why=res.get('why'))   # not retried for this account
                continue
            if res['status'] != 'ok':
                continue
            hard = [f for f in res['findings'] if f['level'] == 'hard']
            if hard:
                info['tries'][-1]['hard'] = [f['code'] for f in hard]
                info['tries'][-1]['hard_detail'] = [str(f.get('detail'))[:120] for f in hard[:4]]
                record_use(day, aid, item['id'], None, status='hard', codes=[f['code'] for f in hard])
                continue
            did_hash = hashlib.sha1(item['id'].encode()).hexdigest()[:8]
            rel = Path('media') / day.isoformat() / f"{ID_PREFIX}{run_id[-6:]}-{aid}-{did_hash}.png"
            from live import draft_media
            png = Path(media_out or draft_media.MEDIA_OUT) / rel
            try:
                png_info = render_fn(res['data'], png)
            except Exception as exc:   # noqa: BLE001
                info['tries'][-1]['render_error'] = f'{type(exc).__name__}: {str(exc)[:160]}'
                continue
            if png_info.get('overlaps') or png_info.get('overflow'):
                info['tries'][-1]['render_error'] = f"layout check failed: {png_info.get('overlaps')} overlaps, {png_info.get('overflow')} overflow"
                continue
            (out_dir).mkdir(parents=True, exist_ok=True)
            tree_path = out_dir / f'{aid}.tree.json'
            tree_path.write_text(json.dumps(res['data'], ensure_ascii=False, indent=1))
            persona = registry.persona_for_account(aid)
            card = ph.load_card(persona)
            taken = []
            for r in compose_inbox.rows(day.isoformat(), account=aid, base=inbox_base):
                try:
                    taken.append(datetime.fromisoformat(r['suggested_post_time_london']))
                except (KeyError, TypeError, ValueError):
                    pass
            post_time = ph.sample_post_time(card, day, seed=f'{aid}|mindmap|{item["id"]}', taken=taken, min_gap_min=90).isoformat()
            row = inbox_row(acct, item, res, day, run_id, post_time=post_time, png_info=png_info, rel_png=rel.as_posix(),
                            tree_path=str(tree_path))
            try:
                fresh_hold.apply(row, log=log)
            except Exception:   # noqa: BLE001
                pass
            lchk = lane_check(acct, item)
            if not lchk.get('ok') and not row.get('held'):
                row.update({'held': True, 'hold_reason': 'off_lane', 'draft_status': 'needs_review', 'status': 'held',
                            'hold_detail': lchk.get('detail') or 'source topic off the account lane'})
                info['tries'][-1]['off_lane'] = True
            if write:
                compose_inbox.add(row, base=inbox_base)
            record_use(day, aid, item['id'], row['id'], status='made')
            uses[item['id']] = uses.get(item['id'], 0) + 1
            made_today += 1
            summary['made'] += 1
            info.update(draft_id=row['id'], source=item['id'], png=str(png), nodes=row['mindmap']['nodes'], held=row['held'])
            log(f"[{aid}] mindmap {row['draft_status']} ${res['spend_usd']:.4f} {item['id']} | {row['text'][:80]!r}")
            break
        else:
            if cands and 'draft_id' not in info:
                log(f'[{aid}] no mind map: {tries} source(s) tried')
        if 'draft_id' not in info and not cands:
            info.setdefault('skip', 'no usable long-form source in the pool')
    summary['model_usd'] = round(spent, 6)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    summary['out_dir'] = str(out_dir)
    return summary


def fill_gaps(day, *, accounts=None, log=print):
    """Hook for scripts/daily_compose.py (after the 回看 hook): FD_MINDMAP_FILL=1 only; never fatal to the day."""
    if not enabled():
        return {'skipped': 'FD_MINDMAP_FILL != 1'}
    ids = list(accounts or [])
    return run(ids, day, log=log)
