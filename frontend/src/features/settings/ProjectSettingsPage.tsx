/**
 * FE-012 · экран «Настройки проекта» (SPEC 11.6, DESIGN.md 10.5): в шапке статус и «⋯» (FE-015), вкладки, слева «Основное»
 * и «Команда», справа «Деньги» (только роли с деньгами — FE-014). Эксперт видит всё только для
 * чтения; без связи поля тоже только для чтения (FR-TREE-33).
 */
import { useTranslation } from 'react-i18next';

import { Link } from '../../app/router';
import { useReadOnlyOffline } from '../../shared/ws/WsProvider';
import { ErrorText } from '../../shared/ui/ErrorText';
import { GeneralSection } from './general/GeneralSection';
import { StatusControl } from './status/StatusControl';
import { MoneySection } from './money/MoneySection';
import { TeamSection } from './team/TeamSection';
import { useProject, type Project } from './useProject';

export const SETTINGS_TABS = [
  { key: 'general', path: '/settings' },
  { key: 'documents', path: '/settings/documents' },
  { key: 'outcome', path: '/settings/outcome' },
  { key: 'snapshots', path: '/settings/snapshots' },
  { key: 'trash', path: '/trash' },
  { key: 'journal', path: '/log' },
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number]['key'];

export function canEditSettings(project: Project): boolean {
  return project.my_permissions.includes('project.settings.write');
}

export function SettingsTabs({ projectId, active }: { projectId: string; active: SettingsTab }) {
  const { t } = useTranslation();
  return (
    <nav className="tabs set-tabs" aria-label={t('settings.title')}>
      {SETTINGS_TABS.map((tab) => (
        <Link
          key={tab.key}
          to={`/projects/${projectId}${tab.path}`}
          className={tab.key === active ? 'on' : undefined}
          {...(tab.key === active ? { 'aria-current': 'page' as const } : {})}
        >
          {t(`settings.tabs.${tab.key}`)}
        </Link>
      ))}
    </nav>
  );
}

export function ProjectSettingsPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const project = useProject(projectId);
  const offline = useReadOnlyOffline();

  if (project.error) {
    return (
      <div className="main">
        <ErrorText error={project.error} />
      </div>
    );
  }
  if (!project.data) return null;
  const data = project.data;
  const readOnly = !canEditSettings(data) || offline;
  const money = data.my_permissions.includes('money.read');

  return (
    <div className="settings">
      <div className="crumbs">
        <Link to={`/projects/${data.id}`}>{data.name}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('settings.title')}</h1>
        <span className="sp" />
        <StatusControl project={data} readOnly={offline} />
        {data.my_permissions.includes('team.write') ? <span className="pill acc">{t('settings.youModerator')}</span> : null}
      </div>
      <SettingsTabs projectId={data.id} active="general" />
      {!canEditSettings(data) ? <p className="set-readonly">{t('settings.readOnly')}</p> : null}
      <div className={money ? 'set-grid' : 'set-grid single'}>
        <div className="set-col">
          <GeneralSection project={data} readOnly={readOnly} />
          <TeamSection project={data} readOnly={offline} />
        </div>
        {/* у ролей без денег блока нет в разметке (11.6, SEC-AUTHZ-04) */}
        {money ? (
          <div className="set-col">
            <MoneySection project={data} readOnly={offline} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
