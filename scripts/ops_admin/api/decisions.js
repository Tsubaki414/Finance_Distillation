// Review-console decisions, one private Vercel Blob per draft: decisions/<day>/<draft id>.json.
// GET  /api/decisions?day=YYYY-MM-DD -> {day, decisions: {id: decision}}
// POST /api/decisions {day, id, account_id, action: approve|hold|rewrite|edit|clear, text?, note?} -> {ok, decision}
//   text: edited post text ('' or null = keep the draft text); note: HOLD reason / rewrite instruction.
// Basic auth is enforced by middleware.js; checked again here so the function is never open on its own.
import { get, list, put } from '@vercel/blob';

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[A-Za-z0-9_.-]{1,100}$/;
const ACTIONS = new Set(['approve', 'hold', 'rewrite', 'edit', 'clear']);

function authorised(req) {
  const pw = process.env.ADMIN_PASSWORD || '';
  const h = req.headers.authorization || '';
  if (!pw || !h.startsWith('Basic ')) return false;
  const raw = Buffer.from(h.slice(6), 'base64').toString('utf8');
  const given = Buffer.from(raw.slice(raw.indexOf(':') + 1));
  const want = Buffer.from(pw);
  return given.length === want.length && bytesEqual(given, want);
}

function bytesEqual(a, b) {
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

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

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (!authorised(req)) return res.status(401).json({ error: 'auth' });
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
      const { day, id } = b;
      if (!DAY.test(day || '') || !ID.test(id || '') || !ACTIONS.has(b.action)) return res.status(400).json({ error: 'bad request' });
      const path = `decisions/${day}/${id}.json`;
      const prev = await readBlob(path).catch(() => null);
      const at = new Date().toISOString();
      const text = typeof b.text === 'string' && b.text.trim() ? b.text.slice(0, 20000) : null;
      const note = typeof b.note === 'string' ? b.note.slice(0, 4000) : '';
      const entry = { action: b.action, text, note, at };
      const history = [...((prev && prev.history) || []), entry].slice(-50);
      const decision = { day, id, account_id: String(b.account_id || (prev && prev.account_id) || ''), ...entry, history };
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
