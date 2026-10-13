"""Oct 13: MEME_TIE's second alternative (market cap ... before $TICKER) left group(1) None and crashed lane_hits."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live import lane_fit


def test_cap_before_ticker_does_not_crash():
    hits = lane_fit.lane_hits('crypto_meme', 'its market cap jumped while $ABC rallied')
    assert any(h.startswith('$ticker+market') for h in hits)


def test_ticker_before_cap_unchanged():
    hits = lane_fit.lane_hits('crypto_meme', '$CRH 市值竟然才刚刚突破 100 万美元')
    assert '$ticker+市值' in hits


def test_zh_cap_before_ticker():
    assert lane_fit.lane_hits('crypto_meme', '这个币流动性很差，$PEPE 拉了一下')
