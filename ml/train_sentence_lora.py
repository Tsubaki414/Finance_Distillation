"""LoRA on Qwen2-1.5B for the one thing a human said was broken.

The human review is the whole reason this file exists: groundedness 5.00 out of 5, naturalness
**0.17**, every piece marked 重写, and five prompt-level persona modes rated identically bad. That
last result is what makes training the next step rather than a shortcut — prompting has been
varied five ways and a reader could not tell the variants apart.

Trained on the donors' own sentences, never on model output. Distilling grok's drafts would
propagate the defect: a human scored those 0.17 too.

    input    author, the preceding sentence, a figure and what it measures
    output   the sentence the donor actually wrote carrying that figure

Why this base. Qwen2-1.5B, dequantised from the project's own MLX 4-bit checkpoint by
`ml/dequantize_base.py`. Three routes were tested: torch on the quantised file fails on shape
(4-bit packing makes every tensor 1/8 width); MLX on the GPU runs forward but **not backward**,
the `steel_gemm_fused` kernel failing exactly as the Metal breakage that stopped :8683 being
restartable; MLX on the CPU works at a measured 75 s/step, which is 95 hours for one run. torch
MPS was verified before this file was written — matmul and backward both run.

Dequantising restores shape, not precision. This is the model that has actually been writing this
project's drafts, which makes it the honest base; it is not the upstream fp16 release.

What would make this wrong, recorded before the run rather than after:

  * label-before-number stays at ~5x the donors' rate (theirs: 5.03 per 1000 chars)
  * a human's naturalness score does not move off 0.17

Either one means the approach failed. `PLAN.md` S6 says record it and stop, not tune until a
metric moves.

Run: .venv/bin/python -B ml/train_sentence_lora.py [--epochs=3] [--rank=16] [--dry-run]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, time, math, datetime, random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / 'ml/store/sentence_task'
# The dequantised copy. `.runtime/models/generator` is MLX 4-bit and transformers cannot load
# it; see ml/dequantize_base.py for the three routes tested and why this is the surviving one.
BASE = ROOT / '.runtime/models/generator-fp16'
OUT = ROOT / '.runtime/adapters/sentence_style'
RUNS = ROOT / 'ml_experiments/training'

MAX_LEN = 384


def load_rows(name):
    p = DATA / f'{name}.jsonl'
    if not p.is_file():
        raise SystemExit(f'{p} 不存在，先跑 ml/sentence_dataset.py')
    # split('\n'), not splitlines(): the latter also breaks on U+2028/U+2029, which json does
    # not escape, and a record containing one would be read as two broken halves.
    return [json.loads(l) for l in p.read_text(encoding='utf-8').split('\n') if l.strip()]


def build_examples(rows, tok):
    """Prompt tokens are masked out of the loss; only the sentence itself is learned."""
    from ml.sentence_dataset import prompt_of
    out = []
    for r in rows:
        prompt = prompt_of(r)
        target = r['target']
        p_ids = tok(prompt, add_special_tokens=False)['input_ids']
        t_ids = tok(target + tok.eos_token, add_special_tokens=False)['input_ids']
        ids = (p_ids + t_ids)[:MAX_LEN]
        # -100 tells the loss to ignore a position. Without this the model spends its capacity
        # learning to reproduce the prompt, which it is given at inference anyway.
        labels = ([-100] * len(p_ids) + t_ids)[:MAX_LEN]
        if len(ids) < 8 or all(x == -100 for x in labels):
            continue
        out.append({'input_ids': ids, 'labels': labels})
    return out


def collate(batch, pad_id):
    import torch
    n = max(len(b['input_ids']) for b in batch)
    ids, labels, mask = [], [], []
    for b in batch:
        k = n - len(b['input_ids'])
        ids.append(b['input_ids'] + [pad_id] * k)
        labels.append(b['labels'] + [-100] * k)
        mask.append([1] * len(b['input_ids']) + [0] * k)
    return (torch.tensor(ids), torch.tensor(labels), torch.tensor(mask))


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    epochs = int(args.get('epochs', 3))
    rank = int(args.get('rank', 16))
    lr = float(args.get('lr', 1e-4))
    bs = int(args.get('bs', 2))
    seed = int(args.get('seed', 42))
    dry = 'dry-run' in args

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(seed)
    random.seed(seed)
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'

    train_rows, test_rows = load_rows('train'), load_rows('test')
    tok = AutoTokenizer.from_pretrained(str(BASE))
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    train = build_examples(train_rows, tok)
    test = build_examples(test_rows, tok)
    print(f'训练 {len(train)} 条 / 测试 {len(test)} 条  device={device}')

    if dry:
        ex = train[0]
        print('\n样例（loss 只算目标句部分）:')
        print('  输入:', tok.decode([i for i, l in zip(ex['input_ids'], ex['labels'])
                                     if l == -100]).replace('\n', ' / '))
        print('  目标:', tok.decode([l for l in ex['labels'] if l != -100]))
        print(f"\n  token 长度分布: 中位 "
              f"{sorted(len(e['input_ids']) for e in train)[len(train)//2]}, "
              f"最长 {max(len(e['input_ids']) for e in train)}")
        return

    # bfloat16 for the frozen base, float32 for the LoRA parameters that actually train.
    #
    # float32 throughout was measured at 65 s/step and would have taken 41 hours; the weights
    # alone are 6 GB in fp32 and unified memory starts swapping. In bfloat16 the same step takes
    # 2.17 s — thirty times faster — and float16 is faster still at 1.68 s but has the narrower
    # exponent range, which is not worth eighteen minutes on a run that only happens once.
    #
    # The trainable parameters stay in float32 because the optimiser's moments lose too much in
    # half precision; the base is frozen so its precision only has to be good enough to read.
    model = AutoModelForCausalLM.from_pretrained(str(BASE), dtype=torch.bfloat16)
    cfg = LoraConfig(r=rank, lora_alpha=rank * 2, lora_dropout=0.05, bias='none',
                     task_type='CAUSAL_LM',
                     target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj',
                                     'gate_proj', 'up_proj', 'down_proj'])
    model = get_peft_model(model, cfg).to(device)
    # The LoRA parameters stay in bfloat16 with the base.
    #
    # Casting them to float32 is the usual advice — the optimiser's moments lose precision in half
    # — and on this hardware it made every step do a dtype conversion inside each LoRA matmul. The
    # benchmark that said 2.17 s/step had not been cast; the real run with the cast went past 44
    # s/step and would have taken 28 hours. Measuring a simplified configuration and then shipping
    # a different one is how that went unnoticed for 36 minutes.
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f'LoRA r={rank}  可训练 {trainable:,} / {total:,} ({trainable/total:.2%})')

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    steps = math.ceil(len(train) / bs) * epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps,
                                                pct_start=0.1)

    def evaluate():
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for i in range(0, len(test), bs):
                b = test[i:i + bs]
                ids, labels, mask = [x.to(device) for x in collate(b, tok.pad_token_id)]
                out = model(input_ids=ids, attention_mask=mask, labels=labels)
                tot += out.loss.item() * len(b)
                n += len(b)
        model.train()
        return tot / max(n, 1)

    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = 'lora-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    record = {'run_id': run_id, 'base': str(BASE.relative_to(ROOT)), 'device': device,
              'rank': rank, 'lr': lr, 'epochs': epochs, 'batch_size': bs, 'seed': seed,
              'train_n': len(train), 'test_n': len(test), 'max_len': MAX_LEN,
              'trainable_params': trainable, 'total_params': total,
              'dataset_meta': json.loads((DATA / 'meta.json').read_text()),
              'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'history': []}

    before = evaluate()
    record['test_loss_before'] = round(before, 4)
    print(f'训练前 test loss {before:.4f}')

    model.train()
    step, t0 = 0, time.time()
    for ep in range(epochs):
        random.shuffle(train)
        run_loss, seen = 0.0, 0
        for i in range(0, len(train), bs):
            b = train[i:i + bs]
            ids, labels, mask = [x.to(device) for x in collate(b, tok.pad_token_id)]
            out = model(input_ids=ids, attention_mask=mask, labels=labels)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            run_loss += out.loss.item() * len(b)
            seen += len(b)
            step += 1
            if step % 10 == 0:
                print(f'  ep{ep+1} step {step}/{steps}  loss {run_loss/seen:.4f}  '
                      f'{(time.time()-t0)/step:.2f}s/step', flush=True)
        te = evaluate()
        record['history'].append({'epoch': ep + 1, 'train_loss': round(run_loss / seen, 4),
                                  'test_loss': round(te, 4)})
        print(f'epoch {ep+1}: train {run_loss/seen:.4f}  test {te:.4f}')

    record['test_loss_after'] = record['history'][-1]['test_loss']
    record['seconds'] = round(time.time() - t0, 1)
    record['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record['falsification'] = [
        'label-before-number must fall from ~5x toward the donors 5.03 per 1000 chars',
        'a human naturalness score must move off 0.17',
        'a lower test loss on its own proves nothing about either',
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUT))
    tok.save_pretrained(str(OUT))
    (RUNS / f'{run_id}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(f'\n适配器写入 {OUT}\n记录写入 {RUNS / (run_id + ".json")}')
    print(f'test loss {before:.4f} → {record["test_loss_after"]:.4f}')
    print('  注意：loss 下降只说明它学到了训练分布，不说明真人会觉得更自然。验收在 S5。')


if __name__ == '__main__':
    main()
