"""Long-form source ingest (Oct 16, Fiona): blog posts + YouTube transcripts + the FD_VIDEO_SRC video transcripts (+ local
book summaries) stored as plain text for the mind-map fill tier. No LLM call here (free apart from network time).

Nightly step: live/daily_ingest.py step 'longform_src' -> collect(). Output (outside git): FD_LONGFORM_DIR
(default /workspace/x/longform_src)/<yyyymmdd>/<item id>.{txt,json}; <dir>/books/*.txt (+ optional .json meta) are book
summaries put there by hand; <dir>/state.json remembers what was fetched. Config: live/longform_sources.json
(FD_LONGFORM_CONFIG). Switch: FD_LONGFORM_SRC (default 1; 0 = no fetch). Wall-clock budget FD_LONGFORM_BUDGET_S (240).
Never publishes; each stored item carries url / title / author / published_at for attribution.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'live' / 'longform_sources.json'
OUT_DIR = Path('/workspace/x/longform_src')
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
YT_FEED = 'https://www.youtube.com/feeds/videos.xml?channel_id={}'


def enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LONGFORM_SRC', '1') != '0'


def out_dir(env=None):
    return Path((env if env is not None else os.environ).get('FD_LONGFORM_DIR') or OUT_DIR)


def load_config(path=None):
    p = Path(path or os.environ.get('FD_LONGFORM_CONFIG') or CONFIG)
    return json.loads(p.read_text())


def _now():
    return datetime.now(timezone.utc)


def _ts(value):
    """aware datetime from an ISO string / feedparser struct_time / None."""
    if not value:
        return None
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def item_id(kind, source_id, key):
    return f'{kind}-{source_id}-' + hashlib.sha1(str(key).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- text extraction

def page_text(body):
    """Article text from a page: <article> / <main> / body paragraphs."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body or '', 'html.parser')
    for t in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript', 'svg']):
        t.decompose()
    node = soup.find('article') or soup.find('main') or soup.body or soup
    paras = [p.get_text(' ', strip=True) for p in node.find_all(['p', 'h2', 'h3', 'li', 'blockquote'])]
    paras = [p for p in paras if len(p) > 25 or p[:1].isupper()]
    return '\n\n'.join(paras).strip()


def html_to_text(html):
    from live.adapters import common
    return common.html_text(html or '')


def vtt_to_text(vtt):
    """WEBVTT / srt -> plain text, rolling auto-caption duplicates removed."""
    lines, last = [], ''
    for raw in (vtt or '').splitlines():
        s = raw.strip()
        if (not s or s.startswith(('WEBVTT', 'Kind:', 'Language:', 'NOTE')) or '-->' in s or re.fullmatch(r'\d+', s)):
            continue
        s = re.sub(r'<[^>]+>', '', s).replace('&nbsp;', ' ').replace('&amp;', '&').strip()
        if s and s != last and not (last and s in last):
            lines.append(s)
            last = s
    text = ' '.join(lines)
    return re.sub(r'\s+', ' ', text).strip()


# ---------------------------------------------------------------- fetchers (transport seam for tests)

def _get(url, transport=None, timeout=25):
    from live.adapters import common
    return common.http_get(url, headers={'User-Agent': UA}, timeout=timeout, transport=transport)


def blog_items(src, defaults, *, now, transport=None, fetch_page=None):
    """[{...meta, text}] new-enough entries of one blog feed (<= max_new_per_source, newest first)."""
    import feedparser
    st, body = _get(src['feed'], transport)
    if st != 200:
        return [], f'http_{st}'
    feed = feedparser.parse(body if isinstance(body, (bytes, str)) else str(body))
    horizon = now - timedelta(days=int(src.get('max_age_days', defaults.get('max_age_days', 21))))
    out = []
    for e in feed.entries:
        pub = _ts(e.get('published_parsed') or e.get('updated_parsed'))
        if pub is None or pub < horizon:
            continue
        html = ''
        if e.get('content'):
            html = max((c.get('value', '') for c in e['content']), key=len)
        text = html_to_text(html) if html else ''
        url = e.get('link') or ''
        if len(text) < defaults.get('min_chars', 2500) and url:
            try:
                s2, b2 = (fetch_page or _get)(url, transport) if fetch_page is None else fetch_page(url)
                if s2 == 200:
                    t2 = page_text(b2)
                    if len(t2) > len(text):
                        text = t2
            except Exception:   # noqa: BLE001 - a dead article page is just skipped
                pass
        if len(text) < defaults.get('min_chars', 2500):
            continue
        out.append({'kind': 'blog', 'source_id': src['id'], 'name': src['name'], 'lang': src.get('lang', 'en'),
                    'topic': src.get('topic', 'general'), 'title': (e.get('title') or '').strip(), 'url': url,
                    'author': src['name'], 'feed_author': (e.get('author') or '').strip(), 'published_at': pub.isoformat(),
                    'text': text[:defaults.get('max_chars', 60000)]})
        if len(out) >= int(src.get('max_new', defaults.get('max_new_per_source', 2))):
            break
    return out, 'ok'


