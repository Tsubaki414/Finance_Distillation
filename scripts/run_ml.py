from pathlib import Path
import os,json,re,csv,time,datetime,hashlib,collections,importlib.util,random
ROOT=Path(__file__).resolve().parents[1]
for name in ['TRACKIO_SPACE_ID','TRACKIO_SERVER_URL','TRACKIO_BUCKET_ID','TRACKIO_WEBHOOK_URL']:
 os.environ.pop(name,None)
os.environ.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',TRACKIO_DIR=str(ROOT/'ml_experiments/trackio'))
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score,precision_recall_fscore_support,classification_report,confusion_matrix,silhouette_score
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from scipy.spatial.distance import jensenshannon
from sentence_transformers import SentenceTransformer
import torch,trackio

sp=importlib.util.spec_from_file_location('stylometry',ROOT/'.agents/skills/financial-persona-distillation/scripts/stylometry.py');style=importlib.util.module_from_spec(sp);sp.loader.exec_module(style)
ip=importlib.util.spec_from_file_location('ingest',ROOT/'scripts/import_corpus.py');ingest=importlib.util.module_from_spec(ip);ip.loader.exec_module(ingest)

def readjl(path):return [json.loads(l) for l in path.read_text().split('\n') if l]
def writej(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False))
def writejl(path,rows):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def metrics(y,p):
 pr,rec,f,_=precision_recall_fscore_support(y,p,average='macro',zero_division=0)
 return {'n':len(y),'accuracy':float(accuracy_score(y,p)),'macro_precision':float(pr),'macro_recall':float(rec),'macro_f1':float(f)}
def bootstrap(y,p):
 rng=np.random.default_rng(42);scores=[];y=np.asarray(y);p=np.asarray(p)
 for _ in range(250):
  idx=rng.integers(0,len(y),len(y));scores.append(accuracy_score(y[idx],p[idx]))
 return {'accuracy_95_percentile_interval':np.percentile(scores,[2.5,97.5]).tolist(),'method':'iid bootstrap of held-out rows; does not capture donor/thread dependence'}
def mask(text):return re.sub(r'\$[A-Z]{1,6}\b|https?://\S+|@[\w_]+',' ',text)
def distribution(values):
 arr=np.asarray(values,dtype=float)
 return {'n':len(arr),'mean':float(arr.mean()),'p10':float(np.percentile(arr,10)),'p50':float(np.percentile(arr,50)),'p90':float(np.percentile(arr,90))} if len(arr) else None
def silver_label(row):
 t=row['text'];c=row['classification']
 if row['post_type']=='repost' or ingest.AD.search(t) or c['signals']['promotion']:return 0,'explicit_repost_or_promotion'
 if ingest.LIFE.search(t) and not ingest.FINANCE.search(t):return 0,'explicit_lifestyle_without_finance_evidence'
 if re.search(r'财报|利润|估值|利率|流动性|持仓|营收|半导体|通胀|就业|\b(?:earnings|revenue|valuation|inflation|portfolio|yield|payroll|stocks|liquidity)\b',t,re.I) and len(t)>=80 and (bool(re.search(r'\d',t)) or ingest.MECH.search(t)):
  return 1,'financial_object_plus_substantive_numeric_or_mechanism_context'
 if len(t.strip())<18 and not ingest.FINANCE.search(t):return 0,'short_social_fragment_without_finance_object'
 return None,'insufficient_context_for_strict_rule_reference'

