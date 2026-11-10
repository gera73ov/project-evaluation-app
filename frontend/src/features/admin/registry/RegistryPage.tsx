/**
 * FE-073 · «Реестр проектов» администратора (SPEC 7.5, BR-PRJ-07, FR-ADM-06): проекты без денег,
 * поиск, статус и отдельный фильтр «Проекты без модератора» с числом дней. Действия строки:
 * «Передать / добавить модератора» и «Открыть в режиме поддержки» с причиной 10–500 символов.
 */
import { Button, Checkbox, Modal, Select, Stack, Textarea, TextInput } from '@mantine/core';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDate } from '../../../shared/format/date';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { AdminLayout } from '../layout/AdminLayout';
import { canModerate, rememberSupportReason, REASON_MAX, REASON_MIN, reasonValid, registryKey } from './registry';

type Project = components['schemas']['RegistryProject'];
type UserRef = components['schemas']['UserRef'];

const STATUSES = ['preparation', 'estimation', 'consolidation', 'completed', 'archived'] as const;

export function RegistryPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [orphans, setOrphans] = useState(false);
  const [moderating, setModerating] = useState<Project | null>(null);
  const [support, setSupport] = useState<Project | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  const registry = useInfiniteQuery({
    queryKey: [...registryKey, { q, status, orphans }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/admin/projects', {
          params: {
            query: {
              limit: 50,
              ...(q ? { q } : {}),
              ...(status ? { status: status as Project['status'] } : {}),
              ...(orphans ? { without_moderator: true } : {}),
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = registry.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <AdminLayout active="registry" title={t('admin.menu.registry')} subtitle={t('admin.registry.subtitle')}>
      <ErrorText error={registry.error} />
      <section className="sec">
        <div className="sys-list-head adm-filters">
          <TextInput
            className="adm-search"
            aria-label={t('admin.registry.search')}
            placeholder={t('admin.registry.search')}
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
          />
          <Select
            aria-label={t('admin.registry.status')}
            placeholder={t('admin.registry.anyStatus')}
            clearable
            value={status}
            data={STATUSES.map((s) => ({ value: s, label: t(`status.project.${s}`) }))}
            onChange={setStatus}
          />
          <Checkbox
            label={t('admin.registry.orphans')}
            checked={orphans}
            onChange={(e) => setOrphans(e.currentTarget.checked)}
          />
        </div>
        {registry.data && items.length === 0 ? <p className="sys-empty">{t('admin.registry.empty')}</p> : null}
        {items.length > 0 ? (
          <table className="t sys-table">
            <thead>
              <tr>
                <th>{t('admin.registry.name')}</th>
                <th>{t('admin.registry.moderators')}</th>
                <th>{t('admin.registry.status')}</th>
                <th>{t('admin.registry.updated')}</th>
                <th />
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
                  <td className="sub">{formatDate(p.updated_at)}</td>
                  <td className="adm-row-actions">
                    <Button
                      size="xs"
                      variant="default"
                      aria-label={t('admin.registry.moderatorsOf', { name: p.name })}
                      onClick={() => setModerating(p)}
                    >
                      {t('admin.registry.transfer')}
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      aria-label={t('admin.registry.supportOf', { name: p.name })}
                      onClick={() => setSupport(p)}
                    >
                      {t('admin.registry.support')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {registry.hasNextPage ? (
          <Button
            mt="sm"
            variant="default"
            loading={registry.isFetchingNextPage}
            onClick={() => void registry.fetchNextPage()}
          >
            {t('admin.registry.more')}
          </Button>
        ) : null}
      </section>
      <Modal
        opened={moderating !== null}
        onClose={() => setModerating(null)}
        title={t('admin.registry.transferTitle', { name: moderating?.name ?? '' })}
        size="lg"
      >
        {moderating ? <ModeratorsForm project={moderating} onClose={() => setModerating(null)} /> : null}
      </Modal>
      <Modal
        opened={support !== null}
        onClose={() => setSupport(null)}
        title={t('admin.registry.supportTitle', { name: support?.name ?? '' })}
      >
        {support ? <SupportForm project={support} onClose={() => setSupport(null)} /> : null}
      </Modal>
    </AdminLayout>
  );
}

/** Передать проект (снять прежних и назначить новых) или добавить модератора. */
function ModeratorsForm({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [keep, setKeep] = useState<string[]>(project.moderators.map((m) => m.id));
  const [added, setAdded] = useState<UserRef[]>([]);
  const users = useQuery({
    queryKey: ['admin', 'users', 'moderators'],
    queryFn: () => call(() => api.GET('/admin/users', { params: { query: { limit: 200, status: 'active' } } })),
  });
  const candidates = (users.data?.items ?? []).filter(
    (u) => canModerate(u) && !keep.includes(u.id) && !added.some((a) => a.id === u.id),
  );
  const removed = project.moderators.filter((m) => !keep.includes(m.id)).map((m) => m.id);
  const total = keep.length + added.length;
  const save = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/projects/{id}/moderators', {
          params: { path: { id: project.id } },
          body: { add_user_ids: added.map((a) => a.id), remove_user_ids: removed },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: registryKey });
      onClose();
    },
  });
  return (
    <Stack gap="sm">
      <p>{t('admin.registry.transferIntro')}</p>
      {project.moderators.length > 0 ? (
        <Checkbox.Group label={t('admin.registry.current')} value={keep} onChange={setKeep}>
          <Stack gap={6} mt={4}>
            {project.moderators.map((m) => (
              <Checkbox key={m.id} value={m.id} label={m.full_name} />
            ))}
          </Stack>
        </Checkbox.Group>
      ) : (
        <p className="set-danger">{t('admin.registry.noneNow')}</p>
      )}
      {added.length > 0 ? (
        <ul className="adm-added" aria-label={t('admin.registry.added')}>
          {added.map((a) => (
            <li key={a.id}>
              {a.full_name}
              <button
                type="button"
                className="btn-link"
                aria-label={t('admin.registry.unadd', { name: a.full_name })}
                onClick={() => setAdded((x) => x.filter((y) => y.id !== a.id))}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <Select
        label={t('admin.registry.add')}
        description={t('admin.registry.addHint')}
        placeholder={t('admin.registry.addPlaceholder')}
        searchable
        value={null}
        data={candidates.map((u) => ({ value: u.id, label: `${u.full_name} · ${u.login}` }))}
        onChange={(id) => {
          const u = candidates.find((c) => c.id === id);
          if (u) setAdded((x) => [...x, { id: u.id, full_name: u.full_name, initials: '', is_active: true }]);
        }}
      />
      {total === 0 ? <p className="set-danger">{t('admin.registry.lastModerator')}</p> : null}
      <ErrorText error={users.error ?? save.error} />
      <div className="sys-actions">
        <Button
          disabled={total === 0 || (added.length === 0 && removed.length === 0)}
          loading={save.isPending}
          onClick={() => save.mutate()}
        >
          {t('common.save')}
        </Button>
        <Button variant="default" onClick={onClose}>
          {t('common.cancel')}
        </Button>
      </div>
    </Stack>
  );
}

/** «Открыть в режиме поддержки»: причина 10–500 символов уходит в аудит и модераторам проекта. */
function SupportForm({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [reason, setReason] = useState('');
  const open = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/projects/{id}/support-session', {
          params: { path: { id: project.id } },
          body: { reason: reason.trim() },
        }),
      ),
    onSuccess: () => {
      rememberSupportReason(project.id, reason.trim());
      onClose();
      navigate(`/projects/${project.id}`);
    },
  });
  const length = reason.trim().length;
  return (
    <Stack gap="sm">
      <p>{t('admin.registry.supportIntro')}</p>
      <Textarea
        label={t('admin.registry.reason')}
        description={t('admin.registry.reasonHint', { length, min: REASON_MIN, max: REASON_MAX })}
        required
        autosize
        minRows={3}
        maxLength={REASON_MAX}
        value={reason}
        onChange={(e) => setReason(e.currentTarget.value)}
      />
      <ErrorText error={open.error} />
      <div className="sys-actions">
        <Button disabled={!reasonValid(reason)} loading={open.isPending} onClick={() => open.mutate()}>
          {t('admin.registry.supportOpen')}
        </Button>
        <Button variant="default" onClick={onClose}>
          {t('common.cancel')}
        </Button>
      </div>
    </Stack>
  );
}
