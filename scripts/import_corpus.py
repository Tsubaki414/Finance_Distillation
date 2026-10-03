from pathlib import Path
import json,re,hashlib,datetime,collections,uuid
from email.utils import parsedate_to_datetime
from promotion_policy import clean_promotions,VERSION,output_gate

ROOT=Path(__file__).resolve().parents[1]
INPUT=Path('/Users/fionama/Desktop/Crypto/Mango_Works/Finance_Stocks_KOL/outputs/relationship_pipeline_20260905_v1')
DONORS={
 'phyrexni':'zh','qinbafrank':'zh','kovainvest':'zh','aleabitoreddit':'zh','michael_qqq2025':'zh','xingpt':'zh',
 'beth_kindig':'en','citrini':'en','ericjackson':'en','rjccapital':'en','globalmktobserv':'en','tradexwhisperer':'en'}
FINANCE=re.compile(r'财报|估值|美股|股票|股价|上市|利率|通胀|流动性|美联储|联储|央行|非农|期权|期货|国债|债券|收益率|营收|收入|利润|毛利|净利|现金流|持仓|仓位|交易|投资|半导体|芯片|存储|英伟达|订单|产能|光模块|加密|比特币|以太|稳定币|纳指|标普|铜价|油价|\$[A-Z]{2,6}\b|\b(?:earnings|revenue|margin|valuation|equity|stock|stocks|shares|bond|yield|inflation|liquidity|federal reserve|fed|payroll|portfolio|trading|trader|trade|invest|investment|semiconductor|memory|capex|supply chain|risk management|drawdown|entry|position|bitcoin|ethereum|btc|qqq|hbm|gpu|nvidia|guidance)\b',re.I)
AD=re.compile(r'邀请码|返佣|开户链接|优惠码|注册链接|注册.*领取|限时优惠|付费群|扫码.*加入|领取.*空投|推广链接|\b(?:affiliate|referral code|sign up.*bonus|promo code|sponsored|paid partnership|subscribe.*discount)\b',re.I)
LIFE=re.compile(r'晚餐|早餐|咖啡|第二杯|旅游|风景|孩子|生日|猫咪|美食|晚安|good morning|happy birthday|dinner|vacation|coffee|family',re.I)
MECH=re.compile(r'因为|所以|意味着|取决于|导致|如果|但是|然而|由于|\b(?:because|therefore|implies|driven by|depends|if|however|while|risk)\b',re.I)
SOURCE=re.compile(r'财报|公告|数据显示|根据|研报|统计|电话会|\b(?:according|reported|filing|data|research|survey|transcript)\b',re.I)
def analysis_text(text,post_id=None):
 cleaned,spans,decision=clean_promotions(text,post_id)
 markers=re.findall(r'\b(?:bitcoin|ethereum):native|\b(?:solana|ethereum|ripple):[A-Za-z0-9]+',cleaned)
 cleaned=re.sub(r'\bbitcoin:native\b','BTC',cleaned);cleaned=re.sub(r'\bethereum:native\b','ETH',cleaned)
 cleaned=re.sub(r'\b(?:solana|ethereum|ripple):[A-Za-z0-9]+','[asset]',cleaned)
 return cleaned,{'excluded_spans':spans,'provider_entity_marker_normalizations':markers,'version':VERSION,'raw_text_preserved':True,'whole_post_commercial_exclusion':decision}

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def stamp(value):
 if not value:return None
 try:return datetime.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(datetime.timezone.utc).isoformat()
 except (ValueError,AttributeError):
  try:return parsedate_to_datetime(value).astimezone(datetime.timezone.utc).isoformat()
  except Exception:return None
