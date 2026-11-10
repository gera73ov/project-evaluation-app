/**
 * FE-001 · запуск моков в браузере (`npm run dev:mock`): Service Worker MSW перехватывает
 * `/api/v1/*` и WebSocket, в углу экрана — переключатель роли. В production-сборку модуль
 * не попадает: main.tsx импортирует его только при `import.meta.env.MODE === 'mock'`.
 */
import { setupWorker } from "msw/browser";

import { restartDemoSetup } from "./demoSetup";
import { buildHandlers } from "./handlers";
import { loadPersona } from "./personas";
import { mountRoleSwitcher } from "./RoleSwitcher";

export async function startMocks(): Promise<void> {
  loadPersona();
  // FE-064: `?demo=setup` — мастер первичной настройки с начала, как после create-superadmin
  if (new URLSearchParams(window.location.search).get("demo") === "setup")
    restartDemoSetup();
  const worker = setupWorker(...buildHandlers({ latencyMs: 150 }));
  await worker.start({ onUnhandledRequest: "bypass", quiet: true });
  mountRoleSwitcher();
}
