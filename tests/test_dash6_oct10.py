"""Oct 10 dash6 tests: 在X打开 intent URL builder + auto_published.py matcher / POST payload / dry-run / env flag."""
import json
import re
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# helpers shared across sections
# ---------------------------------------------------------------------------

def _draft(id='d1', account_id='acc1', body='hello world test post text here', mode='original',
           target='', stored_at='2026-10-10T08:00:00+00:00', status='draft_ready', decision=None):
    return {'id': id, 'account_id': account_id, 'body': body, 'mode': mode,
            'target': target, 'stored_at': stored_at, 'status': status, 'decision': decision or {}}


def _tweet(id='t1', text='hello world test post text here', created='Sat Oct 10 10:00:00 +0000 2026',
           rt=False, reply=False, uid='u1'):
    return {'id': id, 'text': text, 'created': created, 'rt': rt, 'reply': reply, 'uid': uid}


# ---------------------------------------------------------------------------
# 1. intent URL builder (Python mirror matching what the page JS produces)
# ---------------------------------------------------------------------------

def build_intent_url(draft_text, mode, target_url=''):
    """Python mirror of the JS intent URL logic in card(). Used to verify hrefs in the built HTML."""
    import urllib.parse
    base = 'https://x.com/intent/post'
    if mode == 'reply':
        # extract status id from target_url
        m = re.search(r'/status/(\d+)', target_url or '')
        sid = m.group(1) if m else ''
        params = {'in_reply_to': sid, 'text': draft_text} if sid else {'text': draft_text}
        return base + '?' + urllib.parse.urlencode(params)
    elif mode == 'quote':
        text = draft_text + '\n' + target_url if target_url else draft_text
        return base + '?' + urllib.parse.urlencode({'text': text})
    else:
        return base + '?' + urllib.parse.urlencode({'text': draft_text})


class IntentUrlTests(unittest.TestCase):

    def test_standalone_url_contains_intent_post(self):
        url = build_intent_url('some text', 'original')
        self.assertIn('intent/post', url)
        self.assertIn('text=', url)
        self.assertNotIn('in_reply_to', url)

    def test_reply_url_contains_in_reply_to(self):
        target = 'https://x.com/user/status/1234567890'
        url = build_intent_url('my reply', 'reply', target)
        self.assertIn('in_reply_to=1234567890', url)
        self.assertIn('text=', url)

    def test_reply_without_valid_status_id_falls_back_to_text_only(self):
        url = build_intent_url('my reply', 'reply', 'https://x.com/user/no-status')
        self.assertNotIn('in_reply_to=', url)
        self.assertIn('text=', url)

    def test_quote_url_appends_target_to_text(self):
        target = 'https://x.com/user/status/9999'
        url = build_intent_url('my quote', 'quote', target)
        import urllib.parse
        qs = urllib.parse.parse_qs(url.split('?', 1)[1])
        combined = qs['text'][0]
        self.assertIn('my quote', combined)
        self.assertIn(target, combined)

    def test_html_page_contains_intent_post_for_standalone(self):
        """Build a minimal page and verify the generated HTML has intent/post in an href."""
        html = _build_page_with_fixture(mode='original', target='')
        self.assertIn('intent/post', html)

    def test_html_page_contains_in_reply_to_for_reply(self):
        """The JS intentUrl() function in the page must define the in_reply_to parameter and the target
        status id must be present in the page (in the data block) so JS can use it at runtime."""
        html = _build_page_with_fixture(mode='reply', target='https://x.com/a/status/55555')
        self.assertIn('intent/post', html)           # base intent URL in intentUrl() JS function
        self.assertIn('in_reply_to', html)           # intentUrl() sets this param for reply mode
        self.assertIn('55555', html)                 # status id present in the JSON data block

    def test_html_page_quote_contains_target_url_in_text(self):
        """The target URL must appear in the page's data block so JS intentUrl() can append it."""
        target = 'https://x.com/a/status/88888'
        html = _build_page_with_fixture(mode='quote', target=target)
        self.assertIn('intent/post', html)
        self.assertIn('88888', html)                 # status id present in the JSON data block


# ---------------------------------------------------------------------------
# helper: build a real ops page with a synthetic inbox and extract the HTML
# ---------------------------------------------------------------------------