def jsonl(path,rows):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def classify(row):
 text=row.get('analysis_text',row['text']);fin=bool(FINANCE.search(text));ad=bool(AD.search(text)) or bool(re.search(r'赞助|推广合作',text)) or bool(row.get('text_processing',{}).get('whole_post_commercial_exclusion')) or bool(output_gate(text));life=bool(LIFE.search(text));why=[]
 if row['post_type']=='repost':cat='纯转推';keep=False;conf=.99;why=['not_author_language']
 elif ad:cat='广告或带货';keep=False;conf=.93;why=['explicit_promotion_marker']
 elif re.search(r'代发|代笔|ghostwritten|posted on behalf',text,re.I):cat='可能由他人代写或来源不明';keep=False;conf=.75;why=['explicit_authorship_marker']
 elif not text.strip():cat='无法判断';keep=False;conf=.99;why=['empty_text']
 elif re.search(r'空投|白名单|mint now|presale',text,re.I):cat='项目推广';keep=False;conf=.83;why=['project_campaign_marker']
 elif row['post_type']=='reply':cat='回复';keep=fin and len(text)>=35;conf=.90;why=[] if keep else ['reply_lacks_standalone_financial_context']
 elif row['post_type']=='quote':cat='引用评论';keep=fin and len(text)>=35;conf=.88;why=[] if keep else ['quote_comment_not_substantive_finance']
 elif fin and re.search(r'冲冲|梭哈|无脑买|all in|to the moon|buy now',text,re.I) and not MECH.search(text):cat='喊单但无分析';keep=False;conf=.80;why=['unsupported_call']
 elif fin and SOURCE.search(text):cat='原始研究或数据引用';keep=True;conf=.83
 elif fin and (MECH.search(text) or len(text)>=140):cat='原创金融分析';keep=True;conf=.82
 elif fin:cat='新闻转述';keep=len(text)>=35;conf=.68;why=[] if keep else ['too_short_to_interpret']
 elif life:cat='生活内容';keep=False;conf=.82;why=['non_finance_lifestyle']
 else:cat='原创非金融内容';keep=False;conf=.65;why=['no_finance_evidence_under_rule_v1']
 if not row['stable_author_id'] or row['author_match'] is False:
  keep=False;why.append('stable_author_identity_unavailable_or_mismatch')
 return {'category':cat,'financial_relevant':fin and not ad,'keep':keep,'confidence':conf,'confidence_kind':'heuristic_not_calibrated','excluded_reasons':why,'method':'rules-v3-commercial-cleanup','signals':{'finance':fin,'promotion':ad,'mechanism':bool(MECH.search(text)),'source_cue':bool(SOURCE.search(text))}}

