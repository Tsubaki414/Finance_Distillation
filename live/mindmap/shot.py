"""Headless chrome screenshot (run with a python that has playwright; FD_MINDMAP_PYTHON). argv: html png."""
import json
import sys

from playwright.sync_api import sync_playwright

html, png = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1700, 'height': 1000}, device_scale_factor=2)
    pg.goto('file://' + html)
    pg.wait_for_function("document.body.dataset.ready==='1'", timeout=15000)
    pg.wait_for_timeout(300)
    # layout self-check: no two label boxes overlap, nothing outside the page
    bad = pg.evaluate('''()=>{const r=[...document.querySelectorAll('.node span')].map(e=>{const b=e.getBoundingClientRect();return [b.left,b.top,b.right,b.bottom,e.textContent]});
      let o=0;for(let i=0;i<r.length;i++){for(let j=i+1;j<r.length;j++){const a=r[i],c=r[j];
      if(a[0]<c[2]-1&&c[0]<a[2]-1&&a[1]<c[3]-1&&c[1]<a[3]-1)o++}}
      const out=r.filter(a=>a[2]>document.documentElement.scrollWidth+1).length;return [o,out]}''')
    h = pg.evaluate('document.documentElement.scrollHeight')
    pg.screenshot(path=png, full_page=True)
    b.close()
print(json.dumps({'css_w': 1700, 'css_h': h, 'overlaps': bad[0], 'overflow': bad[1]}))
