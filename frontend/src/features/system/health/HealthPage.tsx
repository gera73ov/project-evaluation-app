/**
 * FE-060 · «Состояние системы» (FR-SA-07, DESIGN.md 10.2): версия приложения и схемы БД, карточки
 * компонентов с индикатором — кружок и слово «работает» / «недоступен» (цвет не единственный
 * носитель смысла, FR-UI-04), пояснение сервера и время проверки. «Обновить» перечитывает.
 */
import { Button } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import type { Me } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout } from '../layout/SystemLayout';

type Component = components['schemas']['Health']['components'][number];

/** Порядок карточек: хранилища, почта и каталог, затем фоновые задачи и журнал. */
const ORDER: readonly Component['name'][] = [
  'db',
  'redis',
  'smtp',
  'ldap',
  'siem',
  'queue',
  'backup',
  'audit_chain',
  'audit_purge',
];

export function sortComponents(items: readonly Component[]): Component[] {
  return [...items].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name));
}

export function HealthPage({ me }: { me: Me }) {
  const { t } = useTranslation();
  const timeZone = me.timezone ?? undefined;
  const health = useQuery({
    queryKey: ['system', 'health'],
    queryFn: () => call(() => api.GET('/system/health')),
    refetchInterval: 60_000,
  });
  const items = sortComponents(health.data?.components ?? []);
  const down = items.filter((c) => !c.ok).length;
  return (
    <SystemLayout active="health" title={t('system.menu.health')} subtitle={t('system.health.subtitle')}>
      <ErrorText error={health.error} />
      {health.data ? (
        <>
          <div className="sys-health-head">
            <span>
              {t('system.health.app')} <b className="mono">{health.data.app_version}</b>
            </span>
            <span>
              {t('system.health.schema')} <b className="mono">{health.data.schema_version}</b>
            </span>
            <span className={down ? 'bad' : 'ok'}>
              {down ? t('system.health.down', { count: down }) : t('system.health.allOk')}
            </span>
            <span className="sp" />
            <Button variant="default" size="xs" loading={health.isFetching} onClick={() => void health.refetch()}>
              {t('system.health.refresh')}
            </Button>
          </div>
          <ul className="sys-health" aria-label={t('system.menu.health')}>
            {items.map((c) => (
              <li key={c.name} className={c.ok ? 'card' : 'card bad'}>
                <div className="sys-health-name">{t(`system.health.component.${c.name}`)}</div>
                <div className={c.ok ? 'sys-state ok' : 'sys-state bad'}>
                  <i aria-hidden="true" />
                  {c.ok ? t('system.health.ok') : t('system.health.fail')}
                </div>
                {c.detail ? <div className="sys-health-detail">{c.detail}</div> : null}
                <div className="sys-health-at">
                  {t('system.health.checked', { at: formatDateTime(c.checked_at, timeZone) })}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </SystemLayout>
  );
}
