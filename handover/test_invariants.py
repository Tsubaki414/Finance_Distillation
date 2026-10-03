"""Real artifact integrity tests; no product imports, fixtures, writes or network."""
from pathlib import Path
import sys,json,unittest,datetime,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from handover_checks import read,rows,sha,db_records
class ArtifactIntegrity(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.raw={x['post_id']:x for x in rows('data/raw_posts.jsonl')};cls.clean=rows('data/clean_posts.jsonl');cls.ids={x['post_id'] for x in cls.clean}
 def test_clean_resolves_to_raw_payload(self):
  for x in self.clean:
   r=self.raw[x['post_id']];self.assertEqual(x['raw_source_ref']['payload_hash'],r['raw_payload_hash'])
   canonical=json.dumps(r['source_record'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
   self.assertEqual(hashlib.sha256(canonical).hexdigest(),r['raw_payload_hash'])
 def test_unique_ids_and_manifest_counts(self):
  raw=rows('data/raw_posts.jsonl');m=read('data/corpus_manifest.json')
  self.assertEqual(len(raw),len(self.raw));self.assertEqual(len(self.clean),len(self.ids));self.assertEqual(m['raw_posts'],len(raw));self.assertEqual(m['clean_posts'],len(self.clean))
 def test_legacy_registry_matches_database(self):
  ids={d['id'] for d in read('evidence_loop/quarantine/registry.json')['drafts']}
  db={d['id'] for d in db_records() if d['kind']=='legacy_invalid_output'}
  self.assertEqual(ids,db);self.assertEqual(len(ids),45)
  self.assertFalse(any(d['kind']=='draft' for d in db_records()))
 def test_source_hash_and_exact_fact_spans(self):
  p=read('evidence_loop/sources/packets/75155f58f5a995e3.json');f=ROOT/'evidence_loop'/p['artifact_path'];t=f.read_text()
  self.assertEqual(sha(f),p['artifact_sha256']);block_ids={b['id'] for b in p['blocks']}
  for fact in p['facts']:
   s=fact['source_span'];self.assertEqual(t[s['start']:s['end']],s['quote']);self.assertTrue(set(fact['source_block_ids'])<=block_ids)
 def test_profile_measurements_reference_real_posts(self):
  def walk(value):
   if isinstance(value,dict):
    if 'denominator_post_ids' in value:
     self.assertTrue(set(value['denominator_post_ids'])<=self.ids);self.assertTrue(set(value['support_post_ids'])<=set(value['denominator_post_ids']));self.assertEqual(value['sample_n'],len(value['denominator_post_ids']));self.assertTrue(value['method'])
    for v in value.values():walk(v)
   elif isinstance(value,list):
    for v in value:walk(v)
  for p in (ROOT/'evidence_loop/profiles').glob('*.json'):walk(json.loads(p.read_text()))
 def test_retrieval_pre_event_and_versioned(self):
  retrieval=read('evidence_loop/experiments/retrieval.json');routing=read('evidence_loop/experiments/routing.json');release=datetime.datetime.fromisoformat(read('evidence_loop/sources/packets/75155f58f5a995e3.json')['published_at'])
  for pid,items in retrieval['results'].items():
   for x in items:
    self.assertIn(x['post_id'],self.ids);self.assertLess(datetime.datetime.fromisoformat(x['created_at']),release)
   for d in routing[pid]['donors']:self.assertTrue((ROOT/'evidence_loop/profiles/versions'/f"{d['donor']}-{d['profile_version']}.json").is_file())
 def test_caption_hashes_time_links_and_no_shortpost_style(self):
  for s in rows('evidence_loop/transcripts/segments.jsonl'):
   self.assertEqual(sha(ROOT/'evidence_loop/transcripts'/s['raw_caption_file']),s['raw_caption_sha256']);self.assertLess(s['start'],s['end']);self.assertGreaterEqual(s['start'],0);self.assertIn('t=',s['timestamp_url']);self.assertFalse(s['eligible_for_short_post_style']);self.assertTrue(s['raw_cue_ids'])
 def test_real_new_plans_have_saved_requests_and_responses(self):
  for p in (ROOT/'evidence_loop/experiments/cases').glob('*.json'):
   d=json.loads(p.read_text());call=read('runs/model_calls/'+d['plan_run_id']+'.json');self.assertEqual(call['task'],'evidence_loop_independent_plan');self.assertIn('response',call);self.assertIn('messages',call['request'])
if __name__=='__main__':unittest.main(verbosity=2)
