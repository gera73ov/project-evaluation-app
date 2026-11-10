/**
 * FE-063 · «Анонимизация» (SEC-PD-03, Q-34, CR-010) и «Реестр проектов» (11.2 №1, 3.2, FR-ADM-06).
 * Список — все заблокированные учётки, и раздела «Система», и обычные пользователи
 * (`GET /system/users`), с поиском и «Ещё». Анонимизировать можно только заблокированного:
 * ФИО → «Удалённый пользователь #N», логин и email — случайные, сессии и 2FA удаляются; действие
 * необратимо и требует step-up. Вкладка «Анонимизированные» — для сверки, без действий. Реестр —
 * только чтение, без денег: название, заказчик, модераторы, статус, даты, дни без модератора.
 */
import { Button, SegmentedControl, TextInput } from '@mantine/core';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDate, formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout, adminsKey } from '../layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';
import { ModeratorsCell } from '../../admin/registry/ModeratorsCell';

type Item = components['schemas']['SystemUserItem'];
type Status = Item['status'];

const usersKey = ['system', 'users'] as const;

export function AnonymizePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const [status, setStatus] = useState<Status>('blocked');
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [target, setTarget] = useState<Item | null>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);
  const users = useInfiniteQuery({
    queryKey: [...usersKey, { status, q }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/system/users', {
          params: { query: { status, limit: 50, ...(q ? { q } : {}), ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = users.data?.pages.flatMap((p) => p.items) ?? [];
  const anonymize = useMutation({
    mutationFn: (a: Item) =>
      run(() => call(() => api.POST('/system/users/{id}/anonymize', { params: { path: { id: a.id } } }))),
    onSuccess: (_r, a) => {
      void qc.invalidateQueries({ queryKey: usersKey });
      void qc.invalidateQueries({ queryKey: adminsKey });
      setDone(a.full_name);
    },
  });
  const role = (r: string) => (r === 'superadmin' ? t('system.accounts.roles.superadmin') : t(`system.roles.${r}`));
  return (
    <SystemLayout active="anonymize" title={t('system.menu.anonymize')} subtitle={t('system.anonymize.subtitle')}>
      <ErrorText error={users.error ?? (anonymize.error instanceof StepUpCancelled ? null : anonymize.error)} />
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {t('system.anonymize.done', { name: done })}
        </p>
      ) : null}
      <section className="sec">
        <p className="auth-hint">{t('system.anonymize.scope')}</p>
        <div className="sys-list-head adm-filters">
          <SegmentedControl
            aria-label={t('system.anonymize.status')}
            value={status}
            data={(['blocked', 'anonymized'] as const).map((s) => ({ value: s, label: t(`system.anonymize.${s}`) }))}
            onChange={(v) => setStatus(v === 'anonymized' ? 'anonymized' : 'blocked')}
          />
          <TextInput
            className="adm-search"
            aria-label={t('system.anonymize.search')}
            placeholder={t('system.anonymize.search')}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
          />
        </div>
        {users.data && items.length === 0 ? (
          <p className="sys-empty">
            {t(status === 'blocked' ? 'system.anonymize.empty' : 'system.anonymize.emptyDone')}
          </p>
        ) : null}
        {items.length > 0 ? (
          <table className="t sys-table">
            <thead>
              <tr>
                <th>{t('system.accounts.name')}</th>
                <th>{t('system.accounts.role')}</th>
                <th>{t('system.anonymize.blockedAt')}</th>
                <th>{t('system.accounts.lastLogin')}</th>
                {status === 'blocked' ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{a.full_name}</b>
                    <div className="sub">{a.login}</div>
                  </td>
                  <td>{a.roles.length ? a.roles.map(role).join(', ') : t('system.roles.user')}</td>
                  <td className="sub">{a.blocked_at ? formatDateTime(a.blocked_at) : '—'}</td>
                  <td className="sub">{a.last_login_at ? formatDateTime(a.last_login_at) : '—'}</td>
                  {status === 'blocked' ? (
                    <td className="r">
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        c="var(--bad-ink)" // DESIGN 2.3: текст тоном -ink, у Mantine red.6 на светлом фоне ниже 4.5:1
                        aria-label={t('system.anonymize.actionFor', { name: a.full_name })}
                        onClick={() => {
                          setDone(null);
                          setTarget(a);
                        }}
                      >
                        {t('system.anonymize.action')}
                      </Button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {users.hasNextPage ? (
          <Button
            mt="sm"
            variant="default"
            loading={users.isFetchingNextPage}
            onClick={() => void users.fetchNextPage()}
          >
            {t('system.anonymize.more')}
          </Button>
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
                  <ModeratorsCell
                    moderators={p.moderators}
                    since={p.no_moderator_since}
                    days={p.days_without_moderator}
                  />
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
