"""Bounded source/context recovery. No login, cookie access or paid crawler.

Fetch only configured public hosts. Related post recovery uses already collected
records. Media remains unavailable until a real transcript/extraction is supplied.
"""
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
import re
import socket
from urllib.parse import urlparse, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
from bs4 import BeautifulSoup
from live.distillation_source import digest, now
from live.language_support import DEFAULT as DEFAULT_LANGUAGES


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def validate_url(url,allowed_hosts):
    u=urlparse(url)
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.hostname not in allowed_hosts:
        raise ValueError('URL outside configured HTTPS recovery hosts')
    for item in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:raise ValueError('Non-public recovery address')
    return u


def fetch_public(url,allowed_hosts,max_bytes=2_000_000):
    opener=build_opener(NoRedirect)
    for _ in range(4):
        validate_url(url,allowed_hosts)
        try:r=opener.open(Request(url,headers={'User-Agent':'ContentLocalization/1.0 public-source-reader'}),timeout=25)
        except Exception as e:
            if getattr(e,'code',0) in (301,302,303,307,308):url=urljoin(url,e.headers['Location']);continue
            raise
        with r:
            raw=r.read(max_bytes+1)
            if len(raw)>max_bytes:raise ValueError('Public response exceeds recovery limit')
            kind=r.headers.get('Content-Type','')
            if not any(k in kind for k in ('text/html','text/plain','application/xhtml')):raise ValueError('Unread media/PDF requires a supplied extraction')
            return {'url':url,'raw':raw.decode('utf-8',errors='replace'),'content_type':kind,'fetched_at':now()}
    raise ValueError('Too many redirects')


def extract_page(document):
    raw=document['raw'];soup=BeautifulSoup(raw,'html.parser')
    if 'text/plain' in document.get('content_type',''):
        # A plain response can itself be a feed summary or teaser. HTTP 200 and
        # body length do not establish that the whole article was obtained.
        text=raw;status='public_text_completeness_unverified';complete=False;media=[]
    else:
        root=soup.find('article') or soup.find('main')
        if root is None:raise ValueError('No reliable article/main body; manual extraction needed')
        for tag in root.find_all(['script','style','nav','form','button','footer']):tag.decompose()
        media=[{'url':urljoin(document['url'],tag.get('src','')),'alt':tag.get('alt',''),'read':False} for tag in root.find_all('img')]
        for pre in root.find_all('pre'):pre.replace_with('\n\n```\n'+pre.get_text()+'\n```\n\n')
        for tag in root.find_all(['p','li','h1','h2','h3','blockquote','tr']):tag.insert_before('\n\n');tag.append('\n\n')
        text=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',root.get_text()).strip()
        complete=not bool(re.search(r'continue reading|read the full|paid subscribers|subscribe to (?:read|continue)|阅读全文|付费阅读',text,re.I))
        status='public_article' if complete else 'public_partial_or_teaser'
    if len(text.strip())<80:raise ValueError('Recovery body too short to establish completeness')
    return {'text':text,'url':document['url'],'content_complete':complete,'extraction_status':status,'media':media,
            'fetched_at':document['fetched_at'],'document_hash':digest(raw),'extractor_version':'bounded-public-html-v1'}


def relation_id(value):
    return str(value.get('post_id') or value.get('id') or '') if isinstance(value,dict) else str(value or '')


