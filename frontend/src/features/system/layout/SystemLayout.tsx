/**
 * FE-060 · каркас раздела «Система» (SPEC 11.2 №1, DESIGN.md 5.3 «Админка», 10.2): меню раздела
 * слева, заголовок с подзаголовком и секции справа. Над содержимым — красные баннеры раздела:
 * «Заведите второго суперадминистратора…», пока активен только один (BR-ROLE-03), и
 * предупреждение об отключённом втором факторе для ролей с деньгами или админкой (FR-SA-04).
 */
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { mfaWarningRoles, soleSuperadmin } from './system';

export const SYSTEM_MENU = [
  { key: 'health', path: '/system' },
  { key: 'auth', path: '/system/auth' },
  { key: 'security', path: '/system/security' },
  { key: 'smtp', path: '/system/smtp' },
  { key: 'retention', path: '/system/retention' },
  { key: 'admins', path: '/system/admins' },
  { key: 'auditors', path: '/system/auditors' },
  { key: 'anonymize', path: '/system/anonymize' },
  { key: 'projects', path: '/system/projects' },
  { key: 'audit', path: '/audit' },
] as const;

export type SystemSection = (typeof SYSTEM_MENU)[number]['key'];

export const adminsKey = ['system', 'admins'] as const;
export const settingsKey = (section: string) => ['system', 'settings', section] as const;

function Banners() {
  const { t } = useTranslation();
  const admins = useQuery({
    queryKey: adminsKey,
    queryFn: () => call(() => api.GET('/system/admins')),
    retry: false,
  });
  const security = useQuery({
    queryKey: settingsKey('security'),
    queryFn: () => call(() => api.GET('/system/settings/{section}', { params: { path: { section: 'security' } } })),
    retry: false,
  });
  const sole = admins.data ? soleSuperadmin(admins.data.items) : false;
  const roles = security.data ? mfaWarningRoles(security.data.values) : [];
  if (!sole && roles.length === 0) return null;
  return (
    <div className="sys-banners">
      {sole ? (
        <div className="sys-banner" role="alert">
          {t('system.banner.soleSuperadmin')} <Link to="/system/admins">{t('system.banner.soleAction')}</Link>
        </div>
      ) : null}
      {roles.length > 0 ? (
        <div className="sys-banner" role="alert">
          {t('system.banner.mfaOff', { roles: roles.map((r) => t(`system.roles.${r}`)).join(', ') })}{' '}
          <Link to="/system/security">{t('system.banner.mfaAction')}</Link>
        </div>
      ) : null}
    </div>
  );
}

export function SystemLayout({
  active,
  title,
  subtitle,
  children,
}: {
  active: SystemSection;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="sys">
      <nav className="sys-menu" aria-label={t('system.menuLabel')}>
        {SYSTEM_MENU.map((item) => (
          <Link
            key={item.key}
            to={item.path}
            className={item.key === active ? 'on' : undefined}
            {...(item.key === active ? { 'aria-current': 'page' as const } : {})}
          >
            {t(`system.menu.${item.key}`)}
          </Link>
        ))}
      </nav>
      <div className="sys-main">
        <Banners />
        <h1 className="sys-title">{title}</h1>
        {subtitle ? <p className="sys-sub">{subtitle}</p> : null}
        {children}
      </div>
    </div>
  );
}

/**
 * Шаблон «Список + форма справа» (DESIGN.md 5.3): таблица слева, форма выбранной записи справа
 * 380 px; без выбранной записи — подсказка.
 */
export function ListWithForm({ list, form }: { list: ReactNode; form: ReactNode | null }) {
  const { t } = useTranslation();
  return (
    <div className="sys-list-form">
      <div className="sys-list">{list}</div>
      <section className="sec sys-form">{form ?? <p className="sys-empty">{t('system.listForm.empty')}</p>}</section>
    </div>
  );
}

/** Пункт меню, экран которого делает следующая задача плана. */
export function SystemStub({ active, task }: { active: SystemSection; task: string }) {
  const { t } = useTranslation();
  return (
    <SystemLayout active={active} title={t(`system.menu.${active}`)}>
      <p className="sys-sub">{t('placeholder.hint', { task })}</p>
    </SystemLayout>
  );
}
