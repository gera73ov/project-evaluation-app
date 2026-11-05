/**
 * FE-001 · запуск моков в браузере (`npm run dev:mock`): Service Worker MSW перехватывает
 * `/api/v1/*` и WebSocket, в углу экрана — переключатель роли. В production-сборку модуль
 * не попадает: main.tsx импортирует его только при `import.meta.env.MODE === 'mock'`.
 */
import { setupWorker } from 'msw/browser';

import { buildHandlers } from './handlers';
import { loadPersona } from './personas';
import { mountRoleSwitcher } from './RoleSwitcher';

export async function startMocks(): Promise<void> {
  loadPersona();
  const worker = setupWorker(...buildHandlers({ latencyMs: 150 }));
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
  mountRoleSwitcher();
}
