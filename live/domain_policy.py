"""Small policy values and two built-ins; no discovery framework or agent registry."""
from dataclasses import dataclass,field
from typing import Callable
import re
from live.numeric_fidelity import compare
from live.distillation_source import digest
from live import finance_policy
from live.fidelity import segment_language_matches


def generic_checks(source,passages,segments,target_language,stage,detector,frame=None):
    # frame: rendered post_type attribution frame; only removed for the provenance check.
    from live.attribution_frame import strip_segments
    findings=[]
    for passage,segment,body in zip(passages,segments,strip_segments(segments,frame)):
        original,output=passage['exact_text'],segment['text']
        def flag(code,detail):findings.append({'paragraph_id':passage['paragraph_id'],'stage':stage,'code':code,'detail':detail})
        if not segment_language_matches(original,output,target_language,'\n\n'.join(s['text'] for s in segments),detector):flag('wrong_or_uncertain_language','Language not established for target account')
        if re.search(r'^(?:I (?:cannot|can\x27t|am unable)|Sorry[,，]|抱歉|对不起|无法生成)',output.strip(),re.I):flag('refusal_prose','Refusal is not a draft')
        for entity,translated in source.get('entity_glossary',{}).items():
            if entity in original and translated.casefold() not in output.casefold():flag('entity_glossary','Missing entity: '+translated)
        if re.search(r'https?://|(?:^|\n)(?:来源|出处|译自|Source|Translated from)\s*[:：]',body,re.I):flag('provenance_in_body','Unrequested provenance in body')
        if re.search(r'link in (?:bio|profile)|use code|join our paid|领取邀请码|扫码加群',output,re.I):flag('promotion','Promotion survives into draft')
        numeric,_=compare(original,output,source=source)
        for item in numeric:flag(item['code'],item['detail'])
    return findings


@dataclass(frozen=True)
class DomainPolicy:
    id:str
    version:str
    review_guidance:str=''
    metric_aliases:dict=field(default_factory=dict)
    extra_checks:Callable|None=None

    @property
    def fingerprint(self):
        return digest([self.id,self.version,self.review_guidance,self.metric_aliases])

    def numeric(self,original,output,source=None):
        return compare(original,output,metric_aliases=self.metric_aliases,source=source)

    def deterministic(self,source,passages,segments,target_language,stage,detector,frame=None):
        # Domain hooks are additive. An empty extension cannot disable generic
        # language, numeric, provenance or entity checks.
        rows=generic_checks(source,passages,segments,target_language,stage,detector,frame=frame)
        if self.extra_checks:
            rows+=self.extra_checks(source,passages,segments,target_language,stage,detector=detector,**({'frame':frame} if frame else {}))
        unique={}
        for row in rows:unique.setdefault((row['paragraph_id'],row['stage'],row['code']),row)
        return list(unique.values())


GENERIC=DomainPolicy('generic','generic-fidelity-v3-compound-units-time-anchors')
FINANCE=DomainPolicy('finance','finance-fidelity-v3-compound-units-time-anchors',finance_policy.REVIEW_GUIDANCE,
                     finance_policy.METRIC_ALIASES,finance_policy.deterministic)


def policies(extra=()):
    result={p.id:p for p in (GENERIC,FINANCE)}
    for policy in extra:result[policy.id]=policy
    return result


def account_domain(row):
    # No persona or keyword inference. Only known old account IDs get the
    # compatibility default. A new domain must choose its policy explicitly.
    return row.get('domain') or ('finance' if row.get('id') in finance_policy.LEGACY_ACCOUNT_IDS else 'generic')