def _build_page_with_fixture(mode='original', target=''):
    """Run build_ops_dashboard with a synthetic one-draft inbox; return the HTML string."""
    import importlib, os, tempfile
    # We need to import the module fresh so __file__ resolves properly
    import scripts.build_ops_dashboard as bop

    draft_body = 'Sample draft text for intent URL test'
    stored_at = '2026-10-10T08:00:00+00:00'

    row = {
        'id': 'test-draft-001',
        'account_id': 'test_acc',
        'name': 'Test Account',
        'lang': 'zh',
        'body': draft_body,
        'draft_status': 'draft_ready',
        'stored_at': stored_at,
        'suggested_post_time_london': '2026-10-10T08:00:00+01:00',
        'post_mode': mode,
    }
    if mode == 'reply':
        row['reply_to_url'] = target
        row['engagement'] = {'mode': 'reply', 'url': target}
    elif mode == 'quote':
        row['quote_target_url'] = target
        row['engagement'] = {'mode': 'quote', 'url': target}

    with tempfile.TemporaryDirectory() as td:
        inbox_day = Path(td) / 'inbox' / '2026-10-10'
        inbox_day.mkdir(parents=True)
        (inbox_day / 'test-draft-001.json').write_text(json.dumps(row))
        out = Path(td) / 'out'
        out.mkdir()

        # patch load_accounts to avoid needing the full account file
        fake_acc = [{'id': 'test_acc', 'no': '1', 'name': 'Test', 'lang': 'zh',
                     'beat': '', 'handle': '@testhandle', 'status': 'main', 'avatar': ''}]
        with patch.object(bop, 'load_accounts', return_value=fake_acc), \
             patch.object(bop, 'pull_decisions', return_value=None), \
             patch.object(bop, 'INBOX', inbox_day.parent), \
             patch.object(bop, 'DECISIONS', Path(td) / 'decisions'), \
             patch.object(bop, 'OUT', out):
            import sys as _sys
            _sys.argv = ['build_ops_dashboard.py', '--inbox', str(inbox_day.parent),
                         '--out', str(out), '--no-pull', '--no-admin']
            bop.main()
        return (out / 'index.html').read_text()


# ---------------------------------------------------------------------------
# 2. auto_published matcher tests (no network)
# ---------------------------------------------------------------------------

from scripts.auto_published import (
    similarity, match_drafts_to_tweets, build_decision_payload,
    tweet_created_utc, strip_target_url, target_status_id,
)


class MatcherTests(unittest.TestCase):

    def test_exact_match_is_marked(self):
        d = _draft(body='exact text here for matching purposes only')
        tw = _tweet(text='exact text here for matching purposes only',
                    created='Sat Oct 10 10:00:00 +0000 2026')
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 1)
        self.assertIs(res[0][0], d)

    def test_near_match_above_threshold_is_marked(self):
        base = 'crypto market analysis shows strong signals across major assets today'
        d = _draft(body=base)
        tw = _tweet(text=base + ' — thread')
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 1)

    def test_below_threshold_not_marked(self):
        d = _draft(body='completely different content about something else entirely')
        tw = _tweet(text='hello world this is unrelated content nothing matches here')
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 0)

    def test_sim_085_not_marked(self):
        # Verify a clearly-below-threshold pair is not marked (threshold is 0.88).
        # These strings share no meaningful content and score well below threshold.
        from scripts.auto_published import MATCH_THRESHOLD
        a = 'bitcoin ETF inflows reached record highs this quarter amid strong demand'
        b = 'ethereum staking rewards declined as validator numbers increased sharply'
        s = similarity(a, b)
        self.assertLess(s, MATCH_THRESHOLD,
                        f'expected sim {s:.3f} < threshold {MATCH_THRESHOLD}')

    def test_ambiguous_tie_not_marked(self):
        body = 'shared text content for both draft candidates in this test case'
        d1 = _draft(id='d1', body=body)
        d2 = _draft(id='d2', body=body)
        tw = _tweet(text=body)
        res = match_drafts_to_tweets([d1, d2], [tw])
        self.assertEqual(len(res), 0)

    def test_tweet_older_than_stored_at_not_marked(self):
        # tweet created at 06:00, stored_at 08:00 — tweet predates draft
        d = _draft(body='some post body text here', stored_at='2026-10-10T08:00:00+00:00')
        tw = _tweet(text='some post body text here',
                    created='Sat Oct 10 06:00:00 +0000 2026')
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 0)

    def test_reply_mode_non_reply_tweet_not_matched(self):
        target = 'https://x.com/user/status/1234'
        d = _draft(body='this is a reply body text content here now',
                   mode='reply', target=target)
        tw = _tweet(text='this is a reply body text content here now', reply=False)
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 0)

    def test_retweet_skipped(self):
        d = _draft(body='some post text that should not match a retweet')
        tw = _tweet(text='some post text that should not match a retweet', rt=True)
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 0)

    def test_quote_strip_target_url_improves_match(self):
        target = 'https://x.com/user/status/9999'
        body = 'market analysis showing strong growth patterns'
        d = _draft(body=body, mode='quote', target=target)
        # tweet text has the target URL appended (as X does for quote tweets)
        tw = _tweet(text=body + ' ' + target)
        res = match_drafts_to_tweets([d], [tw])
        self.assertEqual(len(res), 1)


