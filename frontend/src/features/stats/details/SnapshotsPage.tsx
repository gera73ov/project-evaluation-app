/**
 * FE-042 · вкладка «Снимки» (SPEC 11.10 №5, FR-SNAP-01; DESIGN.md 10.9): название, автор и дата,
 * E / P80, «в КП» в валюте (только когда сервер прислал деньги), описание. Ошибочный снимок
 * зачёркнут и не выбирается. Флажками выбираются один снимок («Сравнить с текущим») или два
 * («Сравнить два») — переход на экран сравнения 11.12 (`/stats/compare?a=…&b=…`). FE-045: «⇩» —
 * Excel «Часы» из снимка (`export.hours`), «Пометить «ошибочный»» — с `snapshot.invalidate` (FR-SNAP-02).
 */
import { Button, Checkbox } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { useSession } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDate, formatTime } from '../../../shared/format/date';
import { formatHours, formatNumber } from '../../../shared/format/number';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { ExportToast, useProjectExport } from '../../exports/useProjectExport';
import { compareHref, orderPair } from '../../compare/compare';
import { StatsShell } from './StatsShell';

type Snapshot = components['schemas']['Snapshot'];

export const snapshotsKey = (projectId: string) => ['snapshots', projectId] as const;

/** Выбор для сравнения: не больше двух, ошибочные не выбираются; третий вытесняет первый. */
export function toggleSelection(selected: readonly string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((x) => x !== id);
  return [...selected, id].slice(-2);
}

export function SnapshotsPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const [selected, setSelected] = useState<string[]>([]);
  const [invalidating, setInvalidating] = useState<Snapshot | null>(null);
  const qc = useQueryClient();
  const exporting = useProjectExport(projectId);
  const invalidate = useMutation({
    mutationFn: (id: string) => call(() => api.POST('/snapshots/{id}/invalidate', { params: { path: { id } } })),
    onSuccess: () => {
      setInvalidating(null);
      setSelected((sel) => sel.filter((x) => x !== invalidating?.id));
      void qc.invalidateQueries({ queryKey: snapshotsKey(projectId) });
    },
  });
  const snapshots = useQuery({
    queryKey: snapshotsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/snapshots', { params: { path: { id: projectId } } })),
    select: (data) => ([...data.items] as Snapshot[]).sort((a, b) => b.created_at.localeCompare(a.created_at)),
  });
  /** Одиночный снимок сравнивается с текущим; из двух «было» — более ранний (11.12 №1). */
  const compare = (a: string, b?: string) => {
    const x = items.find((s) => s.id === a);
    const y = b ? items.find((s) => s.id === b) : undefined;
    if (x && y) {
      const { older, newer } = orderPair(x, y);
      navigate(compareHref(projectId, newer.id, older.id));
    } else navigate(compareHref(projectId, 'current', a));
  };
  const items = snapshots.data ?? [];
  const currency = items.find((s) => s.money)?.money?.currency;
  const withMoney = currency !== undefined;
  const [first, second] = selected;
  return (
    <StatsShell projectId={projectId} active="snapshots">
      {({ perms }) => (
        <div className="det-one">
          <section className="card det-card" aria-labelledby="det-snaps">
            <div className="card-head">
              <h3 id="det-snaps">{t('stats.snapshots.title')}</h3>
              <span className="det-tools">
                <Button
                  size="xs"
                  variant="default"
                  disabled={selected.length !== 1}
                  onClick={() => first && compare(first)}
                >
                  {t('stats.snapshots.withCurrent')}
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  disabled={selected.length !== 2}
                  onClick={() => first && second && compare(first, second)}
                >
                  {t('stats.snapshots.two')}
                </Button>
              </span>
            </div>
            <ErrorText error={snapshots.error} />
            {snapshots.isSuccess && items.length === 0 ? (
              <p className="card-hint">{t('stats.snapshots.empty')}</p>
            ) : null}
            {items.length > 0 ? (
              <table className="t det-table snaps">
                <thead>
                  <tr>
                    <th>
                      <span className="sr-only">{t('stats.snapshots.pick')}</span>
                    </th>
                    <th>{t('stats.snapshots.name')}</th>
                    <th>{t('stats.snapshots.author')}</th>
                    <th className="r">{t('stats.snapshots.hours')}</th>
                    {withMoney ? <th className="r m">🔒 {t('stats.snapshots.quote', { currency })}</th> : null}
                    <th>{t('stats.snapshots.description')}</th>
                    <th>
                      <span className="sr-only">{t('stats.snapshots.actions')}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((s) => (
                    <tr key={s.id} className={s.is_invalid ? 'invalid' : undefined}>
                      <td>
                        <Checkbox
                          size="xs"
                          aria-label={t('stats.snapshots.pickOne', { name: s.name })}
                          disabled={s.is_invalid}
                          checked={selected.includes(s.id)}
                          onChange={() => setSelected(toggleSelection(selected, s.id))}
                        />
                      </td>
                      <td>
                        <b className="snap-name">{s.name}</b>
                        {s.is_invalid ? <span className="pill gray">{t('stats.snapshots.invalid')}</span> : null}
                      </td>
                      <td>
                        {s.created_by.full_name} · {formatDate(s.created_at, timeZone, true)}{' '}
                        {formatTime(s.created_at, timeZone)}
                      </td>
                      <td className="r num">
                        {formatHours(s.totals.e)} / {formatHours(s.totals.p80)}
                      </td>
                      {withMoney ? (
                        <td className="r m num">{s.money?.quote_cur ? formatNumber(s.money.quote_cur, 0) : '—'}</td>
                      ) : null}
                      <td className="desc">{s.description}</td>
                      <td className="acts">
                        {perms.includes('export.hours') ? (
                          <button
                            type="button"
                            className="icon-btn"
                            title={t('stats.snapshots.download')}
                            aria-label={t('stats.snapshots.downloadOne', { name: s.name })}
                            disabled={exporting.isPending}
                            onClick={() => exporting.mutate({ kind: 'hours_xlsx', snapshotId: s.id })}
                          >
                            ⇩
                          </button>
                        ) : null}
                        {perms.includes('snapshot.invalidate') && !s.is_invalid ? (
                          <button type="button" className="btn-link sm" onClick={() => setInvalidating(s)}>
                            {t('stats.snapshots.markInvalid')}
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="card-hint">{t('stats.snapshots.hint')}</p>
            <ErrorText error={invalidate.error} />
          </section>
          <ExportToast phase={exporting.phase} error={exporting.error} />
          <ConfirmDialog
            opened={invalidating !== null}
            title={t('stats.snapshots.invalidTitle')}
            message={t('stats.snapshots.invalidMessage', { name: invalidating?.name ?? '' })}
            confirmLabel={t('stats.snapshots.markInvalid')}
            danger
            busy={invalidate.isPending}
            onConfirm={() => invalidating && invalidate.mutate(invalidating.id)}
            onCancel={() => setInvalidating(null)}
          />
        </div>
      )}
    </StatsShell>
  );
}
