/**
 * FE-070 · каркас админки администратора (SPEC 7.5, DESIGN.md 5.3 «Админка»): меню разделов слева,
 * заголовок и содержимое справа — как в разделе «Система». Журнал аудита администратора — только
 * категории «Пользователи и роли» и «Справочники» (SEC-AUD-06).
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';

export const ADMIN_MENU = [
  { key: 'users', path: '/admin/users' },
  { key: 'dictionaries', path: '/admin/dictionaries' },
  { key: 'calendar', path: '/admin/calendar' },
  { key: 'proposed', path: '/admin/proposed-types' },
  { key: 'registry', path: '/admin/registry' },
  { key: 'audit', path: '/audit' },
] as const;

export type AdminSection = (typeof ADMIN_MENU)[number]['key'];

export function AdminLayout({
  active,
  title,
  subtitle,
  children,
}: {
  active: AdminSection;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="sys">
      <nav className="sys-menu" aria-label={t('admin.menuLabel')}>
        {ADMIN_MENU.map((item) => (
          <Link
            key={item.key}
            to={item.path}
            className={item.key === active ? 'on' : undefined}
            {...(item.key === active ? { 'aria-current': 'page' as const } : {})}
          >
            {t(`admin.menu.${item.key}`)}
          </Link>
        ))}
      </nav>
      <div className="sys-main">
        <h1 className="sys-title">{title}</h1>
        {subtitle ? <p className="sys-sub">{subtitle}</p> : null}
        {children}
      </div>
    </div>
  );
}