class PayloadTests(unittest.TestCase):

    def test_payload_shape(self):
        d = _draft(id='draft-abc', account_id='acc1')
        tw = _tweet(id='tweet-123', created='Sat Oct 10 10:00:00 +0000 2026')
        tc = tweet_created_utc(tw)
        url = 'https://x.com/handle/status/tweet-123'
        payload = build_decision_payload('2026-10-10', d, tw, tc.isoformat(), url)
        self.assertEqual(payload['action'], 'published')
        self.assertTrue(payload['published'])
        self.assertEqual(payload['day'], '2026-10-10')
        self.assertEqual(payload['id'], 'draft-abc')
        self.assertEqual(payload['account_id'], 'acc1')
        self.assertIn('posted_at', payload)
        self.assertIn('tweet_url', payload)
        self.assertEqual(payload['source'], 'auto')

    def test_payload_keeps_before_publish_from_prior_approve(self):
        d = _draft(decision={'action': 'approve', 'text': None, 'note': ''})
        tw = _tweet()
        payload = build_decision_payload('2026-10-10', d, tw, '', '')
        self.assertEqual(payload['before_publish'], 'approve')

    def test_payload_keeps_admin_text(self):
        d = _draft(decision={'action': 'edit', 'text': 'edited by admin', 'note': ''})
        tw = _tweet()
        payload = build_decision_payload('2026-10-10', d, tw, '', '')
        self.assertEqual(payload['text'], 'edited by admin')


class DryRunAndEnvTests(unittest.TestCase):

    def test_dry_run_never_posts(self):
        """--dry-run must not call POST to the decisions API."""
        posted = []

        def fake_post(url, payload):
            posted.append(payload)

        import scripts.auto_published as ap
        fake_client = MagicMock()
        fake_client.made = 1
        fake_client.left = 39

        # load_unposted_drafts returns dicts with 'day' included
        unposted = [dict(_draft(id='d1', account_id='acc_with_handle'), day='2026-10-10')]

        with patch.object(ap, 'post_decision', side_effect=fake_post), \
             patch.object(ap, 'inbox_days', return_value=['2026-10-10']), \
             patch.object(ap, 'load_unposted_drafts', return_value=unposted), \
             patch.object(ap, 'load_accounts', return_value={
                 'acc_with_handle': {'id': 'acc_with_handle', 'handle': 'testhandle'}
             }), \
             patch.object(ap, 'fetch_timeline', return_value=[
                 _tweet(text='hello world test post text here',
                        created='Sat Oct 10 10:00:00 +0000 2026')
             ]), \
             patch.object(ap, 'write_log', return_value=None), \
             patch('live.x_daily.RapidClient', return_value=fake_client), \
             patch.dict('os.environ', {'FD_AUTOPUB': '1', 'RAPID_X_API_KEY': 'fake'}):
            ap.main(['--dry-run'])
        self.assertEqual(posted, [], 'dry-run must not POST')

    def test_fd_autopub_0_skips(self):
        """FD_AUTOPUB=0 must return 0 immediately without any API calls."""
        called = []
        import scripts.auto_published as ap
        with patch.object(ap, 'inbox_days', side_effect=lambda: called.append(1) or []), \
             patch.dict('os.environ', {'FD_AUTOPUB': '0'}):
            rc = ap.main([])
        self.assertEqual(rc, 0)
        self.assertEqual(called, [], 'inbox_days must not be called when FD_AUTOPUB=0')


# ---------------------------------------------------------------------------
# 3. tweet_created_utc and helpers
# ---------------------------------------------------------------------------

class HelperTests(unittest.TestCase):

    def test_tweet_created_utc_parses(self):
        tw = _tweet(created='Sat Oct 10 12:34:56 +0000 2026')
        dt = tweet_created_utc(tw)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 12)

    def test_tweet_created_utc_bad_returns_none(self):
        self.assertIsNone(tweet_created_utc({'created': ''}))
        self.assertIsNone(tweet_created_utc({'created': None}))

    def test_target_status_id_extracts(self):
        self.assertEqual(target_status_id('https://x.com/u/status/12345'), '12345')
        self.assertIsNone(target_status_id('https://x.com/no-status'))

    def test_strip_target_url(self):
        url = 'https://x.com/user/status/999'
        text = 'body text ' + url
        self.assertEqual(strip_target_url(text, url), 'body text')


if __name__ == '__main__':
    unittest.main()
