/** Точка входа SPA (INF-003). Роутинг, провайдеры и layout — трек FE (src/app). */
import '@mantine/core/styles.css';
import './shared/ui/app.css';
import './shared/ui/ui.css';
import './shared/i18n';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';

const container = document.getElementById('root');
if (!container) {
  throw new Error('Нет элемента #root');
}

/** FE-001: в режиме `npm run dev:mock` API отвечают моки MSW. В сборку для стендов модуль
 *  моков не попадает: условие известно на этапе сборки, и Vite выбрасывает ветку целиком. */
async function prepare(): Promise<void> {
  if (import.meta.env.MODE === 'mock') {
    const { startMocks } = await import('./shared/api/mocks/browser');
    await startMocks();
  }
}

void prepare().then(() => {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
