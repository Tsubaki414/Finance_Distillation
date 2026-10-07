// Vercel Edge Middleware: HTTP basic auth for the private review console (/admin) and its API (/api/*).
// The public ops dashboard (/, /<day>.csv) is not matched and stays open. Any user name; the password is the
// ADMIN_PASSWORD env var (production). No password configured -> everything matched stays locked.
export const config = { matcher: ['/admin', '/admin/:path*', '/api/:path*'] };

function same(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export default function middleware(request) {
  const pw = process.env.ADMIN_PASSWORD || '';
  const auth = request.headers.get('authorization') || '';
  if (pw && auth.startsWith('Basic ')) {
    try {
      const raw = new TextDecoder().decode(Uint8Array.from(atob(auth.slice(6)), c => c.charCodeAt(0)));
      if (same(raw.slice(raw.indexOf(':') + 1), pw)) return;   // continue to the page / function
    } catch (_) { /* malformed header -> 401 */ }
  }
  return new Response('Authentication required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="FD admin", charset="UTF-8"', 'Cache-Control': 'no-store' },
  });
}
