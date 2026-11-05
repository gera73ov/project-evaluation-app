/** Точка входа SPA (INF-003). Роутинг, провайдеры и layout — трек FE (src/app). */
import '@mantine/core/styles.css';
import './shared/ui/app.css';
import './shared/i18n';

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';

const container = document.getElementById('root');
if (!container) {
  throw new Error('Нет элемента #root');
}
createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
