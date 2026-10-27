// Cloudflare Worker on squint.nickymolina.com/*. Serves the landing page from landing/ on
// GitHub (so it stays up when the Mac mini is off, and a push updates it within 5 minutes) and
// passes everything else (the app under /app/ and /api) through the tunnel to the preview
// server. When the tunnel is down it answers /api with 503 offline and the app from its last
// cached copy. Deploy: paste this file as the `squint-edge` Worker (route squint.nickymolina.com/*).

const LANDING_BASE = 'https://raw.githubusercontent.com/nicolasdmolina/squint/main/landing/';
const LANDING_FILES = {
  '/': ['index.html', 'text/html; charset=utf-8'],
  '/index.html': ['index.html', 'text/html; charset=utf-8'],
  '/favicon.svg': ['favicon.svg', 'image/svg+xml'],
  '/og.png': ['og.png', 'image/png'],
};
const OFFLINE_MESSAGE = 'The live demo is offline right now. You can run Squint on your own Mac instead.';

const OFFLINE_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Squint</title>
<link rel="icon" href="/favicon.svg"><style>
:root{color-scheme:light dark;--bg:#faf9f6;--fg:#1c1b19;--muted:#5d5a54}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--fg:#ecebe6;--muted:#a19e96}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:17px/1.5 Geist,system-ui,sans-serif;padding:0 16px}main{max-width:32rem}
a{color:inherit}p{color:var(--muted)}</style></head><body><main><h1>Squint</h1>
<p>${OFFLINE_MESSAGE}</p><p><a href="/#download">Get Squint for Mac</a> · <a href="/">Home</a></p>
</main></body></html>`;

async function landing(file, type) {
  const res = await fetch(LANDING_BASE + file, { cf: { cacheTtl: 300, cacheEverything: true } });
  if (!res.ok) return new Response('Not found', { status: 502 });
  return new Response(res.body, { headers: { 'content-type': type, 'cache-control': 'public, max-age=300' } });
}

function originDown(res) {
  // 502: tunnel up, server down. 520-530: tunnel down. The server's own 503 busy is JSON.
  return res.status === 502 || (res.status === 503 && !res.headers.get('content-type')?.includes('json'))
    || (res.status >= 520 && res.status <= 530);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const html = { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache' };
    if (LANDING_FILES[url.pathname]) return landing(...LANDING_FILES[url.pathname]);
    if (url.pathname === '/app') return Response.redirect(`${url.origin}/app/`, 301);

    const api = url.pathname.startsWith('/api/');
    const cacheable = request.method === 'GET' && !api;
    let res = null;
    try {
      res = await fetch(request);
    } catch {
      res = null;
    }
    if (res && !originDown(res)) {
      if (cacheable && res.ok) {
        const copy = new Response(res.clone().body, res);
        copy.headers.set('cache-control', 'public, max-age=2592000');
        ctx.waitUntil(caches.default.put(request.url, copy));
      }
      return res;
    }
    if (api) {
      return Response.json({ error: { code: 'offline', message: OFFLINE_MESSAGE } },
        { status: 503, headers: { 'cache-control': 'no-store' } });
    }
    if (cacheable) {
      const cached = await caches.default.match(request.url);
      if (cached) return cached;
    }
    return new Response(OFFLINE_PAGE, { status: 503, headers: html });
  },
};