class SourceRecovery:
    def __init__(self,directory,allowed_hosts=(),posts=None,fetcher=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.allowed_hosts=set(allowed_hosts);self.posts=posts or {};self.fetcher=fetcher or (lambda u:fetch_public(u,self.allowed_hosts))

    def retrieve(self,url):
        if urlparse(url).hostname not in self.allowed_hosts:raise ValueError('Recovery host not configured')
        document=self.fetcher(url)
        record={**document,'document_hash':digest(document['raw'])}
        path=self.directory/(record['document_hash']+'.json')
        if not path.exists():path.write_text(json.dumps(record,ensure_ascii=False,indent=2))
        result=extract_page(document);result['document_ref']=str(path)
        return result

    def recover(self,row):
        result=deepcopy(row);report={'at':now(),'original_text_hash':digest(row.get('original_text',row.get('text',''))),'actions':[],'unresolved':[]}
        context=list(result.get('context_items') or [])
        for role,key in [('reply','reply_to'),('quote','quoted_post')]:
            pid=relation_id(row.get(key))
            if not pid:continue
            inline=row.get(key)
            related=self.posts.get(pid) or (inline if isinstance(inline,dict) and inline.get('text') else None)
            if related:
                context.append({'role':role,'post_id':pid,'text':related.get('original_text',related.get('text','')),'author':related.get('author_name') or related.get('handle_at_collection') or related.get('author'),'url':related.get('url'),'source_hash':digest(related.get('original_text',related.get('text',''))),'retrieved_from':'existing_local_archive'})
                report['actions'].append({'kind':'cached_context','role':role,'post_id':pid})
            else:report['unresolved'].append({'kind':role,'post_id':pid,'required':'semantic_assessment'})
        # An explicit collected thread is context, never silently concatenated as one author/post.
        for pid in row.get('thread_post_ids') or []:
            related=self.posts.get(str(pid))
            if related:context.append({'role':'thread','post_id':str(pid),'text':related.get('text',''),'author':related.get('author_name') or related.get('handle_at_collection'),'url':related.get('url'),'source_hash':digest(related.get('text','')),'retrieved_from':'existing_local_archive'})
            else:report['unresolved'].append({'kind':'thread','post_id':str(pid),'required':True})
        # Transport capability comes from the adapter, not the platform name.
        # Legacy article labels are retained only for already collected rows.
        mode=row.get('body_recovery')
        if mode is None and row.get('source_type') in ('article','newsletter','wechat','captured_public_article'):
            mode='public_html'
        if mode=='public_html' and row.get('content_complete') is not True and row.get('url'):
            try:
                recovered=self.retrieve(row['url'])
                if recovered['content_complete']:
                    result.update(recovered,original_text=recovered['text']);result.pop('source_hash',None);result.pop('source_version',None)
                    report['actions'].append({'kind':'full_body','document_ref':recovered['document_ref']})
                    # A preview can be too short to identify its language. Its
                    # derived "unknown" label must not veto the newly recovered
                    # full body. Preserve known declarations and record evidence
                    # instead of guessing from the publisher or account language.
                    if row.get('source_language') in (None, '', 'unknown'):
                        detected, confidence = DEFAULT_LANGUAGES.detect(recovered['text'])
                        language = detected if detected in DEFAULT_LANGUAGES.codes and confidence >= .8 else 'unknown'
                        result.update(source_language=language, language_confidence=confidence,
                                      language_method=DEFAULT_LANGUAGES.version)
                        report['actions'].append({'kind':'full_body_language_detection',
                            'previous_language':row.get('source_language'), 'language':language,
                            'detected_language':detected, 'confidence':confidence,
                            'method':DEFAULT_LANGUAGES.version,
                            'body_hash':digest(recovered['text']),
                            'document_ref':recovered['document_ref']})
                else:report['unresolved'].append({'kind':'body','reason':recovered['extraction_status'],'document_ref':recovered['document_ref'],'required':True})
            except Exception as exc:report['unresolved'].append({'kind':'body','reason':type(exc).__name__,'required':True})
        if row.get('truncated'):result['content_complete']=False;report['unresolved'].append({'kind':'truncated_post','required':True})
        if row.get('media_dependencies'):report['unresolved'].append({'kind':'media','required':True})
        for url in row.get('required_context_urls') or []:
            try:
                page=self.retrieve(url)
                if not page['content_complete']:raise ValueError('Linked context incomplete')
                context.append({'role':'linked_article','text':page['text'],'url':page['url'],
                                'source_hash':digest(page['text']),'document_ref':page['document_ref'],
                                'author':None,'ownership':'external linked document; not automatically the post author'})
            except Exception as exc:
                report['unresolved'].append({'kind':'linked_article','url':url,'required':True,'reason':type(exc).__name__})
        # Recovery may be replayed on an already enriched intake record.
        unique={}
        for item in context:
            unique.setdefault(digest([item.get('role'),item.get('post_id'),item.get('url'),item.get('text')]),item)
        result['context_items']=list(unique.values());result['recovery']=report
        return result
