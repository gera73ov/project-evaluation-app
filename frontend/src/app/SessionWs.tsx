/**
 * FE-020 · WebSocket на время сессии: открыт, пока `GET /me` дал «ready» (FR-SESS-02).
 * `notification.created` перечитывает колокольчик (FE-010).
 * `session.ended` (или закрытие 4401) — сессии нет: забыть её и вернуть на вход с текущим адресом.
 */
import { useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { NOTIFICATIONS_KEY } from '../features/home/NotificationBell';

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
      onSessionEnded={() => {
        clear();
        const next = `${location.pathname}${location.search}`;
        navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
      }}
    >
      {children}
    </WsProvider>
  );
}
