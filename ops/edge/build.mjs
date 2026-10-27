// Inline the landing page into the Worker: node ops/edge/build.mjs → ops/edge/dist/worker.js
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const here = new URL('.', import.meta.url);
const read = p => readFileSync(new URL(p, here), 'utf8');
const out = read('worker.js')
  .replace('__LANDING_HTML__', () => JSON.stringify(read('../../landing/index.html')))
  .replace('__FAVICON_SVG__', () => JSON.stringify(read('../../landing/favicon.svg')));
mkdirSync(new URL('dist/', here), { recursive: true });
writeFileSync(new URL('dist/worker.js', here), out);
console.log(`dist/worker.js ${(out.length / 1024).toFixed(1)} KB`);
