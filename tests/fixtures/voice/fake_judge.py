import json, sys
prompt=sys.stdin.read()
assert "voice_card" in prompt and "style_exemplars" in prompt
print("judge preamble")
print(json.dumps({"judgment_first":4,"voice_match":3,"reason":"synthetic advisory score"}))
