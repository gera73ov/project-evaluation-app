/**
 * FE-003 · шапка приложения (DESIGN.md 5.1): логотип, пункты по ролям (без права — не рисуются),
 * распорка, колокольчик (FE-010), пользователь с меню «Профиль» и «Выйти».
 */
import { Menu } from '@mantine/core';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../shared/api/client';
import { call } from '../shared/api/problem';
import { userColor } from '../shared/ui/userColor';
import { OfflineBanner } from '../shared/ws/OfflineBanner';
import { SessionExtend } from '../features/auth/SessionExtend';
import { NotificationBell } from '../features/home/NotificationBell';
import { Link, useNavigate } from './router';
import { NAV, type NavKey } from './routeTable';
import { hasRole, useSession, type Me } from './session';

export function initials(fullName: string): string {
  const [last = '', first = ''] = fullName.trim().split(/\s+/);
  return (last.charAt(0) + first.charAt(0)).toUpperCase();
}

/** «Иванов Иван» → «Иванов И.» */
export function shortName(fullName: string): string {
  const parts = fullName.trim().split(/\s+/);
  // Уже сокращённое имя («И. Иванов») показываем как есть.
  if (parts.some((part) => part.endsWith('.'))) return parts.join(' ');
  const [last = '', first = ''] = parts;
  return first ? `${last} ${first.charAt(0)}.` : last;
}

export function AppShell({ me, active, children }: { me: Me; active?: NavKey | undefined; children: ReactNode }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { clear } = useSession();

  async function logout() {
    try {
      await call(() => api.POST('/auth/logout'));
    } finally {
      clear();
      navigate('/login', { replace: true });
    }
  }

  return (
    <div className="app-shell">
      <header className="hdr">
        <Link to="/" className="logo">
          <i aria-hidden="true" />
          {t('app.name')}
        </Link>
        <nav className="nav" aria-label={t('nav.label')}>
          {NAV.filter((item) => hasRole(me, item.roles)).map((item) => (
            <Link
              key={item.key}
              to={item.to}
              className={item.key === active ? 'on' : undefined}
              aria-current={item.key === active ? 'page' : undefined}
            >
              {t(`nav.${item.key}`)}
            </Link>
          ))}
        </nav>
        <span className="sp" />
        {me.system_roles.includes('superadmin') ? <span className="pill bad">{t('roles.superadmin')}</span> : null}
        <NotificationBell timeZone={me.timezone ?? undefined} />
        <Menu position="bottom-end">
          <Menu.Target>
            <button type="button" className="user-menu">
              <span className="av" style={{ background: userColor(me) }} aria-hidden="true">
                {initials(me.full_name)}
              </span>
              {shortName(me.full_name)} <span aria-hidden="true">▾</span>
              <span className="sr-only">, {t('nav.userMenu').toLowerCase()}</span>
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => navigate('/profile')}>{t('nav.profile')}</Menu.Item>
            <Menu.Item onClick={() => void logout()}>{t('nav.logout')}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </header>
      <OfflineBanner />
      <SessionExtend
        idleTimeoutSeconds={me.idle_timeout_seconds}
        sessionExpiresAt={me.session_expires_at}
        onLogout={() => void logout()}
      />
      <main>{children}</main>
    </div>
  );
}
