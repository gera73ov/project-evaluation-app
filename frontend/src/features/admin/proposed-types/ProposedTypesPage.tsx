/**
 * FE-072 · «Предложенные типы» (SPEC 7.5, FR-TREE-03): локальные типы из проектов — проект, автор,
 * сколько узлов. Действия: «Добавить» в словарь, «Объединить с …» существующим типом (узлы
 * перепривязываются), «Отклонить» (тип остаётся локальным в проекте).
 */
import { Button, Modal, Select, Stack } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { nodeTypeSymbol } from '../../../shared/ui/icons/nodeTypes';
import { dictKey } from '../dictionaries/dictionaries';
import { AdminLayout } from '../layout/AdminLayout';

type Proposed = components['schemas']['ProposedType'];
type Action = { kind: 'merge' | 'reject'; item: Proposed };

const proposedKey = ['admin', 'proposed-types'] as const;

export function ProposedTypesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [action, setAction] = useState<Action | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const proposed = useQuery({ queryKey: proposedKey, queryFn: () => call(() => api.GET('/admin/proposed-types')) });
  const types = useQuery({
    queryKey: dictKey('node-types'),
    queryFn: () => call(() => api.GET('/admin/node-types', { params: { query: { include_inactive: true } } })),
  });
  const active = (types.data?.items ?? []).filter((x) => x.is_active && x.project_id === null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: proposedKey });
    void qc.invalidateQueries({ queryKey: ['admin', 'dict'] });
    void qc.invalidateQueries({ queryKey: ['dict'] });
  };
  const close = () => {
    setAction(null);
    setTarget(null);
  };

  const accept = useMutation({
    mutationFn: (p: Proposed) =>
      call(() => api.POST('/admin/proposed-types/{id}/accept', { params: { path: { id: p.id } } })),
    onSuccess: (_r, p) => {
      refresh();
      setDone(t('admin.proposed.accepted', { name: p.name }));
    },
  });
  const merge = useMutation({
    mutationFn: ({ p, to }: { p: Proposed; to: string }) =>
      call(() =>
        api.POST('/admin/proposed-types/{id}/merge', {
          params: { path: { id: p.id } },
          body: { target_type_id: to },
        }),
      ),
    onSuccess: (r, { p }) => {
      close();
      refresh();
      setDone(t('admin.proposed.merged', { name: p.name, to: r.name, count: p.nodes_count }));
    },
  });
  const reject = useMutation({
    mutationFn: (p: Proposed) =>
      call(() => api.POST('/admin/proposed-types/{id}/reject', { params: { path: { id: p.id } } })),
    onSuccess: (_r, p) => {
      close();
      refresh();
      setDone(t('admin.proposed.rejected', { name: p.name }));
    },
  });
  const items = proposed.data?.items ?? [];

  return (
    <AdminLayout active="proposed" title={t('admin.menu.proposed')} subtitle={t('admin.proposed.subtitle')}>
      <ErrorText error={proposed.error ?? accept.error} />
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {done}
        </p>
      ) : null}
      <section className="sec">
        {proposed.data && items.length === 0 ? <p className="sys-empty">{t('admin.proposed.empty')}</p> : null}
        {items.length > 0 ? (
          <table className="t sys-table">
            <thead>
              <tr>
                <th>{t('admin.proposed.type')}</th>
                <th>{t('admin.proposed.project')}</th>
                <th>{t('admin.proposed.author')}</th>
                <th className="num">{t('admin.proposed.nodes')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <span className="adm-icon" aria-hidden>
                      {nodeTypeSymbol(p.icon)}
                    </span>
                    <b>{p.name}</b>
                  </td>
                  <td>{p.project_name}</td>
                  <td>
                    {p.author.full_name}
                    <div className="sub">{formatDateTime(p.created_at)}</div>
                  </td>
                  <td className="num">{p.nodes_count}</td>
                  <td className="adm-row-actions">
                    <Button
                      size="xs"
                      loading={accept.isPending && accept.variables.id === p.id}
                      aria-label={t('admin.proposed.acceptOf', { name: p.name })}
                      onClick={() => accept.mutate(p)}
                    >
                      {t('admin.proposed.accept')}
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      aria-label={t('admin.proposed.mergeOf', { name: p.name })}
                      onClick={() => setAction({ kind: 'merge', item: p })}
                    >
                      {t('admin.proposed.merge')}
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      color="red"
                      aria-label={t('admin.proposed.rejectOf', { name: p.name })}
                      onClick={() => setAction({ kind: 'reject', item: p })}
                    >
                      {t('admin.proposed.reject')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      <Modal
        opened={action?.kind === 'merge'}
        onClose={close}
        title={t('admin.proposed.mergeTitle', { name: action?.item.name ?? '' })}
        centered
      >
        <Stack gap="sm">
          <p>{t('admin.proposed.mergeText', { count: action?.item.nodes_count ?? 0 })}</p>
          <Select
            label={t('admin.proposed.mergeWith')}
            searchable
            value={target}
            data={active.map((x) => ({ value: x.id, label: x.name }))}
            onChange={setTarget}
          />
          <ErrorText error={merge.error} />
          <div className="sys-actions">
            <Button
              disabled={!target}
              loading={merge.isPending}
              onClick={() => action && target && merge.mutate({ p: action.item, to: target })}
            >
              {t('admin.proposed.mergeConfirm')}
            </Button>
            <Button variant="default" onClick={close}>
              {t('common.cancel')}
            </Button>
          </div>
        </Stack>
      </Modal>
      <ConfirmDialog
        opened={action?.kind === 'reject'}
        title={t('admin.proposed.rejectTitle', { name: action?.item.name ?? '' })}
        message={t('admin.proposed.rejectText')}
        confirmLabel={t('admin.proposed.reject')}
        danger
        busy={reject.isPending}
        onConfirm={() => action && reject.mutate(action.item)}
        onCancel={close}
      />
    </AdminLayout>
  );
}
