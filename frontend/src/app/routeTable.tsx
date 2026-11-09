/**
 * FE-003 · карта экранов SPEC 8.1. Экраны, которые делают следующие задачи плана, пока
 * заглушки с ID задачи. `roles` — системные роли, которым маршрут доступен (пункты меню без
 * права не рисуются, DESIGN.md 5.1); проектные права проверяет сервер (404/403).
 */
import type { ReactNode } from 'react';

import { ActivatePage } from '../features/auth/ActivatePage';
import { ForgotPasswordPage, ResetPasswordPage } from '../features/auth/PasswordPages';
import { LoginPage } from '../features/auth/LoginPage';
import { PasswordExpiredPage } from '../features/auth/PasswordExpiredPage';
import { SetupInProgressPage } from '../features/auth/SetupInProgressPage';
import { HomeRoute } from '../features/home/HomeRoute';
import { ProfilePage } from '../features/profile/ProfilePage';
import { ProjectCreatePage } from '../features/project-create/ProjectCreatePage';
import { DocumentsPage } from '../features/documents/DocumentsPage';
import { ReadinessPage } from '../features/stats/grid/ReadinessPage';
import { CandidatesPage, SharesPage, TagsPage, VolumesPage } from '../features/stats/details/DetailsPages';
import { SnapshotsPage } from '../features/stats/details/SnapshotsPage';
import { ComparePage } from '../features/compare/ComparePage';
import { DiscussionsPage } from '../features/stats/questions/DiscussionsPage';
import { QuestionsPage } from '../features/stats/questions/QuestionsPage';
import { TotalsPage } from '../features/stats/totals/TotalsPage';
import { PortfolioRoute } from '../features/portfolio/PortfolioRoute';
import { HealthPage } from '../features/system/health/HealthPage';
import { SystemStub } from '../features/system/layout/SystemLayout';
import { SystemRoute } from '../features/system/SystemRoute';
import { OutcomePage } from '../features/settings/outcome/OutcomePage';
import { JournalRoute, SettingsRoute } from '../features/settings/SettingsRoute';
import { TrashPage } from '../features/trash/TrashPage';
import { TotpEnrollPage } from '../features/profile/TotpEnrollPage';
import { WorkRoute } from '../features/work/WorkRoute';
import type { Params } from './router';
import type { SystemRole } from './session';
import { Placeholder } from './Placeholder';

export type Access = 'public' | 'enroll' | 'password' | 'private';

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

/** Пункты меню «Системы», экраны которых делают следующие задачи плана. */
const SYSTEM_STUBS = [
  ['auth', 'FE-061'],
  ['security', 'FE-062'],
  ['smtp', 'FE-062'],
  ['retention', 'FE-062'],
  ['admins', 'FE-063'],
  ['auditors', 'FE-063'],
  ['anonymize', 'FE-063'],
  ['projects', 'FE-063'],
] as const;

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
  { path: '/change-password', access: 'password', render: () => <PasswordExpiredPage /> },

  { path: '/', access: 'private', nav: 'home', render: () => <HomeRoute /> },
  { path: '/projects/new', access: 'private', nav: 'home', roles: ['moderator'], render: () => <ProjectCreatePage /> },
  { path: '/projects/:id', access: 'private', render: (params) => <WorkRoute id={params.id ?? ''} /> },
  { path: '/projects/:id/settings', access: 'private', render: (params) => <SettingsRoute id={params.id ?? ''} /> },
  {
    path: '/projects/:id/settings/outcome',
    access: 'private',
    render: (params) => <OutcomePage key={params.id} projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/settings/documents',
    access: 'private',
    render: (params) => <DocumentsPage key={params.id} projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/trash',
    access: 'private',
    render: (params) => <TrashPage key={params.id} projectId={params.id ?? ''} />,
  },
  { path: '/projects/:id/log', access: 'private', render: (params) => <JournalRoute id={params.id ?? ''} /> },
  {
    path: '/projects/:id/stats',
    access: 'private',
    render: (params) => <ReadinessPage key={params.id} projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/stats/totals',
    access: 'private',
    render: (params) => <TotalsPage projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/stats/shares',
    access: 'private',
    render: (params) => <SharesPage projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/stats/volumes',
    access: 'private',
    render: (params) => <VolumesPage projectId={params.id ?? ''} />,
  },
  {
    path: '/projects/:id/stats/candidates',
    access: 'private',
    render: (params) => <CandidatesPage projectId={params.id ?? ''} />,
  },
  { path: '/projects/:id/stats/tags', access: 'private', render: (params) => <TagsPage projectId={params.id ?? ''} /> },
  {
    path: '/projects/:id/stats/discussions',
    access: 'private',
    render: (p) => <DiscussionsPage projectId={p.id ?? ''} />,
  },
  {
    path: '/projects/:id/stats/snapshots',
    access: 'private',
    render: (params) => <SnapshotsPage projectId={params.id ?? ''} />,
  },
  { path: '/projects/:id/stats/compare', access: 'private', render: (p) => <ComparePage projectId={p.id ?? ''} /> },
  { path: '/projects/:id/stats/questions', access: 'private', render: (p) => <QuestionsPage projectId={p.id ?? ''} /> },
  { path: '/profile', access: 'private', render: () => <ProfilePage /> },
  { path: '/admin', access: 'private', nav: 'admin', roles: ['admin'], render: stub('Админка', 'FE-070') },
  {
    path: '/admin/registry',
    access: 'private',
    nav: 'admin',
    roles: ['admin'],
    render: stub('Реестр проектов', 'FE-073'),
  },
  {
    path: '/admin/registry/:id/support',
    access: 'private',
    nav: 'admin',
    roles: ['admin'],
    render: stub('Проект в режиме поддержки', 'FE-073'),
  },
  {
    path: '/portfolio',
    access: 'private',
    nav: 'portfolio',
    roles: ['presale_head'],
    render: () => <PortfolioRoute />,
  },
  {
    path: '/system',
    access: 'private',
    nav: 'system',
    roles: ['superadmin'],
    render: () => <SystemRoute render={(me) => <HealthPage me={me} />} />,
  },
  ...SYSTEM_STUBS.map(
    ([section, task]): RouteDef => ({
      path: `/system/${section}`,
      access: 'private',
      nav: 'system',
      roles: ['superadmin'],
      render: () => <SystemStub active={section} task={task} />,
    }),
  ),
  {
    path: '/audit',
    access: 'private',
    nav: 'audit',
    roles: ['security_auditor', 'superadmin'],
    render: stub('Журнал аудита', 'FE-065'),
  },
];

export function findRoute(pathname: string, match: (pattern: string, path: string) => Params | null) {
  for (const route of ROUTES) {
    const params = match(route.path, pathname);
    if (params) return { route, params };
  }
  return null;
}
