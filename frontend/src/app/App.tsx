/** Каркас приложения (INF-003, FE-003): провайдеры, тема, nonce для стилей Mantine, роутинг. */
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { cspNonce, theme } from '../shared/ui/theme';
import { RouterProvider } from './router';
import { AppRoutes } from './Routes';
import { SessionProvider } from './session';

export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
}

export function App({ queryClient = createQueryClient() }: { queryClient?: QueryClient }) {
  const nonce = cspNonce();
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} {...(nonce ? { getStyleNonce: () => nonce } : {})}>
        <RouterProvider>
          <SessionProvider>
            <AppRoutes />
          </SessionProvider>
        </RouterProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}
