/**
 * FE-003 · общая обвязка тестов компонентов: моки MSW (FE-001) в Node, jsdom-заглушки для
 * Mantine, i18n, чистый адрес и кэш между тестами.
 */
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll } from 'vitest';

import '../shared/i18n';
import { resetDemoAuth } from '../shared/api/mocks/demoAuth';
import { resetDemoDiscussions } from '../shared/api/mocks/demoDiscussions';
import { resetDemoDocuments } from '../shared/api/mocks/demoDocuments';
import { resetDemoOutcome } from '../shared/api/mocks/demoOutcome';
import { resetDemoPortfolio } from '../shared/api/mocks/demoPortfolio';
import { resetDemoSnapshots } from '../shared/api/mocks/demoSnapshots';
import { resetDemoSystem } from '../shared/api/mocks/demoSystem';
import { resetDemoTree } from '../shared/api/mocks/demoTree';
import { buildHandlers } from '../shared/api/mocks/handlers';
import { PERSONAS, type Persona } from '../shared/api/mocks/personas';

// jsdom не реализует matchMedia и ResizeObserver, а Mantine их вызывает; тесты в среде node их не ждут
const browser = typeof window !== 'undefined';
if (browser) {
  window.matchMedia ??= (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.HTMLElement.prototype.scrollIntoView ??= () => {};
}

export const persona: { current: Persona } = { current: PERSONAS.expert };
export const server = setupServer(...buildHandlers({ persona: () => persona.current }));

// Тесты в среде node (моки FE-001, линтер) поднимают свой сервер MSW или он им не нужен:
// второй перехватчик WebSocket удвоил бы ответы.
if (browser) {
  beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
  afterEach(() => {
    cleanup();
    server.resetHandlers();
    persona.current = PERSONAS.expert;
    resetDemoTree();
    resetDemoDiscussions();
    resetDemoDocuments();
    resetDemoOutcome();
    resetDemoPortfolio();
    resetDemoSnapshots();
    resetDemoSystem();
    resetDemoAuth();
    window.history.replaceState(null, '', '/');
  });
  afterAll(() => server.close());
}
