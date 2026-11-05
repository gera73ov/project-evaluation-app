/** Каркас приложения (INF-003): провайдеры. Экраны добавляет трек FE. */
import { MantineProvider, Title } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

const queryClient = new QueryClient();

export function App() {
  const { t } = useTranslation();
  return (
    <QueryClientProvider client={queryClient}>
      <MantineProvider>
        <Title order={1}>{t('app.title')}</Title>
      </MantineProvider>
    </QueryClientProvider>
  );
}
