// Cloudflare Worker on squint.nickymolina.com/*.
//
// Pages: the landing page and the web UI (/app/) come from GitHub Pages, built by
// .github/workflows/site.yml, so they stay up whatever the checking servers are doing.
// /api: tried on each backend in BACKENDS order, moving on when one is unreachable, down or too
// slow. Preview checks answer in one request and keep nothing between requests, so any backend
// can take any call. When every backend is down, /api answers 503 offline and the app shows its
// example results instead.
//
// BACKENDS (a Worker variable): comma-separated base URLs; "origin" means this hostname's own
// origin (the Mac mini tunnel). Default: "origin".
// EDGE_SECRET (a Worker secret): sent to every other backend as X-Squint-Edge, with the visitor's IP as
// X-Squint-Client; backends started with the same SQUINT_EDGE_SECRET refuse /api calls without it.
// Deploy: upload this file as the `squint-edge` Worker (route squint.nickymolina.com/*).

const PAGES = 'https://nicolasdmolina.github.io/squint';
const OFFLINE_MESSAGE = 'The live demo is offline right now. You can run Squint on your own Mac instead.';
const TIMEOUT_MS = { analyze: 35_000, other: 8_000 }; // a preview check waits up to 25 s server-side
const DOWN_FOR_S = 60; // skip a backend that just failed, per data center

function originDown(res) {
  // 502: tunnel up, server down. 520-530: tunnel down. The server's own 503 busy is JSON.
  return res.status === 502 || (res.status === 503 && !res.headers.get('content-type')?.includes('json'))
    || (res.status >= 520 && res.status <= 530);
}

async function pages(url) {
  const res = await fetch(PAGES + url.pathname + url.search, { cf: { cacheTtl: 300, cacheEverything: true } });
  const out = new Response(res.body, res);
  out.headers.set('cache-control', res.ok ? 'public, max-age=300' : 'no-cache');
  return out;
}

const downKey = (name) => `https://squint-edge.internal/down/${encodeURIComponent(name)}`;

async function markDown(name) {
  await caches.default.put(downKey(name), new Response('1', { headers: { 'cache-control': `max-age=${DOWN_FOR_S}` } }));
}

async function api(request, url, env, ctx) {
  const backends = (env.BACKENDS || 'origin').split(',').map(s => s.trim()).filter(Boolean);
  const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer();
  const timeout = url.pathname === '/api/analyze' ? TIMEOUT_MS.analyze : TIMEOUT_MS.other;
  // A backend marked down is tried last rather than skipped, in case every one is marked.
  const marked = await Promise.all(backends.map(b => caches.default.match(downKey(b))));
  const order = backends.filter((_, i) => !marked[i]).concat(backends.filter((_, i) => marked[i]));
  const headers = new Headers(request.headers);
  headers.delete('x-squint-edge');
  headers.delete('x-squint-client');
  const cloud = new Headers(headers);
  if (env.EDGE_SECRET) {
    cloud.set('x-squint-edge', env.EDGE_SECRET);
    cloud.set('x-squint-client', request.headers.get('cf-connecting-ip') || '');
  }
  for (const name of order) {
    const target = name === 'origin' ? url.href : name.replace(/\/$/, '') + url.pathname + url.search;
    try {
      const res = await fetch(target, {
        method: request.method, headers: name === 'origin' ? headers : cloud, body, redirect: 'manual',
        signal: AbortSignal.timeout(timeout),
      });
      if (!originDown(res)) return res;
    } catch {
      // unreachable or too slow: try the next one
    }
    ctx.waitUntil(markDown(name));
  }
  return Response.json({ error: { code: 'offline', message: OFFLINE_MESSAGE } },
    { status: 503, headers: { 'cache-control': 'no-store' } });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) return api(request, url, env, ctx);
    if (url.pathname === '/app') return Response.redirect(`${url.origin}/app/`, 301);
    if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', { status: 405 });
    return pages(url);
  },
};
