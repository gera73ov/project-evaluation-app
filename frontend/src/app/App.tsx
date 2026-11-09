/** Каркас приложения (INF-003, FE-003): провайдеры, тема, nonce для стилей Mantine, роутинг. */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { cspNonce, theme } from '../shared/ui/theme';
import { RouterProvider } from './router';
import { AppRoutes } from './Routes';
import { SessionProvider } from './session';
import { SessionWs } from './SessionWs';
import type { WsClientOptions } from '../shared/ws/client';

export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
}

export function App({
  queryClient = createQueryClient(),
  wsOptions,
}: {
  queryClient?: QueryClient;
  /** Тесты подставляют имитатор сокета и короткие задержки (FE-020). */
  wsOptions?: Partial<WsClientOptions>;
}) {
  const nonce = cspNonce();
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} {...(nonce ? { getStyleNonce: () => nonce } : {})}>
        <RouterProvider>
          <SessionProvider>
            <SessionWs {...(wsOptions ? { options: wsOptions } : {})}>
              <AppRoutes />
            </SessionWs>
          </SessionProvider>
        </RouterProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}
