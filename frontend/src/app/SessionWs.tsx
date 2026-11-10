/**
 * FE-020 · WebSocket на время сессии: открыт, пока `GET /me` дал «ready» (FR-SESS-02).
 * `notification.created` перечитывает колокольчик (FE-010).
 * `session.ended` (или закрытие 4401) — сессии нет: забыть её и вернуть на вход с текущим адресом.
 * Step-up и TOTP меняют id сессии (FR-SESS-03): соединение старого id получает `session.ended`, хотя
 * cookie уже новая. Поэтому сначала `GET /me`: ответил — соединение открывается заново.
 */
import { useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { NOTIFICATIONS_KEY } from '../features/home/NotificationBell';
import { api } from '../shared/api/client';

import type { WsClientOptions } from '../shared/ws/client';
import { WsProvider } from '../shared/ws/WsProvider';
import { useLocation, useNavigate } from './router';
import { useSession } from './session';

export function SessionWs({ children, options }: { children: ReactNode; options?: Partial<WsClientOptions> }) {
  const { session, clear } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  return (
    <WsProvider
      enabled={session.state === 'ready'}
      {...(options ? { options } : {})}
      onUserEvent={(event) => {
        if (event.event === 'notification.created') void queryClient.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
      }}
      onSessionEnded={(_reason, restart) => {
        const end = () => {
          clear();
          const next = `${location.pathname}${location.search}`;
          navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
        };
        api.GET('/me').then(({ response }) => (response.ok ? restart() : end()), end);
      }}
    >
      {children}
    </WsProvider>
  );
}
