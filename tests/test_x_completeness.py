"""P0-3a acceptance: deterministic X body completeness from the capture itself.

complete only when: no truncation flag; after stripping trailing t.co links every
variant is a prefix of the chosen body; the body does not end with an ellipsis;
there are at least two variants (or a note_tweet body); and an identical-variant
body is not sitting at the platform length limit. The basis says what was
checked; it never claims independent full-text verification.
"""
import unittest

from live.xsearch import normalize_item

BODY = '美联储这次降息之后，市场关心的是终端利率在哪里，以及资产负债表缩减何时停止。我的判断是年内还有一次。'


def item(**updates):
    return {'id': '1', 'author': {'id': '2', 'name': 'q', 'userName': 'q'}, 'lang': 'zh',
            'createdAt': '2026-09-01T00:00:00Z', 'isReply': False, 'isQuote': False, 'isRetweet': False,
            **updates}


def norm(x):
    return normalize_item(x, query='from:q', run_id='r', dataset_id='d', fetched_at='2026-09-01T01:00:00Z',
                          raw_import_ref='TEST')


class XCompleteness(unittest.TestCase):
    def test_identical_variants_complete(self):
        row = norm(item(text=BODY, fullText=BODY))
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'variants_identical')
        self.assertEqual(row['completeness_evidence'], 'capture_internal_consistency')

    def test_truncated_fulltext_with_tco_tail_is_extended_by_text(self):
        trunc = BODY[:30] + ' https://t.co/AbC123xyz'
        row = norm(item(text=BODY, fullText=trunc))
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['original_text'], BODY)
        self.assertEqual(row['completeness_basis'], 'truncated_variant_extended')

    def test_longer_truncated_variant_with_link_is_not_chosen(self):
        # The truncated variant plus link is longer than the real body here.
        short = '短帖：结论是年内还有一次降息。'
        trunc = short[:6] + ' https://t.co/AbCdefghijklmnopqrstuvwxyz0123456789'
        row = norm(item(text=short, fullText=trunc))
        self.assertEqual(row['original_text'], short)
        self.assertTrue(row['content_complete'])

    def test_shared_trailing_link_kept_in_body(self):
        body = BODY + ' https://t.co/Media1234'
        row = norm(item(text=body, fullText=body))
        self.assertEqual(row['original_text'], body)
        self.assertTrue(row['content_complete'])

    def test_ellipsis_tail_not_complete(self):
        for tail in ('…', '...'):
            with self.subTest(tail=tail):
                body = BODY[:40] + tail
                row = norm(item(text=body, fullText=body))
                self.assertFalse(row['content_complete'])
                self.assertEqual(row['completeness_basis'], 'ellipsis_tail')

    def test_ellipsis_before_tco_not_complete(self):
        body = BODY[:40] + '… https://t.co/AbC123xyz'
        row = norm(item(text=body, fullText=body))
        self.assertFalse(row['content_complete'])

    def test_non_prefix_conflict_not_complete(self):
        row = norm(item(text=BODY, fullText='完全不同的另一段话，并且也很长很长很长。'))
        self.assertFalse(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'conflicting_text_variants')

    def test_truncation_flag_wins(self):
        row = norm(item(text=BODY, fullText=BODY, truncated=True))
        self.assertFalse(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'provider_truncated')

    def test_single_variant_unverified(self):
        row = norm(item(text=BODY))
        self.assertFalse(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'single_variant_unverified')

    def test_identical_variants_at_platform_limit_unverified(self):
        # Every variant cut at the same point without an ellipsis cannot be told apart
        # from a complete post when the body sits at the 280 weighted-char limit.
        body = ('利率' * 70)  # 140 CJK chars = 280 weighted
        row = norm(item(text=body, fullText=body))
        self.assertFalse(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'at_platform_limit_unverified')

    def test_note_tweet_body_complete(self):
        long = BODY * 6
        row = norm(item(text=BODY[:50] + '…', fullText=BODY[:50] + '…', noteTweet={'text': long}))
        self.assertEqual(row['original_text'], long)
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'note_tweet_body')

    def test_leading_reply_mentions_ignored_for_prefix(self):
        row = norm(item(text=BODY, fullText='@someone ' + BODY[:30] + ' https://t.co/AbC123xyz'))
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['original_text'], BODY)

    def test_mention_prefixed_truncated_variant_not_chosen(self):
        short = '短帖：结论是年内还有一次降息，收益率会回落。'
        row = norm(item(text=short, fullText='@someone_long ' + short[:12]))
        self.assertEqual(row['original_text'], short)
        self.assertTrue(row['content_complete'])

    def test_mid_text_difference_still_conflicts(self):
        row = norm(item(text=BODY, fullText=BODY[:10] + 'https://t.co/AbC123xyz' + BODY[10:30]))
        self.assertFalse(row['content_complete'])

    def test_explicit_provider_flag_still_honoured(self):
        row = norm(item(text=BODY, truncated=False))
        self.assertTrue(row['content_complete'])
        self.assertEqual(row['completeness_basis'], 'explicit_provider_completeness')


if __name__ == '__main__':
    unittest.main()
