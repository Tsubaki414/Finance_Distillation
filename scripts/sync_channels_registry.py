"""Idempotently register planned channels and their explicit licence restrictions."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from live.adapters.channels import load_channels

def sync(channels_path, registry_path, licence_path):
    rows=load_channels(channels_path)
    registry_path,licence_path=Path(registry_path),Path(licence_path)
    registry=json.loads(registry_path.read_text()); licence=json.loads(licence_path.read_text())
    planned={c['channel_id']:c for c in rows}
    registry['sources']=[r for r in registry['sources'] if r.get('id') not in planned]
    for c in rows:
        cid=c['channel_id']
        if c['mode']=='excluded':
            licence['tiers'].pop(cid,None)
            continue
        registry['sources'].append({'id':cid,'name':c['name'],'type':'channel','enabled':True,
            'adapter':'channel:'+c['mode'],'mode':c['mode'],'url':c['url'],'feed_url':c.get('feed_url'),
            'lang':c['lang'],'persona_hint':c.get('persona_hint'),'reason':c.get('reason','')})
        licence['tiers'][cid]={'tier':c['licence_tier'],'basis':c.get('reason','') or 'planned public channel',
            'aliases':[c['name']],'no_reproduction':bool(c.get('no_reproduction')),
            'quote_allowed':c['licence_tier']=='A' and not c.get('no_reproduction'), 'attribution_required':True}
    for path,value in ((registry_path,registry),(licence_path,licence)):
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--channels',type=Path,default=ROOT/'live/channels.json')
    ap.add_argument('--registry',type=Path,default=ROOT/'live/source_registry.json')
    ap.add_argument('--licence',type=Path,default=ROOT/'live/source_licence.json')
    args=ap.parse_args(); sync(args.channels,args.registry,args.licence)
if __name__=='__main__': main()
