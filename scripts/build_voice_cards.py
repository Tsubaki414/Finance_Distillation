#!/usr/bin/env python3
"""Build all cluster voice cards offline from an external donor corpus."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from live.voice_cards import build_cards, write_cards

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--posts-dir',type=Path,required=True)
    p.add_argument('--tags-dir',type=Path,required=True)
    p.add_argument('--roster',type=Path,default=Path('live/donors/roster.json'))
    p.add_argument('--out',type=Path,default=Path('live/personas/voice_cards'))
    a=p.parse_args(argv)
    write_cards(build_cards(a.posts_dir,a.tags_dir,a.roster),a.out)
    return 0
if __name__=='__main__': sys.exit(main())
