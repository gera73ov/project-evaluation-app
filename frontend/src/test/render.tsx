/** FE-003 · отрисовка приложения на маршруте и ответы-переопределения для моков. */
import { MantineProvider } from '@mantine/core';
import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import type { ReactElement } from 'react';

import { App, createQueryClient } from '../app/App';
import type { WsClientOptions } from '../shared/ws/client';
import { RouterProvider } from '../app/router';
import { theme } from '../shared/ui/theme';

export function renderApp(path = '/', wsOptions?: Partial<WsClientOptions>) {
  window.history.replaceState(null, '', path);
  return render(<App queryClient={createQueryClient()} {...(wsOptions ? { wsOptions } : {})} />);
}

export function problem(status: number, code: string, extra: Record<string, unknown> = {}) {
  return HttpResponse.json(
    {
      type: `https://estimator.local/errors/${code}`,
      title: code,
      status,
      code,
      error_id: 'err-1',
      ...extra,
    },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );
}

export const api = (path: string) => `*/api/v1${path}`;
export { http, HttpResponse };

/** Отдельный компонент в провайдерах приложения (тема, i18n, кэш запросов, роутер). */
export function renderUi(ui: ReactElement) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MantineProvider theme={theme}>
        <RouterProvider>{ui}</RouterProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}
