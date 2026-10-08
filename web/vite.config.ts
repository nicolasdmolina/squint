import react from '@vitejs/plugin-react';
import { defineConfig, type PluginOption } from 'vite';
import { squintMockApi } from './mock/plugin.ts';

// `npm run dev`      -> proxies /api to the Python server on 127.0.0.1:8017
// `npm run dev:mock` -> serves a contract-shaped mock API instead (dev only, never built)
export default defineConfig(({ command, mode }) => {
  const mock = command === 'serve' && mode === 'mock';
  const plugins: PluginOption[] = [react()];
  if (mock) plugins.push(squintMockApi());
  return {
    plugins,
    server: {
      host: '127.0.0.1',
      port: 5317,
      strictPort: true,
      proxy: mock ? undefined : { '/api': { target: 'http://127.0.0.1:8017', changeOrigin: false } },
    },
    preview: { host: '127.0.0.1', port: 5318, strictPort: true },
    build: { outDir: 'dist', emptyOutDir: true, target: 'es2022', assetsInlineLimit: 0 },
  };
});
