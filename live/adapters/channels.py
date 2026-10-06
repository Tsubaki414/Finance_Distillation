"""Planned public channels: discovery is radar; only substantial public text is a source."""
from __future__ import annotations
import calendar
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import feedparser
import httpx
from bs4 import BeautifulSoup
from live.adapters import common

MODES = {'feed_fulltext', 'feed_linkfollow', 'html_index', 'json_api', 'existing_adapter', 'podcast_audio', 'excluded'}
PAYWALL = re.compile(r'subscribe to (?:continue|read)|sign in to read|log in to (?:read|continue)|login to (?:read|continue)|subscription required|premium content|register to read|unlock this article|订阅阅读全文|登录后阅读|登录后查看|登陆后查看|订阅后阅读|付费阅读|会员专享', re.I)
DEFAULT_MODES = ('feed_fulltext', 'feed_linkfollow', 'html_index', 'json_api')

def load_channels(path):
    raw = json.loads(Path(path).read_text())
    rows = raw['channels'] if isinstance(raw, dict) else raw
    seen = set()
    for ch in rows:
        cid = ch.get('channel_id')
        if not cid or cid in seen: raise ValueError('missing or duplicate channel_id')
        seen.add(cid)
        if ch.get('mode') not in MODES: raise ValueError(f'{cid}: invalid mode')
        if ch['mode'] in ('excluded', 'podcast_audio') and (not str(ch.get('reason') or '').strip() or str(ch['reason']).strip().lower() in ('n/a','unknown','excluded','podcast')):
            raise ValueError(f'{cid}: concrete reason required')
        if ch.get('licence_tier') not in ('A','B'): raise ValueError(f'{cid}: invalid licence tier')
    return rows

def select_channels(rows, *, modes=None, ids=None, batch=None):
    selected = [c for c in rows if (modes is None or c['mode'] in modes) and (not ids or c['channel_id'] in ids)]
    if ids and set(ids)-{c['channel_id'] for c in rows}: raise ValueError('unknown channel ids')
    if batch:
        try: k,n=map(int,batch.split('/'))
        except (ValueError,AttributeError): raise ValueError('batch must be K/N') from None
        if not 1 <= k <= n: raise ValueError('batch requires 1 <= K <= N')
        q,r=divmod(len(selected),n); start=(k-1)*q+min(k-1,r)
        selected=selected[start:start+q+(k<=r)]
    return selected

def _extract(page, extractor=None):
    if extractor is not None: return (extractor(page) or '').strip()
    try:
        import trafilatura
        text=trafilatura.extract(page, favor_precision=True, include_comments=False, include_tables=True)
    except (ImportError, ValueError): text=None
    return (text or common.html_text(page)).strip()

def _domain(url):
    host=(urlparse(url).hostname or '').lower()
    # tld ships a local public suffix table (also used by trafilatura).
    try:
        from tld import get_tld
        result = get_tld('https://' + host, as_object=True, fail_silently=True)
        return result.fld if result else host
    except ImportError:
        # A missing suffix database must restrict discovery, never broaden it.
        return host.removeprefix('www.')

def _date(value):
    match=re.search(r'(20\d{2})[-/](\d{2})[-/](\d{2})',value or '')
    return '-'.join(match.groups()) if match else ''

def _iso_date(value):
    """ISO date/datetime from page metadata; month-only values ('September 2026') become the 1st; junk becomes ''."""
    value=str(value or '').strip()
    if not value or re.match(r'20\d{2}-\d{2}-\d{2}',value): return value
    try:
        from dateutil import parser
        return parser.parse(value,default=datetime(2000,1,1)).date().isoformat() if re.search(r'20\d{2}',value) else ''
    except (ValueError,OverflowError):
        return ''

PAGE_DATE = re.compile(r'(?:发布(?:日期|时间)|日期)\s*[：:]\s*(?:&nbsp;|\s)*'
                       r'(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{4})年(\d{1,2})月(\d{1,2})日)')

def page_date(html_text):
    """Labelled date in a page body ('日期：2026-10-06', '发布时间：2026年10月6日'); '' when absent or invalid."""
    for source in (html_text or '', common.html_text(html_text or '')):
        for match in PAGE_DATE.finditer(source):
            y,m,d=match.groups()[:3] if match[1] else match.groups()[3:]
            try: return date(int(y),int(m),int(d)).isoformat()
            except ValueError: continue
    return ''

def _candidates(page, base):
    soup=BeautifulSoup(page,'html.parser'); found=[]; seen=set()
    for a in soup.find_all('a',href=True):
        url=urljoin(base,a['href']).split('#')[0]; p=urlparse(url); label=a.get_text(' ',strip=True)
        if p.scheme not in ('http','https') or _domain(url)!=_domain(base) or url in seen: continue
        if len([s for s in p.path.split('/') if s])<2: continue
        if len(label)<20 and len(re.findall(r'[\u3400-\u9fff]',label))<8: continue
        if re.search(r'/(?:login|signin|tag|tags|category|categories|search|subscribe)(?:/|$)',p.path,re.I): continue
        if a.find_parent(['nav','header','footer']): continue
        seen.add(url)
        nearby=a.parent.get_text(' ',strip=True)[:1000] if a.parent else ''
        # List tables (e.g. Sina reports) keep the date in a sibling cell of the link's row.
        row=a.find_parent('tr')
        row_text=row.get_text(' ',strip=True)[:1000] if row else ''
        found.append({'url':url,'title':label,'published_at':_date(url) or _date(nearby) or _date(row_text)})
    return sorted(found,key=lambda r:r['published_at'],reverse=True)

