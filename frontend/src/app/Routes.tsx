/**
 * FE-003 · выбор экрана по адресу и гарды доступа (FR-2FA-04, FR-SA-02):
 * нет сессии → /login?next=…; сессия до подключения TOTP → только /enroll-totp; мастер не
 * завершён → «Приложение настраивается»; системная роль не подходит → «Страница не найдена».
 */
import { Loader } from '@mantine/core';

import { ErrorText } from '../shared/ui/ErrorText';
import { AppShell } from './AppShell';
import { NotFound } from './Placeholder';
import { Redirect, matchPath, useLocation } from './router';
import { findRoute } from './routeTable';
import { hasRole, useSession } from './session';

const DEFAULT_PATH = '/';

/** Куда вернуться после входа: только внутренний путь (без //host и схем). */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : DEFAULT_PATH;
}

function Loading() {
  return (
    <div className="page-center">
      <Loader aria-label="loading" />
    </div>
  );
}

export function AppRoutes() {
  const { pathname, search } = useLocation();
  const { session } = useSession();
  const found = findRoute(pathname, matchPath);
  const access = found?.route.access ?? 'private';

  if (access === 'public') return <>{found?.route.render(found.params)}</>;
  if (session.state === 'loading') return <Loading />;
  if (session.state === 'setup') return <Redirect to="/setup-in-progress" />;
  if (session.state === 'anonymous') {
    return <Redirect to={`/login?next=${encodeURIComponent(pathname + search)}`} />;
  }
  if (session.state === 'enroll') {
    return access === 'enroll' ? <>{found?.route.render(found.params)}</> : <Redirect to="/enroll-totp" />;
  }
  if (session.state === 'error') {
    return (
      <div className="page-center">
        <ErrorText error={session.error} />
      </div>
    );
  }
  const me = session.me;
  if (access === 'enroll') return <Redirect to={DEFAULT_PATH} />;
  if (!found || !hasRole(me, found.route.roles)) {
    return (
      <AppShell me={me}>
        <NotFound />
      </AppShell>
    );
  }
  return (
    <AppShell me={me} active={found.route.nav}>
      {found.route.render(found.params)}
    </AppShell>
  );
}
