"""Headless screenshot of one public chart page or one local HTML chart (run as a subprocess by live/media_real.py).

Reads one JSON job on stdin, writes a PNG, prints a JSON result line. A fresh browser context per job: no cookies,
no storage state, no profile directory, no login - never the box's desktop browser session. Local HTML jobs are
offline (every non-file request is aborted). Public pages: one page load, no clicks beyond closing nothing.

job: {"url": "https://..." | "html": "/abs/file.html", "out": "/abs/out.png", "viewport": [w, h], "dpr": 2,
      "selector": optional CSS selector to screenshot, "clip": optional [x, y, w, h], "wait_ms": 2500,
      "wait_for": optional selector, "timeout_ms": 45000, "ready_flag": optional JS expression that must be true,
      "hide": optional CSS selectors hidden before the shot (cookie / consent / geo banners: hidden, never clicked),
      "clip_js": optional JS expression returning [x, y, w, h] (page CSS px) to crop to, null -> fail,
      "text_probe": true -> result info.text = the page's visible text (first 2000 chars), for blank / wall checks,
      "color_scheme": "light" | "dark"}

Chromium: playwright's bundled build when installed, else FD_CHROME (default /usr/bin/google-chrome) headless.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def run(job):
    from playwright.sync_api import sync_playwright
    vw, vh = job.get('viewport') or (1280, 720)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:   # noqa: BLE001 - bundled chromium not installed
            browser = p.chromium.launch(headless=True, executable_path=os.environ.get('FD_CHROME', '/usr/bin/google-chrome'),
                                        args=['--headless=new', '--no-first-run', '--disable-extensions'])
        try:
            ctx = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=job.get('dpr', 2),
                                      locale=job.get('locale', 'en-US'), storage_state=None,
                                      user_agent=None, java_script_enabled=True, accept_downloads=False,
                                      color_scheme=job.get('color_scheme') or 'light')
            page = ctx.new_page()
            timeout = job.get('timeout_ms', 45000)
            if job.get('html'):
                page.route('**/*', lambda r: r.continue_() if r.request.url.startswith('file:') else r.abort())
                page.goto(Path(job['html']).resolve().as_uri(), timeout=timeout)
            else:
                page.goto(job['url'], timeout=timeout, wait_until='domcontentloaded')
            if job.get('wait_for'):
                page.wait_for_selector(job['wait_for'], timeout=timeout)
            if job.get('ready_flag'):
                page.wait_for_function(job['ready_flag'], timeout=timeout)
            page.wait_for_timeout(job.get('wait_ms', 1500))
            if job.get('hide'):
                page.add_style_tag(content=', '.join(job['hide']) + ' { display: none !important; }')
                page.wait_for_timeout(200)
            out = Path(job['out'])
            out.parent.mkdir(parents=True, exist_ok=True)
            clip = page.evaluate(job['clip_js']) if job.get('clip_js') else None
            if job.get('clip_js') and not clip:
                raise RuntimeError('clip_js found nothing to crop')
            if clip:
                x, y, w, h = [float(v) for v in clip]
                page.screenshot(path=str(out), clip={'x': x, 'y': y, 'width': w, 'height': h}, full_page=True)
            elif job.get('selector'):
                page.locator(job['selector']).first.screenshot(path=str(out))
            elif job.get('clip'):
                x, y, w, h = job['clip']
                page.screenshot(path=str(out), clip={'x': x, 'y': y, 'width': w, 'height': h})
            else:
                page.screenshot(path=str(out))
            info = page.evaluate('() => window.__chartInfo || null') if job.get('html') else None
            if job.get('text_probe'):
                info = {**(info or {}), 'text': page.evaluate('() => (document.body && document.body.innerText || "").slice(0, 2000)')}
            ctx.close()
        finally:
            browser.close()
    return {'ok': True, 'out': str(out), 'info': info}


def main():
    job = json.loads(sys.stdin.read())
    try:
        res = run(job)
    except Exception as exc:   # noqa: BLE001 - the caller falls back to a rendered chart
        res = {'ok': False, 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
    print(json.dumps(res))


if __name__ == '__main__':
    main()
