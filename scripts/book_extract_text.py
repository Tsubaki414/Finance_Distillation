#!/usr/bin/env python3
"""Copy user-owned book PDFs into live/sources/books and extract text.

Per page: poppler pdftotext first; a page with almost no text layer (scanned)
is rasterised and OCRed with tesseract chi_sim+eng. Tall single-page handouts
(images) are OCRed from the embedded image in slices. Writes
live/sources/books/text/<slug>.txt (pages separated by form feeds) and
manifest.json with per-book OCR page counts. Ads / WeChat IDs are stripped
from file names and text.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, hashlib, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'live' / 'sources' / 'books'
MIN_CHARS = 40
AD = re.compile(r'(加\s*[VvＶ微][\w-]{4,}\s*(赠送课程)?|微信[号:：\s]*[A-Za-z][\w-]{5,}|[Vv][Xx]?[:：]\s*[A-Za-z0-9_-]{6,}|(加|\+)\s*(VX|vx|微信|WX|wx)[:：]?\s*[A-Za-z0-9_-]{5,}|赠送课程)')


def strip_ads(text):
    return AD.sub('', text)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw).stdout


def pages(pdf):
    out = run(['pdfinfo', str(pdf)])
    return int(re.search(r'^Pages:\s+(\d+)', out, re.M).group(1))


def ocr_image(path):
    return run(['tesseract', str(path), '-', '-l', 'chi_sim+eng', '--psm', '6'], timeout=600)


def page_text(pdf, n, tmp):
    text = run(['pdftotext', '-raw', '-f', str(n), '-l', str(n), str(pdf), '-'])
    if len(re.sub(r'\s', '', text)) >= MIN_CHARS:
        return text, False
    img = Path(tmp) / f'p{n}'
    subprocess.run(['pdftoppm', '-r', '300', '-gray', '-png', '-f', str(n), '-l', str(n), '-singlefile', str(pdf), str(img)], capture_output=True)
    png = img.with_suffix('.png')
    if not png.exists():
        return text, False
    out = ocr_image(png)
    png.unlink(missing_ok=True)
    return out, True


def tall_page(pdf, tmp):
    """Single tall image page: OCR the embedded image in overlapping-free slices."""
    from PIL import Image
    subprocess.run(['pdfimages', '-j', str(pdf), str(Path(tmp) / 'img')], capture_output=True)
    texts = []
    for jpg in sorted(Path(tmp).glob('img-*')):
        im = Image.open(jpg).convert('L')
        w, h = im.size
        im = im.resize((w * 2, h * 2))
        step = 3000
        for y in range(0, h * 2, step):
            part = Path(tmp) / f'slice{y}.png'
            im.crop((0, y, w * 2, min(h * 2, y + step))).save(part)
            texts.append(ocr_image(part))
    return '\n'.join(texts)


def extract(pdf, slug, workers):
    n = pages(pdf)
    with tempfile.TemporaryDirectory() as tmp:
        if n == 1 and len(re.sub(r'\s', '', run(['pdftotext', str(pdf), '-']))) < MIN_CHARS:
            return [tall_page(pdf, tmp)], 1, n
        with cf.ThreadPoolExecutor(workers) as pool:
            res = list(pool.map(lambda i: page_text(pdf, i, tmp), range(1, n + 1)))
    return [t for t, _ in res], sum(o for _, o in res), n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--src', type=Path, required=True)
    ap.add_argument('--map', type=Path, required=True, help='json {filename: slug}')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args(argv)
    (ROOT / 'pdf').mkdir(parents=True, exist_ok=True); (ROOT / 'text').mkdir(parents=True, exist_ok=True)
    mapping = json.loads(a.map.read_text())
    mpath = ROOT / 'manifest.json'
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    for name, slug in mapping.items():
        if a.only and slug not in a.only:
            continue
        src = a.src / name
        dst = ROOT / 'pdf' / (slug + '.pdf')
        shutil.copy2(src, dst)
        texts, ocr, n = extract(dst, slug, a.workers)
        body = '\f'.join(strip_ads(t) for t in texts)
        (ROOT / 'text' / (slug + '.txt')).write_text(body)
        manifest[slug] = {'original_filename_clean': strip_ads(name), 'pages': n, 'ocr_pages': ocr,
                          'chars': len(re.sub(r'\s', '', body)),
                          'pdf_sha256': hashlib.sha256(dst.read_bytes()).hexdigest()}
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        print(slug, manifest[slug], flush=True)


if __name__ == '__main__':
    sys.exit(main())
