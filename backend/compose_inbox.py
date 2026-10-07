"""Review page + API for the fd20 compose inbox (live/compose_inbox.py). No publish endpoint exists.

GET  /compose-inbox?day=YYYY-MM-DD[&account=id]   HTML review page (one card per draft)
GET  /api/compose-inbox?day=...&account=...        rows as JSON
POST /api/compose-inbox/{draft_id}/review          {decision, reviewer, reason, text, expected_hash}
"""
from __future__ import annotations

import html
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from live import compose_inbox

router = APIRouter()


class Review(BaseModel):
    decision: str
    reviewer: str
    reason: str
    text: str
    expected_hash: str


@router.get('/api/compose-inbox')
def api_rows(day: str | None = None, account: str | None = None):
    return {'days': compose_inbox.days(), 'rows': compose_inbox.rows(day, account), 'publishing_enabled': False}


@router.post('/api/compose-inbox/{draft_id}/review')
def api_review(draft_id: str, body: Review):
    try:
        return compose_inbox.review(draft_id, **body.model_dump())
    except KeyError:
        raise HTTPException(404, 'draft not found')
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get('/compose-inbox', response_class=HTMLResponse)
def page(day: str | None = None, account: str | None = None):
    return render(compose_inbox.rows(day, account), day or next(iter(compose_inbox.days()), ''), live=True)


def _esc(text):
    return html.escape(text or '')


def _findings(row):
    out = []
    for f in row.get('findings') or []:
        out.append(f'<li class="{_esc(f.get("level"))}">{_esc(f.get("level"))}: {_esc(f.get("code"))}</li>')
    return '<ul class="f">' + ''.join(out[:12]) + '</ul>' if out else ''


def render(rows, day, *, live=False, summary=None):
    """Self-contained HTML. live=True adds the review form (POST to this server); static exports are read-only."""
    by_acct = {}
    for r in rows:
        by_acct.setdefault(r['account_id'], []).append(r)
    cards = []
    for acct, items in by_acct.items():
        head = items[0]
        cards.append(f'<h2>#{head.get("no", "")} {_esc(head.get("name") or acct)} '
                     f'<small>{_esc(acct)} · {_esc(head.get("beat"))} · {len(items)} 篇</small></h2>')
        for r in items:
            src = r.get('source') or {}
            arb = r.get('arbitration') or {}
            text = r.get('reviewed_text', r.get('text') or '')
            badge = r.get('review_status', 'pending')
            hold = ' hold' if r.get('held') else ''
            form = ''
            if live:
                form = (f'<div class="form" data-id="{_esc(r["id"])}" data-hash="{_esc(compose_inbox.text_hash(text))}">'
                        f'<textarea>{_esc(text)}</textarea>'
                        '<input class="who" placeholder="审稿人"><input class="why" placeholder="理由（必填）">'
                        + ''.join(f'<button data-d="{d}">{lab}</button>' for d, lab in
                                  (('approve', '可发'), ('minor_edit', '小改'), ('major_edit', '大改'), ('reject', '拒')))
                        + '<span class="msg"></span></div>')
            cards.append(
                f'<div class="card{hold}"><div class="meta">{"<b>【回看】</b> " if r.get("post_kind") == "archive_lookback" else ""}'
                f'{_esc(r.get("suggested_post_time_london", "")[11:16])} 建议发布 · '
                f'{_esc((r.get("post_format") or {}).get("type"))}/{_esc((r.get("post_format") or {}).get("length"))} · '
                f'帖型 {_esc(r.get("post_type"))} · 角度 <b>{_esc((r.get("angle") or {}).get("lens"))}</b> · '
                f'机检 {_esc(r.get("draft_status"))} · 仲裁 {_esc(arb.get("status"))} · <b>{_esc(badge)}</b></div>'
                f'<pre class="body">{_esc(text)}</pre>'
                f'<div class="src">来源：{_esc(src.get("publisher"))} — {_esc(src.get("title"))} '
                f'({_esc(str(src.get("published_at") or "")[:10])}) {_esc(src.get("lang"))}</div>'
                f'<div class="view">立场：{_esc((r.get("stance") or {}).get("account_view"))}</div>'
                f'{_findings(r)}{form}</div>')
    js = '<script src="/compose-inbox.js"></script>' if live else ''
    summ = f'<pre class="summary">{_esc(json.dumps(summary, ensure_ascii=False, indent=1))}</pre>' if summary else ''
    style = '<link rel="stylesheet" href="/compose-inbox.css">' if live else f'<style>{CSS}</style>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>FD 审稿台 {day}</title>{style}</head><body>
<h1>FD 审稿台 · {day} · {len(rows)} 篇（只审稿，不自动发布）</h1>{summ}{"".join(cards)}{js}</body></html>'''


# The dashboard CSP allows only same-origin scripts/styles, so the live page loads these as files.
CSS = '''body{font-family:-apple-system,"PingFang SC",sans-serif;margin:20px;max-width:980px;color:#0f1419}
h2{margin-top:28px;border-bottom:1px solid #ddd} h2 small{color:#536471;font-weight:400;font-size:13px}
.card{border:1px solid #e1e8ed;border-radius:10px;padding:10px 14px;margin:10px 0} .card.hold{background:#fff8e6}
.meta,.src,.view{color:#536471;font-size:12px;margin:4px 0} .body{white-space:pre-wrap;font-family:inherit;font-size:15px}
.f{font-size:12px;color:#8a6d3b;margin:4px 0} .f .hard{color:#c0392b} textarea{width:100%;height:140px}
.form input{margin:4px 4px 4px 0} .msg{margin-left:8px;color:#1d9bf0} .summary{font-size:11px;background:#f7f9f9;padding:8px}'''
JS = '''document.querySelectorAll('.form button').forEach(b=>b.onclick=async()=>{const f=b.closest('.form');
const body={decision:b.dataset.d,reviewer:f.querySelector('.who').value,reason:f.querySelector('.why').value,
text:f.querySelector('textarea').value,expected_hash:f.dataset.hash};
const r=await fetch('/api/compose-inbox/'+f.dataset.id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
f.querySelector('.msg').textContent=r.ok?'已记录 '+body.decision:('失败: '+(await r.json()).detail);});'''


@router.get('/compose-inbox.css')
def css():
    return Response(CSS, media_type='text/css')


@router.get('/compose-inbox.js')
def js():
    return Response(JS, media_type='application/javascript')
