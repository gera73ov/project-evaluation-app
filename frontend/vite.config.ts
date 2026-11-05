/**
 * INF-003 · сборка SPA.
 * SEC-WEB-03: в собранном index.html нет inline-скриптов, внешних CDN нет — всё в бандле;
 * проверка — scripts/check-build.mjs после `vite build`.
 */
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // FE-001: Service Worker MSW лежит отдельно и копируется только в режиме моков
  publicDir: mode === 'mock' ? 'mock-public' : false,
  build: {
    outDir: 'dist',
    sourcemap: false,
    // полифилл modulepreload Vite вставляет inline-скриптом — он не нужен целевым браузерам
    modulePreload: { polyfill: false },
    // ничего не встраивать в data: URI — ресурсы отдаются файлами с того же origin
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    strictPort: true,
    // при `npm run dev` API и WebSocket идут на dev-стенд в docker compose (deploy/compose).
    // Сертификат стенда проверяется: запуск с NODE_EXTRA_CA_CERTS=../deploy/compose/certs/ca.crt
    // в режиме моков (`npm run dev:mock`) запросы перехватывает MSW, прокси не нужен
    proxy: mode === 'mock' ? undefined : { '/api': { target: 'https://localhost:8443', ws: true } },
    // моки читают контракты прямо из ../contracts (FE-001)
    fs: { allow: ['.', '../contracts'] },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.mjs'],
    restoreMocks: true,
  },
}));