def main():
 now=datetime.datetime.now(datetime.timezone.utc);run_id='import-'+uuid.uuid4().hex[:12];limit=now-datetime.timedelta(days=180)
 previous=ROOT/'data/corpus_manifest.json'
 if previous.exists():
  old=json.loads(previous.read_text());snapshot=ROOT/'data/imports'/old['import_run_id'];snapshot.mkdir(parents=True,exist_ok=True)
  for name in ['raw_posts.jsonl','clean_posts.jsonl','corpus_manifest.json']:
   dest=snapshot/name
   if not dest.exists():dest.write_bytes((ROOT/'data'/name).read_bytes())
 grouped=collections.defaultdict(dict);inputs=[];source_coverage={};incoming=0
 paths=[INPUT/'chinese_x_hardcore_wave1/apify_90d_audit.json',INPUT/'chinese_commercial_gap_audit/apify_90d_audit.json',INPUT/'chinese_question_audit/apify_latest20_raw.json',INPUT/'x_candidate_wave2/rapid_x_audit.json',INPUT/'x_candidate_wave3/rapid_x_audit.json']
 for path in paths:
  payload=json.loads(path.read_text());source_hash=hashlib.sha256(path.read_bytes()).hexdigest();inputs.append({'path':str(path),'sha256':source_hash})
  audits=payload.get('audits',[]) if isinstance(payload,dict) else payload
  for a in audits:
   handle=(a.get('handle') or a.get('requested_handle') or '').lower()
   if handle not in DONORS:continue
   posts=a.get('window_posts',a.get('latest_20',(a.get('content') or {}).get('latest20',[])))
   provider='apify' if 'apify' in path.name else 'rapidapi-twitter241'
   source_coverage[handle]={'provider':provider,'input_file':str(path),'saved_texts':len(posts),'reported_observed_count':(a.get('content') or {}).get('observed_unique_90d'),
      'coverage_record':a.get('coverage') or {k:v for k,v in a.get('content',{}).items() if k.endswith('stop_reason') or k.endswith('reached_boundary')},'new_collection':False}
   for pos,t in enumerate(posts):
    incoming+=1;postid=str(t.get('tweet_id') or t.get('id') or '');created=stamp(t.get('created_at'))
    if not postid or not created or datetime.datetime.fromisoformat(created)<limit:continue
    author=t.get('author') or {};author_id=author.get('rest_id') or author.get('id')
    author_handle=author.get('screen_name') or author.get('username') or ''
    is_rt=bool(t.get('is_repost') or t.get('is_retweet') or t.get('reposted_post'))
    kind='repost' if is_rt else 'reply' if t.get('is_reply') else 'quote' if t.get('is_quote') else 'original'
    run=a.get('run') or {};run=run if isinstance(run,dict) else {}
    collected=stamp(run.get('finishedAt') or run.get('startedAt') or (payload.get('manifest') or {}).get('checked_at') if isinstance(payload,dict) else run.get('finishedAt') or run.get('startedAt'))
    urls=t.get('urls') or [];urls=[u.get('expanded_url') or u.get('url') if isinstance(u,dict) else u for u in urls]
    urls=[u for u in urls if u];urls+=re.findall(r'https?://[^\s<>]+',t.get('text',''))
    media=t.get('media');metrics=t.get('metrics') or {k:t.get(k) for k in ['favorite_count','retweet_count','reply_count','quote_count','bookmark_count','view_count']}
    quote=t.get('quoted_tweet') or {'post_id':t.get('quote_tweet_id') or t.get('quoted_tweet_id'),'author':t.get('quote_target')}
    row={'source_account_id':handle,'stable_author_id':str(author_id) if author_id else None,'handle_at_collection':author_handle or handle,
      'post_id':postid,'url':t.get('url') or f'https://x.com/{handle}/status/{postid}','created_at':created,'collected_at':collected,'ingested_at':now.isoformat(),
      'text':t.get('text',''),'language':t.get('lang') or 'unknown','target_language':DONORS[handle],'post_type':kind,
      'reply_to':{'post_id':t.get('in_reply_to_status_id') or t.get('reply_to_tweet_id'),'user_id':t.get('in_reply_to_user_id') or t.get('reply_to_user_id'),'handle':t.get('in_reply_to_screen_name') or t.get('reply_to_username')} if t.get('is_reply') else None,
      'quoted_post':quote if t.get('is_quote') else None,'reposted_post':{'post_id':t.get('repost_tweet_id'),'author':t.get('repost_target')} if is_rt else None,
      'thread_id':str(t.get('conversation_id')) if t.get('conversation_id') else None,'media_type':sorted(set(m.get('type','unknown') for m in media)) if media is not None else None,
      'external_links':sorted(set(urls)),'engagement_snapshot':metrics,'raw_payload_hash':hashlib.sha256(canonical(t)).hexdigest(),'provider_run_id':run.get('id'),
      'import_run_id':run_id,'provider':provider,'payload_scope':'inherited_normalized_post_not_original_network_response','input_file_hash':source_hash,
      'source_order_index':pos,'author_match':author_handle.lower()==handle if author_handle else None,'timeline_pinned':t.get('timeline_pinned'),
      'missing_fields':[k for k,v in {'collected_at':collected,'stable_author_id':author_id,'media_type':media,'provider_run_id':run.get('id')}.items() if v is None],
      'source_record':t}
    old=grouped[handle].get(postid)
    if old is None or len(row['text'])>len(old['text']):grouped[handle][postid]=row
 rows=[]
 for handle in DONORS:
  observed=sorted(grouped[handle].values(),key=lambda r:(r['created_at'],r['post_id']),reverse=True)[:500]
  rows.extend(reversed(observed))
 seen={};clean=[]
 for row in rows:
  row['analysis_text'],row['text_processing']=analysis_text(row['text'],row['post_id'])
  removed_urls=set(re.findall(r'https?://[^\s<>]+','\n'.join(s['text'] for s in row['text_processing']['excluded_spans'])))
  remaining_urls=set(re.findall(r'https?://[^\s<>]+',row['analysis_text']))
  row['analysis_external_links']=[u for u in row['external_links'] if u not in removed_urls or u in remaining_urls]
  row['classification']=classify(row)
  normalized=re.sub(r'\s+',' ',re.sub(r'https?://\S+','',row['analysis_text'])).strip().lower()
  dup_key=(row['source_account_id'],normalized)
  row['duplicate_group']=hashlib.sha256(normalized.encode()).hexdigest()[:20]
  if dup_key in seen:
   row['classification']['keep']=False;row['classification']['excluded_reasons'].append('same_author_exact_text_duplicate');row['duplicate_of']=seen[dup_key]
  else:seen[dup_key]=row['post_id']
  if row['classification']['keep']:
   processing={**row['text_processing'],'excluded_spans':[{k:v for k,v in s.items() if k!='text'} for s in row['text_processing']['excluded_spans']]}
   clean.append({**{k:v for k,v in row.items() if k!='source_record'},'text':row['analysis_text'],'external_links':row['analysis_external_links'],'text_processing':processing,'raw_source_ref':{'file':'raw_posts.jsonl','post_id':row['post_id'],'payload_hash':row['raw_payload_hash']}})
 jsonl(ROOT/'data/raw_posts.jsonl',rows);jsonl(ROOT/'data/clean_posts.jsonl',clean)
 counts=[]
 for handle in DONORS:
  raw=[r for r in rows if r['source_account_id']==handle];kept=[r for r in clean if r['source_account_id']==handle]
  counts.append({'handle':handle,'target_language':DONORS[handle],'raw_count':len(raw),'clean_count':len(kept),'target_clean':150,'shortfall':max(0,150-len(kept)),
    'oldest':raw[0]['created_at'] if raw else None,'newest':raw[-1]['created_at'] if raw else None,'coverage':source_coverage.get(handle),'complete_180d':False,'status':'sufficient_count_in_incomplete_window' if len(kept)>=150 else 'insufficient_data',
    'post_types':dict(collections.Counter(r['post_type'] for r in raw)),'categories':dict(collections.Counter(r['classification']['category'] for r in raw)),
    'rates':{name:sum(fn(r) for r in raw)/max(1,len(raw)) for name,fn in {'finance':lambda r:r['classification']['financial_relevant'],'original':lambda r:r['post_type']=='original','reply':lambda r:r['post_type']=='reply','advertisement':lambda r:r['classification']['category'] in ['广告或带货','项目推广'],'source_reference':lambda r:bool(r['external_links']) or r['classification']['signals']['source_cue']}.items()}})
 (ROOT/'data/corpus_manifest.json').write_text(json.dumps({'import_run_id':run_id,'as_of':now.isoformat(),'imported_only':True,'inputs':inputs,'incoming_records':incoming,'raw_posts':len(rows),'clean_posts':len(clean),'donors':counts,
   'target':{'donors':12,'zh_donors':6,'en_donors':6,'max_items_per_donor':500,'window_days':180,'clean_per_donor':150,'clean_total':1800},
   'new_x_collector':'Xquik-dev/x-twitter-scraper','new_collection_status':'blocked_missing_xquik_key_and_live_cost_estimate','cleaning_version':VERSION,'retained_language_counts':dict(collections.Counter(r['language'] for r in clean)),'human_validation':False},ensure_ascii=False,indent=2))
 (ROOT/'runs').mkdir(exist_ok=True)
 with (ROOT/'runs/api_run_ledger.jsonl').open('a') as f:f.write(json.dumps({'run_id':run_id,'operation':'user_import','started_at':now.isoformat(),'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_files':len(inputs),'new_network_requests':0,'new_paid_calls':0,'raw_count':len(rows),'clean_count':len(clean),'input_hashes':[i['sha256'] for i in inputs]})+'\n')
 print(json.dumps({'raw':len(rows),'clean':len(clean),'donors':[{k:d[k] for k in ['handle','raw_count','clean_count','shortfall']} for d in counts]},ensure_ascii=False))

if __name__=='__main__':main()
