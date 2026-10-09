"""Oct 9: FD_ENGAGE reply / quote targets (x-<status id>) get tier B, only as the reply / quote itself."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live import registry  # noqa: E402


def test_engage_target_gets_writable_tier_only_as_reply_or_quote():
    assert registry.engagement_licence_tier('x-2108409849843499222', {'engage': 'reply'}) == 'B'
    assert registry.engagement_licence_tier('x-2108409849843499222', {'engage': 'quote'}) == 'B'
    assert 'B' in registry.WRITABLE_TIERS


def test_engage_post_as_standalone_or_other_sources_stay_unlicensed():
    assert registry.engagement_licence_tier('x-2108409849843499222', {'type': 'long_take'}) is None
    assert registry.engagement_licence_tier('x-2108409849843499222', None) is None
    assert registry.engagement_licence_tier('x_WuBlockchain', {'engage': 'reply'}) is None   # C watchlist stays C
    assert registry.engagement_licence_tier('ch142_wscn_global', {'engage': 'quote'}) is None
    assert registry.source_licence_tier('x-2108409849843499222') is None


def test_b_tier_post_types_exist_for_engagement():
    assert registry.post_types_for_tier(registry.ENGAGE_TIER)
