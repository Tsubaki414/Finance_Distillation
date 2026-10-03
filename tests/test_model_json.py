import unittest
from live.model_json import parse_object

class JsonEnvelopeCases(unittest.TestCase):
    def test_post_json_review_prose_cannot_be_silently_discarded(self):
        raw='```json\n{"checks":{"facts_preserved":true}}\n```\nBut the selection omits a necessary premise.'
        with self.assertRaises(ValueError):parse_object(raw)
    def test_regular_json_and_fences_are_unchanged(self):
        self.assertEqual(parse_object('{"ok":true}'),{'ok':True})
        self.assertEqual(parse_object('```json\n{"ok":true}\n```'),{'ok':True})
    def test_never_extracts_json_from_a_prose_response(self):
        for raw in ['Explanation: {"ok":true}','{"ok":true} extra','[{"ok":true}]','{"text":"bad\\q"}']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):parse_object(raw)

if __name__=='__main__':unittest.main()
