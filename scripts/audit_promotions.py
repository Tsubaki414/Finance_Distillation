import json,collections,hashlib
from pathlib import Path
from promotion_policy import output_gate,VERSION
ROOT=Path(__file__).resolve().parents[1]
def main():
 raw=[json.loads(s) for s in (ROOT/'data/raw_posts.jsonl').read_text().split('\n') if s]
 clean=[json.loads(s) for s in (ROOT/'data/clean_posts.jsonl').read_text().split('\n') if s]
 report={'version':VERSION,'raw_n':len(raw),'clean_n':len(clean),'posts_with_removed_spans':sum(bool(x['text_processing']['excluded_spans']) for x in raw),'retained_with_removed_spans':sum(bool(x['text_processing']['excluded_spans']) for x in clean),'removed_span_reasons':dict(collections.Counter(s['reason'] for x in raw for s in x['text_processing']['excluded_spans'])),'whole_commercial_exclusions':[x['post_id'] for x in raw if x['text_processing']['whole_post_commercial_exclusion']],'retained_promotion_gate_matches':[x['post_id'] for x in clean if output_gate(x['text'])],'source_files_hash_verified':all(hashlib.sha256(Path(i['path']).read_bytes()).hexdigest()==i['sha256'] for i in json.loads((ROOT/'data/corpus_manifest.json').read_text())['inputs']),'span_substrings_verified':all(x['text'][s['start']:s['end']]==s['text'] for x in raw for s in x['text_processing']['excluded_spans']),'language_counts':dict(collections.Counter(x['language'] for x in clean)),'raw_sha256':hashlib.sha256((ROOT/'data/raw_posts.jsonl').read_bytes()).hexdigest(),'clean_sha256':hashlib.sha256((ROOT/'data/clean_posts.jsonl').read_bytes()).hexdigest(),'scope':'Known sponsor lines and context-reviewed body/tail promotions. Source files are unchanged. No claim of perfect detection of undisclosed or novel promotion.'}
 assert not report['retained_promotion_gate_matches'] and report['source_files_hash_verified'] and report['span_substrings_verified']
 assert all('raw_text' not in x and all('text' not in s for s in x['text_processing']['excluded_spans']) for x in clean)
 (ROOT/'runs/promotion-cleanup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
