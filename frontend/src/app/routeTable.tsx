/**
 * FE-003 · карта экранов SPEC 8.1. Экраны, которые делают следующие задачи плана, пока
 * заглушки с ID задачи. `roles` — системные роли, которым маршрут доступен (пункты меню без
 * права не рисуются, DESIGN.md 5.1); проектные права проверяет сервер (404/403).
 */
import type { ReactNode } from 'react';

import { ActivatePage } from '../features/auth/ActivatePage';
import { ForgotPasswordPage, ResetPasswordPage } from '../features/auth/PasswordPages';
import { LoginPage } from '../features/auth/LoginPage';
import { SetupInProgressPage } from '../features/auth/SetupInProgressPage';
import { ProfilePage } from '../features/profile/ProfilePage';
import { TotpEnrollPage } from '../features/profile/TotpEnrollPage';
import type { Params } from './router';
import type { SystemRole } from './session';
import { Placeholder } from './Placeholder';

export type Access = 'public' | 'enroll' | 'private';

export interface RouteDef {
  path: string;
  access: Access;
  roles?: readonly SystemRole[];
  /** Ключ пункта меню, который подсвечивается на маршруте. */
  nav?: NavKey;
  render: (params: Params) => ReactNode;
}

export type NavKey = 'home' | 'portfolio' | 'admin' | 'audit' | 'system';

export interface NavItem {
  key: NavKey;
  to: string;
  roles?: readonly SystemRole[];
}

/** Пункты шапки вне проекта, в порядке DESIGN.md 5.1. */
export const NAV: readonly NavItem[] = [
  { key: 'home', to: '/' },
  { key: 'portfolio', to: '/portfolio', roles: ['presale_head'] },
  { key: 'admin', to: '/admin', roles: ['admin'] },
  { key: 'audit', to: '/audit', roles: ['security_auditor'] },
  { key: 'system', to: '/system', roles: ['superadmin'] },
];

function stub(title: string, task: string) {
  return function StubPage() {
    return <Placeholder title={title} task={task} />;
  };
}

export const ROUTES: readonly RouteDef[] = [
  { path: '/login', access: 'public', render: () => <LoginPage /> },
  { path: '/activate', access: 'public', render: () => <ActivatePage /> },
  { path: '/password/forgot', access: 'public', render: () => <ForgotPasswordPage /> },
  { path: '/password/reset', access: 'public', render: () => <ResetPasswordPage /> },
  { path: '/setup-in-progress', access: 'public', render: () => <SetupInProgressPage /> },
  { path: '/enroll-totp', access: 'enroll', render: () => <TotpEnrollPage /> },

  { path: '/', access: 'private', nav: 'home', render: stub('Мои оценки', 'FE-010') },
  { path: '/projects/new', access: 'private', nav: 'home', roles: ['moderator'], render: stub('Создание проекта', 'FE-011') },
  { path: '/projects/:id', access: 'private', render: stub('Рабочий экран проекта', 'FE-022') },
  { path: '/projects/:id/settings', access: 'private', render: stub('Настройки проекта', 'FE-012') },
  { path: '/projects/:id/settings/documents', access: 'private', render: stub('Документы заказчика', 'FE-017') },
  { path: '/projects/:id/trash', access: 'private', render: stub('Корзина', 'FE-018') },
  { path: '/projects/:id/log', access: 'private', render: stub('Журнал проекта', 'FE-015') },
  { path: '/projects/:id/stats', access: 'private', render: stub('Статистика', 'FE-040') },
  { path: '/projects/:id/stats/compare', access: 'private', render: stub('Сравнение со снимком', 'FE-044') },
  { path: '/projects/:id/stats/questions', access: 'private', render: stub('Вопросы заказчику', 'FE-043') },
  { path: '/profile', access: 'private', render: () => <ProfilePage /> },
  { path: '/admin', access: 'private', nav: 'admin', roles: ['admin'], render: stub('Админка', 'FE-070') },
  { path: '/admin/registry', access: 'private', nav: 'admin', roles: ['admin'], render: stub('Реестр проектов', 'FE-073') },
  { path: '/admin/registry/:id/support', access: 'private', nav: 'admin', roles: ['admin'], render: stub('Проект в режиме поддержки', 'FE-073') },
  { path: '/portfolio', access: 'private', nav: 'portfolio', roles: ['presale_head'], render: stub('Портфель', 'FE-050') },
  { path: '/system', access: 'private', nav: 'system', roles: ['superadmin'], render: stub('Система', 'FE-060') },
  { path: '/audit', access: 'private', nav: 'audit', roles: ['security_auditor', 'superadmin'], render: stub('Журнал аудита', 'FE-065') },
];

export function findRoute(pathname: string, match: (pattern: string, path: string) => Params | null) {
  for (const route of ROUTES) {
    const params = match(route.path, pathname);
    if (params) return { route, params };
  }
  return null;
}
