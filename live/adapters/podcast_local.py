"""Podcast episodes transcribed locally (faster-whisper on the box CPU: no API spend).

Only for public podcast feeds whose copyright line does not reserve text-and-data mining.
Audio is downloaded with the honest crawler UA, the first `max_seconds` are transcribed, and the
audio file is deleted afterwards. Units from transcripts are paraphrase-only (no_reproduction).
"""
from __future__ import annotations
import re
import subprocess
import tempfile
from pathlib import Path
from live.adapters import common, feeds

MODEL_NAME = 'base.en'
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(MODEL_NAME, device='cpu', compute_type='int8', cpu_threads=6)
    return _MODEL


def available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return subprocess.run(['which', 'ffmpeg'], capture_output=True).returncode == 0


def transcribe_url(url, *, max_seconds=1500):
    import httpx
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / 'episode.audio'
        with httpx.stream('GET', url, headers={'User-Agent': common.DEFAULT_UA}, timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            with audio.open('wb') as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        raw = subprocess.run(['ffmpeg', '-v', 'quiet', '-t', str(max_seconds), '-i', str(audio), '-f', 's16le',
                              '-ac', '1', '-ar', '16000', '-'], capture_output=True, check=True, timeout=300).stdout
    samples = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    segments, _ = _model().transcribe(samples, beam_size=1, vad_filter=True)
    return ' '.join(s.text.strip() for s in segments).strip()


def _items(xml):
    out = []
    for block in re.findall(r'<item>(.*?)</item>', xml, re.S):
        enc = re.search(r'<enclosure[^>]+url="([^"]+)"', block)
        if not enc:
            continue
        title = (re.search(r'<title>(.*?)</title>', block, re.S) or [None, ''])[1]
        title = re.sub(r'^<!\[CDATA\[|\]\]>$', '', title.strip())
        date = (re.search(r'<pubDate>(.*?)</pubDate>', block, re.S) or [None, ''])[1]
        out.append({'title': common.html_text(title), 'audio': enc[1].replace('&amp;', '&'), 'published_raw': date.strip()})
    return out


def fetch(ch, *, limit=1, transport=None, transcribe=None, max_seconds=1500, known=None):
    url = ch.get('feed_url') or ch['url']
    status, xml = common.http_get(url, transport=transport)
    if status != 200:
        return {'status': f'http_{status}', 'sources': []}
    copyright_ = ' '.join(re.findall(r'<copyright>(.*?)</copyright>', xml, re.S))
    if feeds.TDM.search(copyright_):
        return {'status': 'tdm_reserved', 'copyright': copyright_[:300], 'sources': []}
    if transcribe is None and not available():
        return {'status': 'whisper_unavailable', 'sources': []}
    transcribe = transcribe or (lambda audio: transcribe_url(audio, max_seconds=max_seconds))
    sources, skipped = [], 0
    for it in _items(xml)[:limit]:
        if known is not None and known(it['audio']):
            skipped += 1   # already ingested: never spend CPU re-transcribing
            continue
        text = transcribe(it['audio'])
        if len(text) < 1500:
            continue
        sources.append(common.make_source(
            id=f'pod-{ch["channel_id"]}-{common.digest(it["audio"])[:10]}', source_id=ch['channel_id'], text=text,
            publisher=common.html_text(ch['name']), title=it['title'], url=it['audio'],
            published_at=feeds._iso(it['published_raw']), adapter='podcast_whisper', lang=ch.get('lang', 'en'),
            extra={'no_reproduction': True, 'persona_hint': ch.get('persona_hint'), 'transcript': 'local_whisper_' + MODEL_NAME}))
    status = 'ok' if sources else ('no_new_episodes' if skipped else 'no_transcript')
    return {'status': status, 'sources': sources, 'skipped_known': skipped}
