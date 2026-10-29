// node --test ops/edge/worker.test.mjs
import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

const store = new Map();
globalThis.caches = {
  default: {
    put: async (k, r) => store.set(String(k), await r.text()),
    match: async k => (store.has(String(k)) ? new Response(store.get(String(k))) : undefined),
  },
};
let backends; // host -> (Request) => Response
const seen = [];
globalThis.fetch = async (target, init = {}) => {
  const url = new URL(String(target.url ?? target));
  if (url.hostname === 'nicolasdmolina.github.io') return new Response(`pages ${url.pathname}`);
  seen.push({ host: url.hostname, headers: new Headers(init.headers) });
  const handler = backends[url.hostname];
  if (!handler) throw new TypeError('fetch failed');
  return handler(new Request(url, init));
};
const worker = (await import(new URL('./worker.js', import.meta.url))).default;

async function go(path, { method = 'GET', env = {}, headers = {} } = {}) {
  const pending = [];
  const res = await worker.fetch(
    new Request(`https://squint.nickymolina.com${path}`, { method, headers }),
    env, { waitUntil: p => pending.push(p) });
  await Promise.all(pending);
  return res;
}

beforeEach(() => {
  store.clear();
  seen.length = 0;
  backends = {};
});

test('pages come from GitHub Pages under /squint', async () => {
  assert.equal(await (await go('/')).text(), 'pages /squint/');
  assert.equal(await (await go('/app/assets/x.js')).text(), 'pages /squint/app/assets/x.js');
  assert.equal((await go('/app')).status, 301);
  assert.equal((await go('/', { method: 'POST' })).status, 405);
});

test('api goes to the tunnel origin by default and passes its own errors through', async () => {
  backends['squint.nickymolina.com'] = () => Response.json({ error: { code: 'busy' } }, { status: 503 });
  const res = await go('/api/status');
  assert.equal((await res.json()).error.code, 'busy');
});

test('a down backend fails over to the next and is tried last for a while', async () => {
  const env = { BACKENDS: 'https://a.example, https://b.example', EDGE_SECRET: 's' };
  backends['a.example'] = () => new Response('bad gateway', { status: 502 });
  backends['b.example'] = () => Response.json({ ok: true });
  assert.deepEqual(await (await go('/api/status', { env })).json(), { ok: true });
  assert.deepEqual(seen.map(s => s.host), ['a.example', 'b.example']);
  seen.length = 0;
  await go('/api/status', { env });
  assert.deepEqual(seen.map(s => s.host), ['b.example']);
});

test('every backend down answers offline', async () => {
  const res = await go('/api/status', { env: { BACKENDS: 'https://gone.example' } });
  assert.equal(res.status, 503);
  assert.equal((await res.json()).error.code, 'offline');
});

test('cloud backends get the edge secret and client IP; spoofed headers are dropped', async () => {
  backends['a.example'] = () => Response.json({});
  backends['squint.nickymolina.com'] = () => new Response('', { status: 530 });
  const headers = { 'cf-connecting-ip': '1.2.3.4', 'x-squint-edge': 'forged', 'x-squint-client': '6.6.6.6' };
  await go('/api/status', { env: { BACKENDS: 'origin,https://a.example', EDGE_SECRET: 's' }, headers });
  const [origin, cloud] = seen;
  assert.equal(origin.headers.get('x-squint-edge'), null);
  assert.equal(origin.headers.get('x-squint-client'), null);
  assert.equal(cloud.headers.get('x-squint-edge'), 's');
  assert.equal(cloud.headers.get('x-squint-client'), '1.2.3.4');
});
