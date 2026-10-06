#!/usr/bin/env python3
"""Run the daily free-source ingestion pipeline."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live.daily_ingest import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',type=Path,default=Path('live/store/content_units'))
    parser.add_argument('--runs-dir',type=Path,default=Path('/workspace/x/ingest_runs'))
    parser.add_argument('--inbox',type=Path,default=Path('/workspace/x/ingest_inbox'))
    parser.add_argument('--cost-cap-usd',type=float,default=8.0)
    parser.add_argument('--channel-timeout',type=float,default=90)
    parser.add_argument('--max-extract',type=int,default=40)
    parser.add_argument('--max-source-chars',type=int,default=5000)
    parser.add_argument('--per-channel-max',type=int,default=2)
    parser.add_argument('--fair-share-floor',type=int,default=2,help='paid extracts per persona (fewest fresh first) before the rest')
    parser.add_argument('--extract-model',default=None,help='relay model for EXTRACT only (default: stage_models.json "extract")')
    parser.add_argument('--no-persona-minimum',dest='persona_minimum',action='store_false',help='no persona_minimum slots in the budget window')
    parser.add_argument('--allow-nondefault-extract-model',action='store_true',help='explicit opt-in for a non-default --extract-model')
    # v10 (Oct 6, Fiona approved): 7x24 flashes on a ring-fenced budget inside --cost-cap-usd; tier-C headline leads.
    parser.add_argument('--flash-budget-usd',type=float,default=1.75,help='ring-fenced flash budget inside the cap (0 = no flashes extracted)')
    parser.add_argument('--flash-batch-size',type=int,default=20)
    parser.add_argument('--flash-max',type=int,default=150,help='flashes extracted per run at most')
    parser.add_argument('--flash-window-hours',type=float,default=26)
    parser.add_argument('--flash-dedupe-hours',type=float,default=6,help='same event across outlets within N hours = one flash')
    parser.add_argument('--no-flashes',dest='flashes',action='store_false')
    parser.add_argument('--no-news-leads',dest='news_leads',action='store_false')
    parser.add_argument('--no-dashboard',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--only',nargs='+')
    args=parser.parse_args()
    if args.cost_cap_usd<0 or args.channel_timeout<=0 or args.max_extract<0:
        parser.error('cap and max-extract must be nonnegative; timeout must be positive')
    result=run(**vars(args));print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result['status']=='backup_failed' else 0


if __name__=='__main__':sys.exit(main())
