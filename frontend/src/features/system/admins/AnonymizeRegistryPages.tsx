/**
 * FE-063 · «Анонимизация» (SEC-PD-03, Q-34) и «Реестр проектов» (11.2 №1, 3.2, FR-ADM-06).
 * Анонимизировать можно только заблокированного: ФИО → «Удалённый пользователь #N», логин и email —
 * случайные, сессии и 2FA удаляются; действие необратимо и требует step-up. Реестр — только чтение,
 * без денег: название, заказчик, модераторы, статус, даты, дни без модератора.
 */
import { Button } from '@mantine/core';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDate, formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout, adminsKey } from '../layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';
import { isLastSuperadmin } from './accounts';
import { useAdmins } from './AccountsPage';

type Account = components['schemas']['AdminAccount'];

/** Анонимизированные учётки уже обезличены — повторять нечего. */
export const isAnonymized = (a: Account) => a.full_name.startsWith('Удалённый пользователь #');

export function AnonymizePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const admins = useAdmins();
  const [target, setTarget] = useState<Account | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const all = admins.data?.items ?? [];
  const blocked = all.filter((a) => a.status === 'blocked' && !isAnonymized(a));
  const anonymize = useMutation({
    mutationFn: (a: Account) =>
      run(() => call(() => api.POST('/system/users/{id}/anonymize', { params: { path: { id: a.id } } }))),
    onSuccess: (_r, a) => {
      void qc.invalidateQueries({ queryKey: adminsKey });
      setDone(a.full_name);
    },
  });
  return (
    <SystemLayout active="anonymize" title={t('system.menu.anonymize')} subtitle={t('system.anonymize.subtitle')}>
      <ErrorText error={admins.error ?? (anonymize.error instanceof StepUpCancelled ? null : anonymize.error)} />
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {t('system.anonymize.done', { name: done })}
        </p>
      ) : null}
      <section className="sec">
        <p className="auth-hint">{t('system.anonymize.scope')}</p>
        {blocked.length === 0 ? <p className="sys-empty">{t('system.anonymize.empty')}</p> : null}
        {blocked.length > 0 ? (
          <table className="t sys-table">
            <thead>
              <tr>
                <th>{t('system.accounts.name')}</th>
                <th>{t('system.accounts.role')}</th>
                <th>{t('system.accounts.lastLogin')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {blocked.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{a.full_name}</b>
                    <div className="sub">{a.login}</div>
                  </td>
                  <td>{a.roles.map((r) => t(`system.accounts.roles.${r}`)).join(', ')}</td>
                  <td className="sub">{a.last_login_at ? formatDateTime(a.last_login_at) : '—'}</td>
                  <td className="r">
                    <Button
                      size="xs"
                      color="red"
                      variant="light"
                      disabled={isLastSuperadmin(a, all)}
                      aria-label={t('system.anonymize.actionFor', { name: a.full_name })}
                      onClick={() => {
                        setDone(null);
                        setTarget(a);
                      }}
                    >
                      {t('system.anonymize.action')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <ConfirmDialog
        opened={target !== null}
        title={t('system.anonymize.confirmTitle', { name: target?.full_name ?? '' })}
        message={t('system.anonymize.confirmText')}
        confirmLabel={t('system.anonymize.action')}
        danger
        busy={anonymize.isPending}
        onCancel={() => setTarget(null)}
        onConfirm={() => {
          const a = target;
          setTarget(null);
          if (a) anonymize.mutate(a);
        }}
      />
      {modal}
    </SystemLayout>
  );
}

export function RegistryPage() {
  const { t } = useTranslation();
  const registry = useInfiniteQuery({
    queryKey: ['system', 'registry'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/system/projects', { params: { query: { limit: 50, ...(pageParam ? { cursor: pageParam } : {}) } } }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = registry.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <SystemLayout active="projects" title={t('system.menu.projects')} subtitle={t('system.registry.subtitle')}>
      <ErrorText error={registry.error} />
      <section className="sec">
        <table className="t sys-table">
          <thead>
            <tr>
              <th>{t('system.registry.name')}</th>
              <th>{t('system.registry.moderators')}</th>
              <th>{t('system.registry.status')}</th>
              <th>{t('system.registry.created')}</th>
              <th>{t('system.registry.updated')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>
                  <b>{p.name}</b>
                  <div className="sub">{p.customer}</div>
                </td>
                <td>
                  {p.moderators.length > 0 ? (
                    p.moderators.map((m) => m.full_name).join(', ')
                  ) : (
                    <span className="pill bad">
                      {t('system.registry.noModerator', { count: p.days_without_moderator ?? 0 })}
                    </span>
                  )}
                </td>
                <td>{t(`status.project.${p.status}`)}</td>
                <td className="sub">{formatDate(p.created_at)}</td>
                <td className="sub">{formatDate(p.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {registry.hasNextPage ? (
          <Button
            mt="sm"
            variant="default"
            loading={registry.isFetchingNextPage}
            onClick={() => void registry.fetchNextPage()}
          >
            {t('system.registry.more')}
          </Button>
        ) : null}
      </section>
    </SystemLayout>
  );
}