def main():
 started=time.monotonic();raw=readjl(ROOT/'data/raw_posts.jsonl');clean=[r for r in raw if r['classification']['keep']];manifest=json.loads((ROOT/'data/corpus_manifest.json').read_text())
 for r in raw:
  r['text']=r.get('analysis_text',r['text']);r['external_links']=r.get('analysis_external_links',r['external_links'])
 out=ROOT/'ml_experiments';out.mkdir(exist_ok=True);run_id=datetime.datetime.now(datetime.timezone.utc).strftime('ml-%Y%m%dT%H%M%S')
 trackio.init(project='financial-persona',name=run_id,config={'seed':42,'raw_count':len(raw),'clean_count':len(clean),'labels':'strict_rule_silver_not_human_gold'},space_id=None)
 features=[style.features(r['text']) for r in raw];feature_names=list(features[0]);sx=np.array([[v[n] for n in feature_names] for v in features])
 fhash=hashlib.sha256((ROOT/'data/raw_posts.jsonl').read_bytes()).hexdigest();cache=out/('embeddings-'+fhash[:16]+'.npz')
 if cache.exists():
  loaded=np.load(cache);emb=loaded['embeddings'];chunks=int(loaded['chunks']);device='cached'
 else:
  device='mps' if torch.backends.mps.is_available() else 'cpu';torch.set_num_threads(4)
  encoder=SentenceTransformer(str(ROOT/'.runtime/models/embedding'),device=device,local_files_only=True,trust_remote_code=False)
  parts=[];owners=[]
  for i,row in enumerate(raw):
   ids=encoder.tokenizer.encode(mask(row['text']),add_special_tokens=False)
   for j in range(0,max(len(ids),1),110):parts.append(encoder.tokenizer.decode(ids[j:j+110],skip_special_tokens=True));owners.append(i)
  vectors=encoder.encode(parts,batch_size=32,show_progress_bar=False,normalize_embeddings=True)
  emb=np.zeros((len(raw),vectors.shape[1]),dtype=np.float32);counts=np.zeros(len(raw))
  for i,v in zip(owners,vectors):emb[i]+=v;counts[i]+=1
  emb/=np.maximum(counts,1)[:,None];emb/=np.maximum(np.linalg.norm(emb,axis=1,keepdims=True),1e-12)
  chunks=len(parts);np.savez_compressed(cache,embeddings=emb,chunks=chunks)
  del encoder,vectors
  if torch.backends.mps.is_available():torch.mps.empty_cache()
 print(json.dumps({'stage':'embeddings_ready','rows':len(raw),'chunks':chunks,'device':device}),flush=True)
 writej(out/'embedding_manifest.json',{'run_id':run_id,'dataset_sha256':fhash,'model':json.loads((ROOT/'model-lock.json').read_text())['models'][1],'pooling':'mean of normalized 110-token chunks then L2 normalize','dimensions':int(emb.shape[1]),'chunks':chunks,'rows':len(raw),'cache':cache.name,'device':device})
 # A: 300 stratified rows, strict rules review; train excludes their threads and exact duplicates.
 rng=random.Random(42);by=collections.defaultdict(list)
 for i,r in enumerate(raw):by[r['source_account_id']].append(i)
 review=[]
 for handle,indices in by.items():review.extend(rng.sample(indices,min(30,len(indices))))
 if len(review)<300:review+=rng.sample([i for i in range(len(raw)) if i not in set(review)],300-len(review))
 review=review[:300]
 # Retain all first-pass abstentions, then add decisive strict-policy rows until >=300 can be scored.
 candidates=[i for i in range(len(raw)) if i not in set(review) and silver_label(raw[i])[0] is not None];rng.shuffle(candidates)
 decisive=sum(silver_label(raw[i])[0] is not None for i in review)
 for i in candidates:
  if decisive>=300:break
  review.append(i);decisive+=1
 review_rows=[]
 for i in review:
  label,reason=silver_label(raw[i]);review_rows.append({'post_id':raw[i]['post_id'],'url':raw[i]['url'],'author':raw[i]['source_account_id'],'created_at':raw[i]['created_at'],'text':raw[i]['text'],'rule_category':raw[i]['classification']['category'],'silver_finance_label':label,'review_method':'strict-rule-v1; not human','review_reason':reason,'reviewer':'deterministic_policy','human_label':'','confidence':'high_precision_policy_not_calibrated' if label is not None else 'abstain'})
 with (ROOT/'data/post_classification_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=list(review_rows[0]));writer.writeheader();writer.writerows(review_rows)
 groups={raw[i]['thread_id'] or raw[i]['post_id'] for i in review};dups={raw[i]['duplicate_group'] for i in review}
 train=[i for i,r in enumerate(raw) if i not in review and (r['thread_id'] or r['post_id']) not in groups and r['duplicate_group'] not in dups]
 test=[i for i in review if silver_label(raw[i])[0] is not None];y=[int(raw[i]['classification']['financial_relevant'] and raw[i]['post_type']!='repost') for i in train];yt=[silver_label(raw[i])[0] for i in test]
 char_model=make_pipeline(TfidfVectorizer(analyzer='char',ngram_range=(2,4),min_df=2,max_features=25000,sublinear_tf=True),LogisticRegression(max_iter=400,class_weight='balanced',random_state=42))
 char_model.fit([mask(raw[i]['text']) for i in train],y);pc=char_model.predict([mask(raw[i]['text']) for i in test])
 dense=LogisticRegression(max_iter=400,class_weight='balanced',random_state=42).fit(emb[train],y);pe=dense.predict(emb[test]);pr=[int(raw[i]['classification']['financial_relevant'] and raw[i]['post_type']!='repost') for i in test]
 a={'run_id':run_id,'reference':'Strict-policy reviewed rows, at least 300 decisive references; silver labels, not human gold','reviewed':len(review),'scored':len(test),'abstained':len(review)-len(test),'train_count':len(train),'training_labels':'rules-v2 weak labels','limitation':'Reference policy shares financial vocabulary with baseline; scores measure silver-label agreement, not independently established financial accuracy. Human audit remains required.','models':{'rules':metrics(yt,pr),'char_tfidf_logistic':metrics(yt,pc),'pretrained_embedding_logistic':metrics(yt,pe)},'interval':bootstrap(yt,pe),'llm_status':'pending actual model run','train_ids':[raw[i]['post_id'] for i in train],'test_ids':[raw[i]['post_id'] for i in test]}
 writej(out/'A_finance_classification.json',a)
 writejl(out/'A_predictions.jsonl',[{'post_id':raw[i]['post_id'],'reference':int(label),'rules':int(r),'tfidf':int(c),'embedding':int(e),'url':raw[i]['url'],'text':raw[i]['text']} for i,label,r,c,e in zip(test,yt,pr,pc,pe)])
 # B: author time split with entire threads and duplicate groups purged from training.
 cidx=[i for i,r in enumerate(raw) if r['classification']['keep']];test_idx=[];train_idx=[];split_details=[]
 for handle,indices in by.items():
  ix=[i for i in indices if i in cidx];ix.sort(key=lambda i:raw[i]['created_at']);cut=int(len(ix)*.8);ti=ix[cut:];tr=ix[:cut]
  tg={raw[i]['thread_id'] or raw[i]['post_id'] for i in ti};dg={raw[i]['duplicate_group'] for i in ti};tr=[i for i in tr if (raw[i]['thread_id'] or raw[i]['post_id']) not in tg and raw[i]['duplicate_group'] not in dg]
  eligible=len(tr)>=30 and len(ti)>=10
  split_details.append({'author':handle,'train':len(tr),'test':len(ti),'eligible':eligible,'last_train_time':max((raw[i]['created_at'] for i in tr),default=None),'first_test_time':min((raw[i]['created_at'] for i in ti),default=None)})
  if eligible:train_idx+=tr;test_idx+=ti
 all_test_groups={raw[i]['thread_id'] or raw[i]['post_id'] for i in test_idx};all_test_dups={raw[i]['duplicate_group'] for i in test_idx};train_idx=[i for i in train_idx if (raw[i]['thread_id'] or raw[i]['post_id']) not in all_test_groups and raw[i]['duplicate_group'] not in all_test_dups]
 author_y=[raw[i]['source_account_id'] for i in train_idx];author_test=[raw[i]['source_account_id'] for i in test_idx];classes=sorted(set(author_y));models={};preds={};style_model=None
 for name,array in [('stylometry',sx),('embedding',emb),('combined',np.hstack([sx,emb]))]:
  model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=600,class_weight='balanced',random_state=42));model.fit(array[train_idx],author_y);pred=model.predict(array[test_idx]);preds[name]=pred
  models[name]={**metrics(author_test,pred),'by_author':classification_report(author_test,pred,output_dict=True,zero_division=0),'confusion_matrix':confusion_matrix(author_test,pred,labels=classes).tolist()}
  if name=='stylometry':style_model=model
 majority=collections.Counter(author_y).most_common(1)[0][0];language_majority={l:collections.Counter(raw[i]['source_account_id'] for i in train_idx if raw[i]['language']==l).most_common(1)[0][0] for l in {raw[i]['language'] for i in train_idx}}
 pl=[language_majority.get(raw[i]['language'],majority) for i in test_idx];models['majority']=metrics(author_test,[majority]*len(test_idx));models['language_only']=metrics(author_test,pl)
 top=np.mean(np.abs(style_model[-1].coef_),axis=0);top_features=[{'feature':feature_names[i],'mean_abs_standardized_coefficient':float(top[i])} for i in np.argsort(top)[-12:][::-1]]
 b={'run_id':run_id,'split':'within-author chronological 80/20; whole-thread and exact-text duplicate purge; eligible train>=30 and test>=10','eligible_authors':classes,'excluded_or_included':split_details,'train_n':len(train_idx),'test_n':len(test_idx),'models':models,'top_stylometric_features':top_features,'interval':bootstrap(author_test,preds['combined']),'train_ids':[raw[i]['post_id'] for i in train_idx],'test_ids':[raw[i]['post_id'] for i in test_idx],'limitation':'Associational authorship; topic/time may still confound style. English authors excluded when saved corpus is too small.'}
 writej(out/'B_authorship.json',b);writejl(out/'B_predictions.jsonl',[{'post_id':raw[i]['post_id'],'url':raw[i]['url'],'actual_author':raw[i]['source_account_id'],'stylometry':str(preds['stylometry'][j]),'embedding':str(preds['embedding'][j]),'combined':str(preds['combined'][j])} for j,i in enumerate(test_idx)])
 # C: exploratory topic clusters on complete clean corpus, not held-out predictive performance.
 k=8;km=KMeans(n_clusters=k,random_state=42,n_init=10).fit(emb[cidx]);labels=km.labels_;points=PCA(n_components=2,random_state=42).fit_transform(emb[cidx]);topic_by={raw[i]['post_id']:int(l) for i,l in zip(cidx,labels)}
 vocab=['宏观','利率','流动性','通胀','就业','比特币','以太坊','稳定币','半导体','存储','芯片','英伟达','财报','估值','营收','利润','期权','仓位','风险','交易','AI','GPU','HBM','NVDA','QQQ','earnings','inflation','liquidity','semiconductor','portfolio']
 clusters=[]
 for cluster in range(k):
  members=[j for j,l in enumerate(labels) if l==cluster];idx=[cidx[j] for j in members];center=km.cluster_centers_[cluster];ex=sorted(idx,key=lambda i:float(emb[i]@center),reverse=True)[:6]
  terms=collections.Counter({v:sum(len(re.findall(re.escape(v),raw[i]['text'],re.I)) for i in idx) for v in vocab})
  clusters.append({'cluster_id':cluster,'count':len(idx),'label_terms':[t for t,n in terms.most_common(5) if n],'exemplar_post_ids':[raw[i]['post_id'] for i in ex],'donors':dict(collections.Counter(raw[i]['source_account_id'] for i in idx))})
 writej(ROOT/'topic_clusters/clusters.json',{'run_id':run_id,'method':'KMeans on frozen pretrained multilingual embeddings; all-corpus exploratory','k':k,'silhouette_cosine':float(silhouette_score(emb[cidx],labels,metric='cosine',sample_size=min(1000,len(cidx)),random_state=42)),'clusters':clusters})
 writejl(ROOT/'topic_clusters/assignments.jsonl',[{'post_id':raw[i]['post_id'],'donor':raw[i]['source_account_id'],'cluster':int(l),'x':float(p[0]),'y':float(p[1])} for i,l,p in zip(cidx,labels,points)])
 # Profiles and observed topic drift, each with original post IDs.
 profile_refs={};topic_distributions={};style_centers={};donor_ids={}
 for donor in manifest['donors']:
  handle=donor['handle'];ri=by[handle];ci=[i for i in ri if raw[i]['classification']['keep']];posts=[raw[i] for i in ci];donor_ids[handle]=[r['post_id'] for r in posts]
  sf={name:distribution([features[i][name] for i in ci]) for name in feature_names};style_centers[handle]=np.mean(sx[ci],axis=0).tolist() if ci else None
  media=[raw[i] for i in ri if raw[i]['media_type'] is not None]
  writej(ROOT/'style_profiles'/f'{handle}.json',{'donor':handle,'method':'deterministic stylometry-v1','sample_n':len(ci),'sample_post_ids':donor_ids[handle],'features':sf,'media_usage':{'known_denominator':len(media),'has_media_rate':sum(bool(p['media_type']) for p in media)/len(media) if media else None,'chart_rate':None,'note':'Media presence does not prove a financial chart; unavailable fields stay unknown.'},'language':dict(collections.Counter(r['language'] for r in posts)),'phrase_migration_policy':'Do not copy signatures or advertisements','status':donor['status']})
  ordered=sorted([raw[i] for i in ri],key=lambda r:r['created_at']);dates=[datetime.datetime.fromisoformat(r['created_at']) for r in ordered];intervals=[(b-a).total_seconds()/3600 for a,b in zip(dates,dates[1:])];days=collections.Counter(d.date().isoformat() for d in dates);weekends=sum(d.weekday()>=5 for d in dates)
  theme_lens={str(c):distribution([len(r['text']) for r in posts if topic_by[r['post_id']]==c]) for c in range(k)}
  habit={'donor':handle,'observed_items':len(ri),'post_ids':[r['post_id'] for r in ordered],'time_basis':'UTC; author local timezone unknown','interval_hours':distribution(intervals),'weekend_post_share':weekends/max(len(dates),1),'busiest_observed_days':days.most_common(5),'post_types':donor['post_types'],'theme_length':theme_lens,'topic_switch_rate':None,'reaction_latency':None,'acknowledges_errors':None,'updates_old_views':None,'missing_behavior_reason':'Incomplete timeline and event alignment; absence is not evidence of silence or failure to correct.','unknown_gaps':'Intervals describe observed records, not all activity.'}
  ordered_topics=[topic_by[r['post_id']] for r in ordered if r['post_id'] in topic_by];habit['topic_switch_rate']=sum(a!=b for a,b in zip(ordered_topics,ordered_topics[1:]))/max(len(ordered_topics)-1,1)
  writej(ROOT/'content_habit_profiles'/f'{handle}.json',habit)
  patterns={'macro_liquidity':r'流动性|利率|通胀|非农|\bliquidity|inflation|payroll|yield\b','equity_industry':r'半导体|芯片|营收|估值|\bearnings|revenue|semiconductor|HBM|GPU\b','risk_process':r'仓位|止损|回撤|风险|预期|\brisk|position|drawdown|stop loss\b','conditional_reasoning':r'如果|取决于|因为|可能|\bif|depends|because|could\b'}
  evidence_features=[{'feature':key,'support_count':sum(bool(re.search(p,r['text'],re.I)) for r in posts),'support_post_ids':[r['post_id'] for r in posts if re.search(p,r['text'],re.I)][:30],'interpretation':'observed textual pattern; not verified expertise'} for key,p in patterns.items()]
  entities=collections.defaultdict(list)
  for r in posts:
   for ent in set(re.findall(r'\$[A-Z]{1,6}\b|\b(?:NVDA|QQQ|HBM|GPU|BTC|ETH|MU|ALAB|AMD|TSLA|AMZN)\b|英伟达|美联储|比特币|半导体|存储',r['text'])):entities[ent].append(r['post_id'])
  shared=collections.defaultdict(list)
  for r in posts:
   for url in r['external_links']:
    if 't.co/' not in url:shared[url.split('?')[0]].append(r['post_id'])
  knowledge={'donor':handle,'sample_n':len(posts),'features':evidence_features,'frequent_entities':[{'entity':e,'count':len(ids),'post_ids':ids[:12]} for e,ids in sorted(entities.items(),key=lambda x:len(x[1]),reverse=True)[:20]],'observed_sources':[{'url':url,'post_ids':ids[:10]} for url,ids in sorted(shared.items(),key=lambda x:len(x[1]),reverse=True)[:20]],'framework_status':'hypotheses derived from observable language; model enrichment separate','claims_verified_or_falsified':None,'knowledge_boundary':'not inferred beyond linked samples','excluded_migration':['advertisements','self-reported returns','unsupported certainty','signature expressions'],'time_horizon':{'short_term_post_ids':[r['post_id'] for r in posts if re.search(r'今日|今天|盘前|盘后|日内|\btoday|intraday\b',r['text'],re.I)][:20],'long_term_post_ids':[r['post_id'] for r in posts if re.search(r'长期|周期|未来几年|\blong.term|cycle\b',r['text'],re.I)][:20]},'risk_post_ids':[r['post_id'] for r in posts if re.search(patterns['risk_process'],r['text'],re.I)][:30],'causal_candidate_post_ids':[r['post_id'] for r in posts if ingest.MECH.search(r['text'])][:30]}
  writej(ROOT/'knowledge_profiles'/f'{handle}.json',knowledge)
  dist=np.array([sum(topic_by[r['post_id']]==c for r in posts) for c in range(k)],dtype=float);dist=(dist+1e-9)/(dist.sum()+k*1e-9);topic_distributions[handle]=dist
  pivot=max(dates)-datetime.timedelta(days=30) if dates else datetime.datetime.now(datetime.timezone.utc);earlier=[r for r in posts if datetime.datetime.fromisoformat(r['created_at'])<pivot];later=[r for r in posts if datetime.datetime.fromisoformat(r['created_at'])>=pivot]
  def td(rs):
   x=np.array([sum(topic_by[r['post_id']]==c for r in rs) for c in range(k)],dtype=float)+1e-9;return x/x.sum()
  profile_refs[handle]={'clean_n':len(posts),'topic_distribution':dist.tolist(),'earlier_n':len(earlier),'last30d_n':len(later),'topic_drift_js_distance':float(jensenshannon(td(earlier),td(later))) if len(earlier)>=10 and len(later)>=10 else None,'current_topic_support':[r['post_id'] for r in later[-10:]]}
 writej(ROOT/'topic_clusters/donor_distributions.json',profile_refs)
 # Self-similarity measured among same-topic, separated-time real posts.
 within=[];between=[];pairs=[];random.seed(42)
 for i in cidx:
  matching=[j for j in cidx if j!=i and topic_by[raw[j]['post_id']]==topic_by[raw[i]['post_id']] and abs((datetime.datetime.fromisoformat(raw[j]['created_at'])-datetime.datetime.fromisoformat(raw[i]['created_at'])).days)>=7]
  same=[j for j in matching if raw[j]['source_account_id']==raw[i]['source_account_id']];other=[j for j in matching if raw[j]['source_account_id']!=raw[i]['source_account_id']]
  if same and other:
   j=random.choice(same);z=random.choice(other);within.append(float(emb[i]@emb[j]));between.append(float(emb[i]@emb[z]));pairs.append({'anchor':raw[i]['post_id'],'same_author':raw[j]['post_id'],'other_author':raw[z]['post_id'],'within_cosine':within[-1],'between_cosine':between[-1]})
  if len(pairs)>=240:break
 writej(out/'self_similarity.json',{'method':'matched unsupervised topic; >=7 days apart; frozen semantic encoder; semantic not pure stylistic similarity','pair_count':len(pairs),'within_author':distribution(within),'between_author':distribution(between),'universal_ceiling':None,'pairs':pairs})
 compatibility=[]
 for a1 in by:
  for b1 in by:
   if a1>=b1:continue
   cosine=float(np.mean(emb[[i for i in by[a1] if i in cidx]],axis=0)@np.mean(emb[[i for i in by[b1] if i in cidx]],axis=0)) if donor_ids[a1] and donor_ids[b1] else None
   shared_urls=set(u.split('?')[0] for i in by[a1] for u in raw[i]['external_links'] if 't.co/' not in u)&set(u.split('?')[0] for i in by[b1] for u in raw[i]['external_links'] if 't.co/' not in u)
   compatibility.append({'donor_a':a1,'donor_b':b1,'topic_js_distance':float(jensenshannon(topic_distributions[a1],topic_distributions[b1])),'mean_cross_post_dot':cosine,'shared_resolved_urls':sorted(shared_urls),'sufficient_samples':len(donor_ids[a1])>=150 and len(donor_ids[b1])>=150,'decision':'editorial review required; distance alone is not complementarity'})
 writej(ROOT/'donor_compatibility_matrix.json',compatibility)
 summary={'run_id':run_id,'dataset_sha256':fhash,'raw':len(raw),'clean':len(clean),'reviewed_rows':len(review),'silver_scored':len(test),'eligible_authors':classes,'classification':a['models'],'authorship':{n:{k:v for k,v in m.items() if k not in ['by_author','confusion_matrix']} for n,m in models.items()},'duration_seconds':round(time.monotonic()-started,2),'human_validation':False}
 trackio.log({'raw_count':len(raw),'clean_count':len(clean),'silver_reference_n':len(test),'finance_embedding_silver_macro_f1':a['models']['pretrained_embedding_logistic']['macro_f1'],'author_style_macro_f1':models['stylometry']['macro_f1'],'author_embedding_macro_f1':models['embedding']['macro_f1'],'author_combined_macro_f1':models['combined']['macro_f1']});trackio.finish()
 writej(out/'run_summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