def youtube_list(src, *, transport=None):
    """[{id,title,published,url}] newest first from the channel RSS (channel_id) or yt-dlp flat listing (handle)."""
    if src.get('channel_id'):
        import feedparser
        st, body = _get(YT_FEED.format(src['channel_id']), transport)
        if st != 200:
            return []
        return [{'id': e.get('yt_videoid') or e.get('id', '').split(':')[-1], 'title': e.get('title', ''),
                 'published': _ts(e.get('published_parsed')), 'url': e.get('link')}
                for e in feedparser.parse(body).entries]
    return []


def _js_runtime():
    import shutil
    return ['--js-runtimes', 'node'] if shutil.which('node') else []


def asr_enabled(env=None):
    return (env if env is not None else os.environ).get('FD_LONGFORM_ASR', '1') != '0'


def asr_text(data, lang):
    """Whisper segments -> paragraph text (zh: video_src style; en: plain space-joined ~600-char paragraphs)."""
    from live import video_src
    if str(lang).startswith('zh'):
        return video_src.transcript_text(data)
    paras, cur = [], ''
    for seg in data.get('segments') or []:
        cur = (cur + ' ' + seg['text'].strip()).strip()
        if len(cur) >= 600 and cur[-1:] in '.?!':
            paras.append(cur)
            cur = ''
    if cur:
        paras.append(cur)
    return '\n\n'.join(paras)


def youtube_asr(video_id, work_dir, *, runner=None, transcriber=None, max_s=None, lang='en'):
    """Audio-only download (yt-dlp) + the FD_VIDEO_SRC faster-whisper child -> text. Used when a video has no readable
    captions (YouTube answers 429 to the caption endpoint from this box). Returns (text, status)."""
    from live import video_src
    runner = runner or subprocess.run
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    cmd = ['yt-dlp', '-f', 'bestaudio', *_js_runtime(), '--no-warnings', '--socket-timeout', '20', '-o',
           str(work / f'{video_id}.%(ext)s'), f'https://www.youtube.com/watch?v={video_id}']
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=300)
    except Exception as exc:   # noqa: BLE001
        return '', f'asr_download_error: {type(exc).__name__}'
    files = [p for p in work.glob(f'{video_id}.*') if p.suffix not in ('.json', '.txt', '.part')]
    if not files:
        return '', 'asr_download_failed'
    try:
        data = (transcriber or video_src.transcribe)(files[0], work / f'{video_id}.whisper.json',
                                                     timeout=float(os.environ.get('FD_LONGFORM_ASR_TIMEOUT_S', 900)))
    except Exception as exc:   # noqa: BLE001
        return '', f'asr_failed: {str(exc)[:80]}'
    finally:
        for p in files:
            p.unlink(missing_ok=True)
    return asr_text(data, lang), 'ok'


