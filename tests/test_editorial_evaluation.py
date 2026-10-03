import json
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from live.editorial_evaluation import summarize,save_review_packet
from scripts.freeze_shadow_intake import freeze

class EvaluationCases(unittest.TestCase):
    def test_two_preflight_holds_are_not_routing_success(self):
        report=summarize([{'results':{'current':{'status':'needs_source'},'candidate':{'status':'needs_source'}}}])
        self.assertEqual(report['paired_cases'],1);self.assertEqual(report['route_comparisons'],0)
        self.assertIsNone(report['route_agreement'])
    def test_unattempted_rows_are_not_model_failures_or_route_agreement(self):
        cases=[{'results':{'current':{'status':'blocked'},'candidate':{'status':'not_attempted'}}}]
        report=summarize(cases)
        self.assertEqual(report['modes']['candidate']['attempts'],0)
        self.assertEqual(report['modes']['candidate']['not_attempted'],1)
        self.assertIsNone(report['modes']['candidate']['hold_rate']);self.assertEqual(report['paired_cases'],0)
    def test_empty_is_not_a_zero_failure_or_human_success(self):
        report=summarize([])
        self.assertIsNone(report['route_agreement']);self.assertIsNone(report['human_edit_distance'])
        self.assertEqual(report['modes'],{})
    def test_holds_are_not_skips_and_none_is_a_route_disagreement(self):
        cases=[{'results':{'current':{'status':'not_suitable','route':{'decision':'NONE'}},
                           'candidate':{'status':'needs_source','why':'Missing chart','route':{'decision':'NEEDS_SOURCE'}}}}]
        result=summarize(cases)
        self.assertEqual(result['modes']['candidate']['hold_rate'],1)
        self.assertEqual(result['modes']['candidate']['skip_rate'],0)
        self.assertEqual(result['route_agreement'],0)
        self.assertIsNone(result['language_agreement_on_both_routed'])
    def test_blind_packet_keeps_exact_prose_without_method_or_quality_labels(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'attempt.json';p.write_text(json.dumps({'run_id':'TEST','source':{'original_text':'original'}}))
            text='Exact candidate.\n\nKeep paragraph.'
            cases=[{'case':'TEST','results':{'candidate':{'status':'needs_review','candidate_text':text,'metadata_ref':str(p),'account_id':'zh_macro'}}}]
            packet=save_review_packet(cases,Path(d)/'review')
            self.assertEqual(packet[0]['text'],text)
            self.assertNotIn('mode',packet[0]);self.assertNotIn('status',packet[0]);self.assertEqual(packet[0]['human_review'],'pending')
            self.assertEqual(json.loads((Path(d)/'review/private_blind_key.json').read_text())[0]['status'],'needs_review')
    def test_shadow_window_supports_feed_dates_without_assuming_completeness(self):
        end=datetime(2026,9,29,tzinfo=timezone.utc)
        rows=[{'source_id':'s','text':'one','published_at':'Mon, 28 Sep 2026 12:00:00 +0000'},
              {'source_id':'s','text':'two','published_at':'2026-09-28T11:00:00Z'},
              {'source_id':'s','text':'old','published_at':'2026-09-20T11:00:00Z'},
              {'source_id':'t','text':'bad date','published_at':'missing'}]
        result=freeze(rows,end,24,1)
        self.assertEqual(len(result['cases']),1);self.assertEqual(result['cases'][0]['source']['text'],'one')
        self.assertNotIn('content_complete',result['cases'][0]['source'])
        self.assertEqual(result['rows_with_unusable_dates'],1)

if __name__=='__main__':unittest.main()
