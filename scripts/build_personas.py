import json
from model_client import ROOT
def main():
 specs=[('macro','流动性观察员',['phyrexni','qinbafrank','michael_qqq2025'],'先辨认数据修订与方向，再解释政策预期的条件；避免用单月数据断言降息。','revision → labor demand → policy uncertainty'),('industry','产业证据研究员',['aleabitoreddit','kovainvest','xingpt'],'从实体需求和行业差异切入，区分就业数据与公司营收证据；不能从总量数据推出特定股票结论。','sector composition → demand transmission → evidence gap'),('risk','情景与风险编辑',['kovainvest','michael_qqq2025','qinbafrank'],'并列基准与反例，先写什么会推翻判断，再列下次核验条件，不编造仓位与交易。','alternative explanations → falsification → next check')]
 dest=ROOT/'personas';dest.mkdir(exist_ok=True)
 for pid,name,donors,description,angle in specs:
  roles={'knowledge':dict(zip(donors,[.5,.3,.2])),'reasoning':dict(zip(donors,[.3,.5,.2])),'language':dict(zip(donors,[.2,.3,.5])),'habit':dict(zip(donors,[.4,.3,.3])),'visual':{}}
  profiles={h:json.loads((ROOT/'style_profiles'/f'{h}.json').read_text()) for h in donors}
  keys=['sentence_length_mean','paragraph_count','question_density','hedge_density','number_density']
  actualkeys=list(profiles[donors[0]]['features']);keys=[k for k in actualkeys if any(s in k for s in ['sentence','paragraph','hedge','question','number','conclusion','evidence'])]
  style={k:sum(roles['language'][h]*profiles[h]['features'][k]['mean'] for h in donors) for k in keys}
  d={'id':pid,'name':name,'donors':donors,'description':description,'analysis_angle':angle,'roles':roles,'weights_origin':'editorial hypothesis; not learned or proven optimal','measured_style_targets':style,'sample_counts':{h:profiles[h]['sample_n'] for h in donors},'profile_refs':{h:{kind:f'{kind}/{h}.json' for kind in ['knowledge_profiles','style_profiles','content_habit_profiles']} for h in donors},'visual_policy':'unassigned donor role: original chart sourced from primary evidence','english_style_status':'provisional transfer; English donor corpus insufficient','banned':['copied signature phrases','claimed trades','advertising','unverified performance'],'validation':'pending generation ablation and human blind review'}
  (dest/f'{pid}.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
 print('Created 3 provisional, separately weighted personas from measured profiles.')
if __name__=='__main__':main()