def youtube_captions(video_id, langs, *, runner=None, timeout=90):
    """(text, duration_s, title, status) via yt-dlp subtitles only (own or auto captions, no media download)."""
    runner = runner or subprocess.run
    with tempfile.TemporaryDirectory() as td:
        cmd = ['yt-dlp', '--skip-download', '--write-subs', '--write-auto-subs', '--sub-langs', langs, '--sub-format', 'vtt',
               *_js_runtime(), '--print', '%(duration)s\t%(title)s', '--no-warnings', '-o', f'{td}/%(id)s', f'https://www.youtube.com/watch?v={video_id}']
        try:
            r = runner(cmd, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:   # noqa: BLE001
            return '', 0, '', f'error: {type(exc).__name__}'
        head = (r.stdout or '').strip().splitlines()
        dur, title = 0, ''
        if head and '\t' in head[0]:
            d, title = head[0].split('\t', 1)
            dur = float(d) if re.fullmatch(r'[\d.]+', d) else 0
        files = sorted(Path(td).glob('*.vtt'))
        if not files:
            return '', dur, title, 'no_captions'
        # prefer a manual (non -orig / non auto) file: shortest name first, else the first
        text = vtt_to_text(files[0].read_text(errors='replace'))
        return text, dur, title, 'ok'


def asr_max_s():
    return float(os.environ.get('FD_LONGFORM_ASR_MAX_S', 1500))


def youtube_items(src, defaults, *, now, transport=None, runner=None, seen=(), budget_left=lambda: True,
                  transcriber=None, asr_used=None, asr_budget=None):
    out, status = [], 'ok'
    asr_used = asr_used if asr_used is not None else [0]
    cap = int(os.environ.get('FD_LONGFORM_ASR_MAX', 2))
    asr_budget = asr_budget or (lambda: asr_used[0] < cap)
    horizon = now - timedelta(days=int(src.get('max_age_days', defaults.get('max_age_days', 21))))
    langs = 'zh.*,en.*' if src.get('lang') == 'zh' else 'en.*'
    for v in youtube_list(src, transport=transport):
        if len(out) >= int(src.get('max_new', defaults.get('max_new_per_source', 2))) or not budget_left():
            break
        if not v['id'] or (v['published'] and v['published'] < horizon) or item_id('youtube', src['id'], v['id']) in seen:
            continue
        text, dur, title, st = youtube_captions(v['id'], langs, runner=runner)
        if st == 'no_captions' and asr_enabled() and asr_budget() and (not dur or dur <= asr_max_s()):
            asr_used[0] += 1
            text, st = youtube_asr(v['id'], Path(tempfile.gettempdir()) / 'fd_longform_asr', runner=runner,
                                   transcriber=transcriber, lang=src.get('lang', 'en'))
        if st != 'ok' or len(text) < defaults.get('min_chars', 2500):
            status = st if st != 'ok' else 'short'
            continue
        if dur and not (defaults.get('min_video_s', 360) <= dur <= defaults.get('max_video_s', 5400)):
            continue
        out.append({'kind': 'youtube', 'source_id': src['id'], 'name': src['name'], 'lang': src.get('lang', 'en'),
                    'topic': src.get('topic', 'general'), 'title': title or v['title'], 'url': v['url'],
                    'author': src['name'], 'published_at': (v['published'] or now).isoformat(), 'video_id': v['id'],
                    'duration_s': dur, 'text': text[:defaults.get('max_chars', 60000)]})
    return out, status


# ---------------------------------------------------------------- store / collect

def _write(base, day, item):
    iid = item.get('id') or item_id(item['kind'], item['source_id'], item.get('video_id') or item['url'])
    d = Path(base) / day
    d.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in item.items() if k != 'text'} | {'id': iid, 'chars': len(item['text']),
                                                             'fetched_at': _now().isoformat(timespec='seconds')}
    (d / f'{iid}.txt').write_text(item['text'], encoding='utf-8')
    (d / f'{iid}.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return iid


def collect(*, now=None, base=None, config=None, transport=None, runner=None, budget_s=None, log=print, only=None,
            transcriber=None):
    """Fetch new blog entries + YouTube transcripts into <base>/<yyyymmdd>/. Never raises per source. Returns a summary."""
    now = now or _now()
    base = Path(base or out_dir())
    cfg = config or load_config()
    defaults = cfg.get('defaults') or {}
    budget_s = float(budget_s if budget_s is not None else os.environ.get('FD_LONGFORM_BUDGET_S', 900))
    t0 = time.monotonic()
    left = lambda: time.monotonic() - t0 < budget_s   # noqa: E731
    state_p = base / 'state.json'
    try:
        state = json.loads(state_p.read_text())
    except (OSError, ValueError):
        state = {}
    seen = set(state.get('seen') or [])
    day = now.strftime('%Y%m%d')
    summary = {'day': day, 'sources': {}, 'new': 0}
    asr_used = [0]
    todo = [('blog', s) for s in cfg.get('blogs') or []] + [('youtube', s) for s in cfg.get('youtube') or []]
    for kind, src in todo:
        if only and src['id'] not in only:
            continue
        if not left():
            summary['sources'][src['id']] = 'budget'
            continue
        try:
            if kind == 'blog':
                items, st = blog_items(src, defaults, now=now, transport=transport)
            else:
                items, st = youtube_items(src, defaults, now=now, transport=transport, runner=runner, seen=seen,
                                          budget_left=left, transcriber=transcriber, asr_used=asr_used)
        except Exception as exc:   # noqa: BLE001
            summary['sources'][src['id']] = f'error: {type(exc).__name__}: {str(exc)[:80]}'
            continue
        n = 0
        for it in items:
            iid = it.get('id') or item_id(it['kind'], it['source_id'], it.get('video_id') or it['url'])
            if iid in seen:
                continue
            _write(base, day, {**it, 'id': iid})
            seen.add(iid)
            n += 1
        summary['sources'][src['id']] = f'{st}: {n} new'
        summary['new'] += n
    base.mkdir(parents=True, exist_ok=True)
    state['seen'] = sorted(seen)[-4000:]
    state['last_run'] = now.isoformat(timespec='seconds')
    state_p.write_text(json.dumps(state, ensure_ascii=False))
    summary['asr_videos'] = asr_used[0]
    log('longform_src ' + json.dumps(summary, ensure_ascii=False))
    return summary


# ---------------------------------------------------------------- pool for the mind-map tier

def _meta_from_video_src(meta_path, cfg):
    xv = cfg.get('x_video') or {}
    try:
        m = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return None
    txt = meta_path.with_suffix('.txt')
    if not txt.exists():
        return None
    try:
        created = datetime.strptime(m.get('created', ''), '%a %b %d %H:%M:%S %z %Y').isoformat()
    except ValueError:
        created = None
    try:
        from live import video_src
        handle = video_src.HANDLE
    except Exception:   # noqa: BLE001
        handle = None
    sid = str(m.get('id') or meta_path.stem)
    return {'id': f'xv-{sid}', 'kind': 'x_video', 'source_id': 'x_video', 'name': xv.get('name', 'X video'),
            'lang': m.get('language') or xv.get('lang', 'zh'), 'topic': xv.get('topic', 'investing'),
            'title': re.sub(r'https?://\S+', '', m.get('caption') or '').strip()[:100] or f'video {sid}',
            'url': f'https://x.com/i/status/{sid}', 'author': xv.get('credit') or 'X 视频', 'handle': handle,
            'published_at': created, 'chars': m.get('transcript_chars'), 'text_path': str(txt)}


def pool(*, base=None, config=None, lookback_days=45, now=None, env=None):
    """Candidate source items [{meta..., 'text_path'}] newest first: stored blog / YouTube items, book summaries and the
    FD_VIDEO_SRC transcripts, within `lookback_days` of the folder day (books have no age limit)."""
    env = env if env is not None else os.environ
    base = Path(base or out_dir(env))
    cfg = config or load_config()
    now = now or _now()
    out = []
    horizon = (now - timedelta(days=lookback_days)).strftime('%Y%m%d')
    for d in sorted((p for p in base.glob('2*') if p.is_dir()), reverse=True):
        if d.name < horizon:
            continue
        for mp in sorted(d.glob('*.json')):
            try:
                m = json.loads(mp.read_text())
            except ValueError:
                continue
            txt = mp.with_suffix('.txt')
            if txt.exists() and m.get('id'):
                out.append({**m, 'text_path': str(txt)})
    for tp in sorted((base / 'books').glob('*.txt')) if (base / 'books').is_dir() else []:
        mp = tp.with_suffix('.json')
        m = json.loads(mp.read_text()) if mp.exists() else {}
        out.append({'id': 'book-' + tp.stem, 'kind': 'book', 'source_id': 'book', 'name': m.get('name') or tp.stem,
                    'lang': m.get('lang', 'en'), 'topic': m.get('topic', 'general'), 'title': m.get('title') or tp.stem,
                    'author': m.get('author', ''), 'url': m.get('url', ''), 'published_at': m.get('published_at'),
                    'text_path': str(tp), **{k: v for k, v in m.items() if k not in ('text_path',)}})
    xv = cfg.get('x_video') or {}
    vdir = Path(os.environ.get('FD_VIDEO_DIR') or xv.get('dir') or '/workspace/x/video_src')
    if xv.get('enabled', True) and env.get('FD_MINDMAP_VIDEO_POOL', '1') != '0' and vdir.is_dir():
        for d in sorted((p for p in vdir.glob('2*') if p.is_dir()), reverse=True):
            if d.name < horizon:
                continue
            for mp in sorted(d.glob('*.json')):
                if mp.name.endswith('.whisper.json'):
                    continue
                m = _meta_from_video_src(mp, cfg)
                if m:
                    out.append(m)
    out.sort(key=lambda m: str(m.get('published_at') or ''), reverse=True)
    return out


def read_text(item, max_chars=60000):
    return Path(item['text_path']).read_text(encoding='utf-8', errors='replace')[:max_chars]


def start_background(*, now=None, base=None, log_path=None):
    """Detached child `python -m live.longform_src collect` (network + CPU, no LLM, own wall-clock budget); the nightly
    ingest does not wait for it. Returns the Popen (or None when FD_LONGFORM_SRC=0)."""
    if not enabled():
        return None
    import sys
    logf = open(log_path or (out_dir().parent / 'longform_collect.log'), 'a')
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    return subprocess.Popen([sys.executable, '-m', 'live.longform_src', 'collect'], cwd=str(ROOT), env=env,
                            stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['collect']:
        if not enabled():
            print('FD_LONGFORM_SRC=0: off')
            return 0
        only = set(argv[1:]) or None
        collect(only=only)
        return 0
    print('usage: python -m live.longform_src collect [source ids]')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