def _pdf_allowed(ch,url):
    host=(urlparse(url).hostname or '').lower()
    official = host.endswith(('.gov', '.gov.cn', '.gov.hk'))
    central_banks = {'ecb.europa.eu', 'bankofengland.co.uk', 'boj.or.jp', 'bis.org',
                     'hkma.gov.hk', 'federalreserve.gov', 'newyorkfed.org', 'frbsf.org', 'atlantafed.org'}
    same_domain = _domain(url) == _domain(ch.get('url', ''))
    bank = any(host == domain or host.endswith('.' + domain) for domain in central_banks)
    company_ir = bool(re.search(r'company.*\bIR\b|investor relations', ch.get('reason', ''), re.I))
    return official or (same_domain and ch.get('licence_tier') == 'A' and (bank or company_ir))

def _convert_pdf(body):
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'article.pdf'; path.write_bytes(body)
        return subprocess.run(['pdftotext',str(path),'-'],check=True,capture_output=True,timeout=30).stdout.decode('utf-8','replace')

def fetch_channel(ch, *, limit=1, transport=None, extractor=None, converter=None):
    if limit < 1: raise ValueError('limit must be positive')
    mode=ch['mode']; out={'status':'no_text','requests':0,'sources':[],'radar':[]}
    def radar(item,reason): out['radar'].append({**item,'reason':reason,'channel_id':ch['channel_id']})
    def get(url, *, method='GET', data=None, binary=False):
        out['requests']+=1
        if method=='POST':
            headers={'User-Agent':common.DEFAULT_UA,'Content-Type':'application/x-www-form-urlencoded'}
            if transport is not None: return transport(url,headers,method=method,data=data)
            response=httpx.post(url,headers=headers,data=data,timeout=30,follow_redirects=True)
            return response.status_code,response.text
        return common.http_get(url,transport=transport,binary=binary)
    def accept(item,page, *, pdf=False):
        text=(converter or _convert_pdf)(page) if pdf else _extract(page,extractor)
        visible=common.html_text(page) if not pdf else text
        if PAYWALL.search(visible): radar(item,'paywall/login marker'); return False
        # Chinese text is ~2.5x denser than English: 600 CJK-language chars carry about as much as 1500 English.
        minimum=600 if str(ch.get('lang','en')).startswith('zh') else 1500
        if len(text)<minimum: radar(item,f'short text: {len(text)} chars (<{minimum})'); return False
        published=item.get('published_at') or ''
        if not published and not pdf:
            soup=BeautifulSoup(page,'html.parser')
            meta=soup.find('meta',attrs={'property':'article:published_time'}) or soup.find('meta',attrs={'name':'date'})
            time=soup.find('time')
            published=(meta.get('content','') if meta else '') or (time.get('datetime','') if time else '') or page_date(page)
        published=_iso_date(published)
        ident=ch['channel_id']+'-'+hashlib.sha256(item['url'].encode()).hexdigest()[:16]
        out['sources']+=common.make_sources_chunked(id=ident,source_id=ch['channel_id'],text=text,publisher=common.html_text(ch['name']),title=item.get('title') or ch['name'],url=item['url'],published_at=published,adapter='channel:'+mode,lang=ch.get('lang','en'),max_parts=1,extra={'no_reproduction':bool(ch.get('no_reproduction'))})
        return True
    deny=[p for p in ch.get('deny_url_patterns') or [] if p]
    def denied(item):
        if any(p in (item.get('url') or '') for p in deny):
            radar(item,'disallowed by robots.txt rule'); return True
        return False
    def follow(item):
        url=item.get('url')
        if not url: radar(item,'missing article link'); return
        if denied(item): return
        pdf=urlparse(url).path.lower().endswith('.pdf')
        if pdf and not _pdf_allowed(ch,url): radar(item,'PDF not authorised for this channel'); return
        status,page=get(url,binary=pdf)
        if status!=200: radar(item,f'http_{status}'); return
        accept(item,page,pdf=pdf)
    try:
        if mode in ('excluded','podcast_audio','existing_adapter'):
            out['reason']=ch.get('reason') or 'handled by existing adapter'; return out
        endpoint=(ch.get('feed_url') or ch['url']) if mode.startswith('feed_') else ch['url']
        if mode=='json_api' and ch['channel_id'].startswith('ch001_'):
            # The public list API requires a date window (HTTP 400 without beginTime/endTime).
            today=datetime.now(timezone.utc).date()
            endpoint=('https://reportapi.eastmoney.com/report/list?industryCode=*&industry=*&rating=*&ratingChange=*&qType=0'
                      f'&code=*&orgCode=&rcode=&beginTime={(today-timedelta(days=14)).isoformat()}&endTime={today.isoformat()}'
                      f'&pageNo=1&pageSize={limit}&sort=publishDate&sortType=desc')
        if mode=='json_api' and ch['channel_id'].startswith('ch139_'):
            return _eastmoney_columns(ch,limit,get,follow,out)
        post=mode=='json_api' and ch['channel_id'].startswith('ch063_')
        status,page=get(endpoint,method='POST' if post else 'GET',data={'pageNum':1,'pageSize':limit,'tabName':'fulltext','column':'szse','plate':'sz','searchkey':'','secid':'','stock':'','category':'','trade':'','seDate':'','sortName':'','sortType':'','isHLtitle':'true'} if post else None)
        if status!=200: out.update(status=f'http_{status}',reason=f'index/feed http_{status}'); return out
        if mode.startswith('feed_'):
            parsed=feedparser.parse(page)
            entries=sorted(parsed.entries,key=lambda e:e.get('published_parsed') or e.get('updated_parsed') or (0,)*9,reverse=True)
            for entry in entries[:limit]:
                date=entry.get('published_parsed') or entry.get('updated_parsed')
                item={'url':urljoin(endpoint,entry.get('link','')) if entry.get('link') else '', 'title':entry.get('title',''), 'published_at':datetime.fromtimestamp(calendar.timegm(date),timezone.utc).isoformat() if date else ''}
                if denied(item): continue
                body='\n'.join(c.get('value','') for c in entry.get('content',[])) or entry.get('summary','') or entry.get('description','')
                if mode=='feed_fulltext' and body and len(_extract(body,extractor))>=1500:
                    accept(item,body)
                else: follow(item)
            if not entries: out['reason']='feed has no entries'
        elif mode=='html_index':
            candidates=_candidates(page,endpoint)
            for item in candidates[:limit*3]:
                follow(item)
                if len(out['sources'])>=limit: break
            if not candidates: out['reason']='no eligible article links in index'
        elif mode=='json_api':
            try:
                payload=json.loads(page)
            except json.JSONDecodeError:
                # Probe snapshots can end mid-record; retain only complete HKEX
                # announcement objects, never repair or invent a partial record.
                if not ch['channel_id'].startswith('ch064_'): raise
                start=page.find('"newsInfoLst"')
                start=page.find('[',start) if start>=0 else -1
                if start<0: raise
                decoder=json.JSONDecoder(); offset=start+1; complete=[]
                while offset<len(page):
                    while offset<len(page) and page[offset] in ' \r\n\t,': offset+=1
                    try: record,offset=decoder.raw_decode(page,offset)
                    except json.JSONDecodeError: break
                    complete.append(record)
                if not complete: raise
                payload={'newsInfoLst':complete}
            def records(obj):
                if isinstance(obj,list):
                    for value in obj: yield from records(value)
                elif isinstance(obj,dict):
                    if any(k in obj for k in ('title','TITLE','announcementTitle','infoCode')): yield obj
                    else:
                        for value in obj.values(): yield from records(value)
            for row in list(records(payload))[:limit]:
                item={'title':row.get('title') or row.get('TITLE') or row.get('announcementTitle') or '', 'url':endpoint, 'published_at':row.get('publishDate','')}
                if ch['channel_id'].startswith('ch001_') and row.get('infoCode'):
                    item['url']='https://data.eastmoney.com/report/info/'+str(row['infoCode'])+'.html'; follow(item)
                else: radar(item,'titles only')
            if not out['radar'] and not out['sources']: out['reason']='API returned no discoverable records'
        out['status']='ok' if out['sources'] else 'radar' if out['radar'] else 'no_text'
        out.setdefault('reason',out['radar'][0]['reason'] if out['radar'] else 'public text extracted' if out['sources'] else 'no substantial public text')
    except Exception as exc:
        out.update(status='error',reason=f'{type(exc).__name__}: {str(exc)[:200]}')
    return out


def _eastmoney_columns(ch, limit, get, follow, out):
    """Eastmoney public news-list API for its US-stock columns (美股导读 768, 美股公司 611); articles are public pages."""
    seen=set()
    for column in ch.get('columns') or [768, 611]:
        url=('https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_news_col'
             f'&column={column}&order=1&needInteractData=0&page_index=1&page_size={max(limit*3,5)}&req_trace=1')
        status,page=get(url)
        if status!=200: continue
        rows=((json.loads(page).get('data') or {}).get('list') or [])
        for row in rows:
            link=(row.get('uniqueUrl') or row.get('url') or '').replace('http://','https://',1)
            if not link or link in seen: continue
            seen.add(link)
            shown=row.get('showTime') or ''
            try: published=datetime.strptime(shown,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
            except ValueError: published=_date(link)
            follow({'url':link,'title':row.get('title') or '','published_at':published,'media':row.get('mediaName')})
            if len(out['sources'])>=limit: break
        if len(out['sources'])>=limit: break
    out['status']='ok' if out['sources'] else 'radar' if out['radar'] else 'no_text'
    out.setdefault('reason',out['radar'][0]['reason'] if out['radar'] else 'public text extracted' if out['sources'] else 'no substantial public text')
    return out
