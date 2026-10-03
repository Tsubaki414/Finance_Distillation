"""Turn the MLX 4-bit checkpoint into weights torch can load, without downloading anything.

Training needed a base and every local generative model turned out to be MLX 4-bit quantised:
`model.embed_tokens.weight` is stored as `(151936, 192) uint32`, one eighth of the width torch
expects, because eight 4-bit values are packed per 32-bit word. `transformers` loads it and
reports every layer as a size mismatch.

Three routes were tested before this one, and the first two are closed:

  torch on the quantised file   shapes are 1/8; transformers refuses
  MLX on the GPU                forward runs, **backward does not** — `steel_gemm_fused` fails to
                                load, the same Metal toolchain breakage that stopped :8683 from
                                being restartable
  MLX on the CPU                works, and measured at 75 s/step: 95 hours for one run

So the weights are unpacked back to float16 here and written as an ordinary safetensors
checkpoint. torch MPS was verified working beforehand — matmul and backward both run — so this
makes the local machine sufficient and no model has to be fetched.

**What is lost, stated rather than glossed.** Dequantising does not recover the original
weights. Quantisation to 4 bits at group size 64 discarded information, and unpacking restores
the shape, not the precision. The result is the model that has actually been generating this
project's drafts all along, which makes it the honest base to fine-tune; it is not equivalent to
the upstream fp16 release, and a run started here cannot be compared against one started there.

Run: .venv/bin/python -B ml/dequantize_base.py [--src=.runtime/models/generator] [--out=...]
"""
from __future__ import annotations
from pathlib import Path
import sys, json, shutil, datetime

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / '.runtime/models/generator'
DEFAULT_OUT = ROOT / '.runtime/models/generator-fp16'

COPY = ('tokenizer.json', 'tokenizer_config.json', 'vocab.json', 'merges.txt',
        'special_tokens_map.json', 'added_tokens.json')


def convert(src: Path, out: Path):
    import mlx.core as mx
    import numpy as np
    from safetensors.numpy import save_file

    cfg = json.loads((src / 'config.json').read_text())
    q = cfg.get('quantization')
    if not q:
        raise SystemExit(f'{src} 不是量化模型，不需要转换')
    gs, bits = q['group_size'], q['bits']

    w = mx.load(str(src / 'model.safetensors'))
    quantised = sorted({k[:-len('.scales')] for k in w if k.endswith('.scales')})
    out_w, kept, unpacked = {}, 0, 0

    for name in sorted(w):
        if name.endswith(('.scales', '.biases')):
            continue
        base = name[:-len('.weight')] if name.endswith('.weight') else None
        if base in quantised:
            t = mx.dequantize(w[name], w[base + '.scales'], w[base + '.biases'],
                              group_size=gs, bits=bits)
            unpacked += 1
        else:
            t = w[name]
            kept += 1
        mx.eval(t)
        out_w[name] = np.array(t, copy=False).astype(np.float16)

    out.mkdir(parents=True, exist_ok=True)
    save_file(out_w, str(out / 'model.safetensors'),
              metadata={'format': 'pt'})

    new_cfg = {k: v for k, v in cfg.items() if k != 'quantization'}
    new_cfg['torch_dtype'] = 'float16'
    new_cfg['_dequantised_from'] = {
        'source': str(src.relative_to(ROOT)), 'bits': bits, 'group_size': gs,
        'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'note': ('shape restored, precision not; this is the model that generated this '
                 "project's drafts, not the upstream fp16 release"),
    }
    (out / 'config.json').write_text(json.dumps(new_cfg, ensure_ascii=False, indent=2))
    for f in COPY:
        if (src / f).is_file():
            shutil.copy(src / f, out / f)
    return {'unpacked': unpacked, 'kept_as_is': kept, 'tensors': len(out_w),
            'bytes': (out / 'model.safetensors').stat().st_size}


def main():
    args = {a.split('=', 1)[0][2:]: (a.split('=', 1)[1] if '=' in a else True)
            for a in sys.argv[1:] if a.startswith('--')}
    src = Path(args.get('src')) if isinstance(args.get('src'), str) else DEFAULT_SRC
    out = Path(args.get('out')) if isinstance(args.get('out'), str) else DEFAULT_OUT
    r = convert(src, out)
    print(f"反量化 {r['unpacked']} 层，原样保留 {r['kept_as_is']} 个张量，"
          f"共 {r['tensors']} 个  →  {r['bytes']/1e9:.2f} GB")
    print(f'写入 {out}')

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    tok = AutoTokenizer.from_pretrained(str(out))
    m = AutoModelForCausalLM.from_pretrained(str(out), dtype=torch.float32)
    ids = tok('毛利率还稳在', return_tensors='pt')
    with torch.no_grad():
        o = m(**ids)
    print(f'  torch 加载并前向成功  logits {tuple(o.logits.shape)}')
    print('  注意：反量化恢复的是形状不是精度，这是本项目一直在用的那个模型，'
          '不等同于上游 fp16 版本。')


if __name__ == '__main__':
    main()
