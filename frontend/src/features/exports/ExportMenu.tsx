/**
 * FE-045 · «Экспорт ▾» в верхней полосе рабочего экрана (FR-EXP-01…05, DESIGN.md 6, 13):
 * источник — текущее состояние или снимок (список только с `snapshot.read`), «Excel «Часы»» —
 * всем с `export.hours`, «Excel «С деньгами» 🔒» — только с `export.money` (иначе пункта нет в DOM).
 */
import { Button, Popover, Select } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { snapshotsKey } from '../snapshots/keys';
import { ExportToast, useProjectExport, type ExportKind } from './useProjectExport';

type Snapshot = components['schemas']['Snapshot'];

export function ExportMenu({ projectId, perms }: { projectId: string; perms: readonly string[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState('current');
  const exporting = useProjectExport(projectId);
  const canSnapshots = perms.includes('snapshot.read');
  const snapshots = useQuery({
    queryKey: snapshotsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/snapshots', { params: { path: { id: projectId } } })),
    select: (data) => ([...data.items] as Snapshot[]).sort((a, b) => b.created_at.localeCompare(a.created_at)),
    enabled: open && canSnapshots,
  });
  if (!perms.includes('export.hours') && !perms.includes('export.money')) return null;
  const run = (kind: ExportKind) => {
    setOpen(false);
    exporting.mutate({ kind, snapshotId: source === 'current' ? null : source });
  };
  return (
    <>
      <Popover opened={open} onChange={setOpen} position="bottom-end" withinPortal shadow="md">
        <Popover.Target>
          <button
            type="button"
            className="btn-link"
            aria-haspopup="dialog"
            aria-expanded={open}
            disabled={exporting.isPending}
            onClick={() => setOpen((o) => !o)}
          >
            {t('exports.menu')} ▾
          </button>
        </Popover.Target>
        <Popover.Dropdown>
          <div className="exp-menu">
            {canSnapshots ? (
              <Select
                size="xs"
                label={t('exports.source')}
                value={source}
                allowDeselect={false}
                comboboxProps={{ withinPortal: false }}
                data={[
                  { value: 'current', label: t('exports.current') },
                  ...(snapshots.data ?? []).map((s) => ({
                    value: s.id,
                    label: `📷 ${s.name}${s.is_invalid ? ` · ${t('compare.invalid')}` : ''}`,
                  })),
                ]}
                onChange={(v) => setSource(v ?? 'current')}
              />
            ) : null}
            {perms.includes('export.hours') ? (
              <Button size="xs" variant="default" onClick={() => run('hours_xlsx')}>
                ⇩ {t('exports.hours')}
              </Button>
            ) : null}
            {perms.includes('export.money') ? (
              <Button size="xs" variant="default" className="money" onClick={() => run('money_xlsx')}>
                🔒 ⇩ {t('exports.money')}
              </Button>
            ) : null}
            <p className="sub">{t('exports.hint')}</p>
          </div>
        </Popover.Dropdown>
      </Popover>
      <ExportToast phase={exporting.phase} error={exporting.error} />
    </>
  );
}
