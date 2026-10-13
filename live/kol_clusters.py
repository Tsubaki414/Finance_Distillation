"""KOL clusters (Oct 13, aixbt P1 'cross-cluster spread > one cluster repeating').

live/kol_clusters.json labels each X source / watchlist handle with one type (macro_research, sell_side, onchain,
traders, media, zh_community). A hotspot 母题 counts the DISTINCT clusters among its members (X member -> the
handle's label, unlabelled X handles are not counted; any non-X material -> media) and live/hotspot.py adds
FD_KOL_CLUSTER_W (default 0.8, 0 = off) * log2(1 + clusters) to breadth, next to the publisher (author) count."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'kol_clusters.json'


@lru_cache(maxsize=1)
def labels():
    try:
        return {k.lower(): v for k, v in json.loads(PATH.read_text()).get('labels', {}).items()}
    except (OSError, ValueError):
        return {}


def weight(env=None):
    try:
        return max(0.0, float((env if env is not None else os.environ).get('FD_KOL_CLUSTER_W', '0.8')))
    except ValueError:
        return 0.8


def cluster_of(material):
    adapter = str(material.get('adapter') or '')
    if adapter.startswith('x:'):
        return labels().get(adapter[2:].lower().lstrip('@'))
    return 'media'


def clusters(materials):
    return sorted({c for c in (cluster_of(m) for m in materials) if c})
