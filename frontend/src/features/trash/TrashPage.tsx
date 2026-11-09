/**
 * FE-018 · вкладка «Корзина» настроек проекта (SPEC 11.6 №1, FR-TREE-24, FR-DOC-01, GAP-06, G-15;
 * DESIGN.md 10.5, шаблон «Список»).
 *
 * Строка — пакет удалённых узлов или документ заказчика: путь, «удалил · когда», плашка `warn`
 * «будет удалён через N дн.» в последние 3 дня и «Восстановить». Что видно, решает сервер
 * (модератор — всё, эксперт — свои ветки, документы — модератор и пресейл). Если прежнее место
 * недоступно (409 `RESTORE_TARGET_UNAVAILABLE`), предлагается выбрать узел той же дисциплины.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../app/router';
import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { ApiError, call } from '../../shared/api/problem';
import { formatWhen } from '../../shared/format/relative';
import { EmptyState } from '../../shared/ui/EmptyState';
import { ErrorText } from '../../shared/ui/ErrorText';
import { SettingsTabs } from '../settings/ProjectSettingsPage';
import { useProject } from '../settings/useProject';
import { MoveDialog } from '../work/menu/dialogs';
import { SOON_DAYS, daysLeft, restoreTargets } from './trash';

type Batch = components['schemas']['TrashBatch'];

export const trashKey = (projectId: string) => ['trash', projectId] as const;

function Picker({
  projectId,
  batch,
  reason,
  busy,
  onPick,
  onClose,
}: {
  projectId: string;
  batch: Batch;
  reason: string | null;
  busy: boolean;
  onPick: (parentId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const tree = useQuery({
    queryKey: ['tree', projectId, 'full'],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id: projectId } } })),
  });
  if (!tree.data) return null;
  const why = reason ? t(`trash.reason.${reason}`, { defaultValue: '' }) : '';
  return (
    <MoveDialog
      title={batch.root_title}
      heading={t('trash.pickTitle', { name: batch.root_title })}
      note={why ? t('trash.pickNoteWhy', { why }) : t('trash.pickNote')}
      confirmLabel={t('trash.restore')}
      targets={batch.discipline_id ? restoreTargets(tree.data, batch.discipline_id) : []}
      busy={busy}
      onPick={onPick}
      onClose={onClose}
    />
  );
}

export function TrashPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const project = useProject(projectId);
  const trash = useQuery({
    queryKey: trashKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/trash', { params: { path: { id: projectId } } })),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pick, setPick] = useState<{ batch: Batch; reason: string | null } | null>(null);

  const perms = new Set(project.data?.my_permissions ?? []);
  const disciplines = new Map((project.data?.disciplines ?? []).map((d) => [d.discipline_id, d.name]));
  const items = trash.data?.items ?? [];

  const restore = async (batch: Batch, target: string | null = null) => {
    setBusy(batch.batch_id);
    setError(null);
    setDone(null);
    try {
      if (batch.kind === 'document') {
        const id = batch.document?.id ?? '';
        await call(() => api.POST('/documents/{id}/restore', { params: { path: { id } } }));
      } else {
        await call(() =>
          api.POST('/trash/{batch_id}/restore', {
            params: { path: { batch_id: batch.batch_id } },
            body: target ? { target_parent_id: target } : {},
          }),
        );
        void client.invalidateQueries({ queryKey: ['tree', projectId] });
      }
      setPick(null);
      setDone(batch.root_title);
      await client.invalidateQueries({ queryKey: trashKey(projectId) });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'RESTORE_TARGET_UNAVAILABLE' && batch.kind === 'nodes') {
        const reason = e.extension('reason');
        setPick({ batch, reason: typeof reason === 'string' ? reason : null });
      } else {
        setPick(null);
        setError(e);
      }
    } finally {
      setBusy(null);
    }
  };

  const where = (batch: Batch) =>
    batch.kind === 'document'
      ? t('settings.tabs.documents')
      : ((batch.discipline_id && disciplines.get(batch.discipline_id)) ?? '');

  return (
    <div className="settings">
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{project.data?.name ?? ''}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('settings.title')}</h1>
      </div>
      <SettingsTabs projectId={projectId} active="trash" />
      <section className="sec trash" aria-labelledby="trash-title">
        <h3 id="trash-title">{t('settings.tabs.trash')}</h3>
        <ErrorText error={project.error ?? trash.error ?? error} />
        {done ? (
          <div className="trash-done" role="status">
            {t('trash.restored', { name: done })}
          </div>
        ) : null}
        {trash.isSuccess && items.length === 0 ? <EmptyState title={t('trash.empty')} hint={t('trash.keep')} /> : null}
        {items.length ? (
          <>
            <table className="t trash-table">
              <thead>
                <tr>
                  <th>{t('trash.what')}</th>
                  <th>{t('trash.who')}</th>
                  <th>{t('trash.purge')}</th>
                  <th aria-label={t('trash.actions')} />
                </tr>
              </thead>
              <tbody>
                {items.map((batch) => {
                  const left = daysLeft(batch.purge_at);
                  const can = perms.has(batch.kind === 'document' ? 'docs.restore' : 'trash.restore');
                  const path = where(batch);
                  return (
                    <tr key={batch.batch_id}>
                      <td>
                        {path ? <span className="trash-path">{path} › </span> : null}
                        <b>{batch.root_title}</b>
                        {batch.kind === 'nodes' && batch.nodes_count > 1 ? (
                          <span className="trash-count"> · {t('trash.nodes', { count: batch.nodes_count })}</span>
                        ) : null}
                      </td>
                      <td className="trash-who">
                        {batch.deleted_by?.full_name ?? t('journal.system')} ·{' '}
                        <time dateTime={batch.deleted_at}>{formatWhen(batch.deleted_at, { timeZone })}</time>
                      </td>
                      <td>
                        {left <= SOON_DAYS ? (
                          <span className="pill warn">{t('trash.soon', { count: left })}</span>
                        ) : (
                          <span className="trash-keep">{t('trash.until', { count: left })}</span>
                        )}
                      </td>
                      <td className="trash-act">
                        {can ? (
                          <button
                            type="button"
                            className="btn-sm"
                            disabled={busy !== null}
                            aria-label={t('trash.restoreName', { name: batch.root_title })}
                            onClick={() => void restore(batch)}
                          >
                            {t('trash.restore')}
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="table-foot">
              <span>{t('trash.shown', { count: items.length })}</span>
              <span>{t('trash.keep')}</span>
            </div>
          </>
        ) : null}
      </section>
      {pick ? (
        <Picker
          projectId={projectId}
          batch={pick.batch}
          reason={pick.reason}
          busy={busy !== null}
          onPick={(target) => void restore(pick.batch, target)}
          onClose={() => setPick(null)}
        />
      ) : null}
    </div>
  );
}
