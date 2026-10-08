// Review-console decisions, one private Vercel Blob per draft: decisions/<day>/<draft id>.json.
// GET  /api/decisions?day=YYYY-MM-DD -> {day, decisions: {id: decision}}
// POST /api/decisions {day, id, account_id, action: approve|published|unpublish|hold|rewrite|edit|clear, text?, note?}
//   -> {ok, decision}
//   text: edited post text ('' or null = keep the draft text); note: HOLD reason / rewrite instruction.
//   published / unpublish: the 已发 flag, set by /admin and by the ops page checkbox. A missing text / note keeps the
//   stored one, so ticking 已发 on the ops page never wipes an admin's edit. The stored action is always one of
//   approve|published|hold|rewrite|edit|clear (older readers only look at `action`); `published` (bool) is the flag
//   and `before_publish` the action unpublish restores. Blobs written before the flag existed have no `published`
//   key: action 'published' alone means published.
// No auth: the site is unlisted by choice (noindex on both pages).
import { get, list, put } from '@vercel/blob';

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[A-Za-z0-9_.-]{1,100}$/;

// <shared> next-decision rule; build_ops_dashboard.py / build_admin_console.py inline this block into / and /admin
const ACTIONS = new Set(['approve', 'published', 'unpublish', 'hold', 'rewrite', 'edit', 'clear']);
function isPublished(x) { return !!x && (x.published === true || (x.published !== false && x.action === 'published')); }
function lastAction(history) {   // newest real action before the 已发 flag (blobs without before_publish)
  for (const h of [...(history || [])].reverse()) {
    if (h.action === 'clear') return null;
    if (h.action !== 'published' && h.action !== 'unpublish') return h.action;
  }
  return null;
}
function nextDecision(prev, b, at) {
  prev = prev || {};
  const was = isPublished(prev);
  const prevAct = prev.action && prev.action !== 'clear' ? prev.action : '';
  const has = k => Object.prototype.hasOwnProperty.call(b, k);
  const str = v => (typeof v === 'string' && v.trim() ? v.slice(0, 20000) : null);
  const flag = b.action === 'published' || b.action === 'unpublish';
  let action = b.action, before = null, published;
  let text = flag && !has('text') ? (prev.text || null) : str(b.text);
  let note = typeof b.note === 'string' ? b.note.slice(0, 4000) : (flag ? (prev.note || '') : '');
  if (action === 'published') {
    published = true;   // stored as 'published' so action-only readers see ready + posted
    before = was ? (prev.before_publish || null) : (prevAct || null);
  } else if (action === 'unpublish') {
    published = false;
    action = (was ? prev.before_publish || lastAction(prev.history) : prevAct) || (text ? 'edit' : 'clear');
  } else if (action === 'clear') {
    published = false;
  } else {
    published = typeof b.published === 'boolean' ? b.published : was;   // an admin action keeps the 已发 flag
    if (published) before = action;
  }
  if (action === 'clear') { text = null; note = ''; }
  const entry = { action, text, note, at, published, before_publish: before };
  const history = [...(prev.history || []), { action: b.action, text, note, at }].slice(-50);
  return { day: b.day, id: b.id, account_id: String(b.account_id || prev.account_id || ''), ...entry, history };
}
// </shared>

async function readBlob(pathname) {
  const r = await get(pathname, { access: 'private', useCache: false });
  return r ? JSON.parse(await new Response(r.stream).text()) : null;
}

async function body(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') return JSON.parse(req.body);
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

export { isPublished, nextDecision };

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  try {
    if (req.method === 'GET') {
      const day = String(req.query.day || '');
      if (!DAY.test(day)) return res.status(400).json({ error: 'day' });
      const out = {};
      let cursor;
      do {
        const page = await list({ prefix: `decisions/${day}/`, cursor, limit: 1000 });
        const rows = await Promise.all(page.blobs.map(b => readBlob(b.pathname).catch(() => null)));
        for (const d of rows) if (d && d.id) out[d.id] = d;
        cursor = page.hasMore ? page.cursor : undefined;
      } while (cursor);
      return res.status(200).json({ day, decisions: out });
    }
    if (req.method === 'POST') {
      const b = await body(req);
      if (!DAY.test(b.day || '') || !ID.test(b.id || '') || !ACTIONS.has(b.action)) return res.status(400).json({ error: 'bad request' });
      const path = `decisions/${b.day}/${b.id}.json`;
      const prev = await readBlob(path).catch(() => null);
      const decision = nextDecision(prev, b, new Date().toISOString());
      await put(path, JSON.stringify(decision), {
        access: 'private', addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json',
      });
      return res.status(200).json({ ok: true, decision });
    }
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ error: 'method' });
  } catch (e) {
    return res.status(500).json({ error: String((e && e.message) || e).slice(0, 300) });
  }
}
