#!/usr/bin/env python3
"""Remove personal position/trade tendencies from saved voice cards offline."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live.voice_cards import sanitize_card


def main():
    directory = Path(__file__).resolve().parents[1] / 'live/personas/voice_cards'
    paths = sorted(directory.glob('*.json'))
    for path in paths:
        card = sanitize_card(json.loads(path.read_text()))
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
    print(f'Sanitized {len(paths)} voice cards')


if __name__ == '__main__':
    main()
