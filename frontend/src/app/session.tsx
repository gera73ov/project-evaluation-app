/**
 * FE-003 · состояние сессии по `GET /me` (FR-SESS-01, FR-2FA-04, FR-SA-02).
 *
 * - 200 — пользователь вошёл (`me`);
 * - 401 UNAUTHENTICATED — нет сессии, экран входа;
 * - 403 PASSWORD_CHANGE_REQUIRED — пароль истёк, доступны только смена пароля и выход (CR-003);
 * - 403 TOTP_ENROLL_REQUIRED — сессия до подключения TOTP, доступно только подключение и выход;
 * - 503 APP_SETUP_IN_PROGRESS — мастер первичной настройки не завершён.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useMemo, type ReactNode } from 'react';

import { api, type components } from '../shared/api/client';
import { ApiError, call } from '../shared/api/problem';

export type Me = components['schemas']['Me'];
export type SystemRole = components['schemas']['SystemRole'];

export type Session =
  | { state: 'loading' }
  | { state: 'anonymous' }
  | { state: 'enroll' }
  | { state: 'password_change' }
  | { state: 'setup' }
  | { state: 'error'; error: unknown }
  | { state: 'ready'; me: Me };

export const ME_KEY = ['me'] as const;

export function sessionFrom(data: Me | undefined, error: unknown, pending: boolean): Session {
  if (data) return { state: 'ready', me: data };
  if (pending) return { state: 'loading' };
  if (error instanceof ApiError) {
    if (error.status === 401) return { state: 'anonymous' };
    if (error.code === 'PASSWORD_CHANGE_REQUIRED') return { state: 'password_change' };
    if (error.code === 'TOTP_ENROLL_REQUIRED') return { state: 'enroll' };
    if (error.code === 'APP_SETUP_IN_PROGRESS') return { state: 'setup' };
  }
  return { state: 'error', error };
}

interface SessionValue {
  session: Session;
  /** Перечитать /me (после входа, подключения TOTP, смены профиля). */
  refresh: () => Promise<void>;
  /** Забыть сессию на клиенте (после выхода): кэш запросов очищается. */
  clear: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ME_KEY,
    queryFn: () => call(() => api.GET('/me')),
    retry: false,
    staleTime: 60_000,
  });
  const value = useMemo<SessionValue>(
    () => ({
      session: sessionFrom(query.data, query.error, query.isPending),
      async refresh() {
        await client.invalidateQueries({ queryKey: ME_KEY });
      },
      clear() {
        client.clear();
        void client.invalidateQueries({ queryKey: ME_KEY });
      },
    }),
    [client, query.data, query.error, query.isPending],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession вне SessionProvider');
  return value;
}

export function hasRole(me: Me, roles: readonly SystemRole[] | undefined): boolean {
  return !roles || roles.some((role) => me.system_roles.includes(role));
}
