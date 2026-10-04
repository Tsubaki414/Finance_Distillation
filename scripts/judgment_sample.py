"""Offline judgment samples; --relay explicitly enables the configured relay."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import compose, content_units, registry
from live.content_store import ContentStore
from live.distillation_source import digest
from live.stance import stance_step


class FakeClient:
    """Deterministic demonstration, never a semantic research substitute."""
    def __init__(self, source=None):
        self.source = source or {}

    def __call__(self, stage, messages, max_tokens):
        p=json.loads(messages[-1]['content'])
        if stage=='extract':
            units=self.source.get('units')
            if units is None:
                spans=[{'paragraph_id':r['paragraph_id'],'exact_text':r['text']} for r in p['paragraphs']]
                units=[]
                for kind in ('fact','view'):
                    u={'kind':kind,'statement':spans[0]['exact_text'],'source_spans':spans[:1], 'numbers':[],
                       'speaker':self.source.get('author_name') or 'Research author','speaker_type':'author','freshness_class':'current'}
                    if kind=='view':
                        u['view']={'direction':'neutral','subject':self.source.get('title') or 'Source thesis', 'conviction':'low',
                                   'reasoning':[spans[0]['exact_text'][:200]],'horizon':'unspecified',
                                   'conditions':'Offline demonstration; research interpretation requires review.'}
                    units.append(u)
            value={'units':units}
        elif stage=='stance':
            en=p['persona']['lang']=='en'
            value={'decision':'take','account_view':'The evidence warrants a cautious stance.' if en else '判断应保持谨慎，现有证据不足以支撑强烈预期。',
                   'supporting_unit_ids':[p['unit']['unit_id']], 'rationale':'Offline illustrative adoption.', 'confidence':.4}
        else:
            facts=[u for u in p['units'] if u['kind']=='fact']
            value={'body':p['stance']['account_view']+' '+ ' '.join(u['statement'] for u in facts),
                   'claim_ledger':[{'claim':u['statement'],'unit_id':u['unit_id'],'span_ref':0} for u in facts]}
        return {'text':json.dumps(value,ensure_ascii=False),'finish_reason':'stop','model':'offline-demo'}


def run_samples(store, accounts, n, output, *, source_json=None, relay=False):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    rows=ContentStore(store).units()
    source=json.loads(Path(source_json).read_text()) if source_json else None
    client=FakeClient(source)
    if relay:
        from live.distillation_client import RelayClient
        client=RelayClient(output/'calls')
    if not any(r['unit'].get('view') for r in rows) and source:
        source.setdefault('source_hash',digest(source['original_text']))
        tier=registry.source_licence_tier(source.get('source_id'))
        extracted=content_units.extract(source,client,licence_tier=tier)
        rows=[{'unit':u,'source':source,'tag_personas':[]} for u in extracted['units']]
    results=[]
    for account in accounts:
        persona=registry.persona_for_account(account)
        candidates=[r for r in rows if r['unit'].get('view') and
                    (not r.get('persona_tags') or persona.persona_id in r.get('tag_personas',[]))]
        for row in candidates[:n]:
            u=row['unit']; stance=stance_step(u,persona,client)
            facts=[r['unit'] for r in rows if r['unit']['kind']=='fact' and r['unit']['source_hash']==u['source_hash']]
            draft=compose.compose_source(row['source'],account,client,post_type='judgment_take',exemplars=False,
                                         extracted_units=[u,*facts],stance_output=stance)
            results.append({'account_id':account,'unit':u,'stance':stance,'account_view':stance['account_view'],
                            'draft':draft.get('text',''),'post_checks':draft['post_checks']})
    (output/'samples.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    (output/'samples.md').write_text('\n\n'.join(f"## {r['account_id']} / {r['unit']['unit_id']}\n\nDecision: {r['stance']['decision']}\n\n{r['account_view']}\n\n{r['draft']}\n\nChecks: {json.dumps(r['post_checks'],ensure_ascii=False)}" for r in results)+'\n')
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',required=True); p.add_argument('--persona-account',nargs='+',required=True)
    p.add_argument('--n',type=int,default=2); p.add_argument('--output',required=True)
    p.add_argument('--source-json'); p.add_argument('--relay',action='store_true')
    a=p.parse_args(); run_samples(a.store,a.persona_account,a.n,a.output,source_json=a.source_json,relay=a.relay)

if __name__=='__main__': main()
