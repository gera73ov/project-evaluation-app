/**
 * FE-044 · сравнение со снимком (SPEC 11.12, FR-SNAP-03/04/05; DESIGN.md 10.11): выбор «что с чем»
 * (слева — текущее состояние или снимок, справа — снимок; ошибочные зачёркнуты, но выбираются),
 * сводка E и P80 «было → стало», денежные карточки только когда сервер прислал `money`, фильтры
 * видов изменения с числами, таблица строк, пояснение про УП и «Экспорт сравнения в Excel».
 *
 * Значений O–R–P «было → стало» и строк параметров в контракте пока нет (CR-008): вместо значений
 * показываются имена изменённых полей.
 */
import { Button, Select } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link, useNavigate, useSearchParam } from '../../app/router';
import { api, type components } from '../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../shared/api/exports';
import { call, errorMessage } from '../../shared/api/problem';
import { formatDateTime } from '../../shared/format/date';
import { formatHours, formatNumber } from '../../shared/format/number';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useProject } from '../settings/useProject';
import { statsKey } from '../stats/grid/ReadinessPage';
import { snapshotsKey } from '../stats/details/SnapshotsPage';
import { CHANGES, beforeAfter, compareHref, countByChange, deltaTone, pmDelta, sidesOf, type Change } from './compare';

type Snapshot = components['schemas']['Snapshot'];
type Diff = components['schemas']['Diff'];
type Stats = components['schemas']['Stats'];

const CHANGE_TONE = new Map<Change, string>([
  ['added', 'ok'],
  ['removed', 'bad'],
  ['changed', 'warn'],
  ['moved', 'gray'],
]);

const signed = (value: string, places: number) => formatNumber(value, places, { sign: true });

export function ComparePage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const sides = sidesOf(useSearchParam('a'), useSearchParam('b'));
  const project = useProject(projectId);
  const perms = project.data?.my_permissions ?? [];
  const [filter, setFilter] = useState<Change | null>(null);
  const snapshots = useQuery({
    queryKey: snapshotsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/snapshots', { params: { path: { id: projectId } } })),
    select: (data) => ([...data.items] as Snapshot[]).sort((a, b) => b.created_at.localeCompare(a.created_at)),
  });
  const diff = useQuery({
    queryKey: ['diff', sides?.right, sides?.left],
    queryFn: () =>
      call(() =>
        api.GET('/snapshots/{id}/diff', {
          params: { path: { id: sides?.right ?? '' }, query: { with: sides?.left ?? 'current' } },
        }),
      ),
    select: (data) => data as Diff,
    enabled: sides !== null,
  });
  const leftIsCurrent = sides?.left === 'current';
  /** Текущая сумма «в КП» — последняя точка денежной динамики статистики. */
  const stats = useQuery({
    queryKey: statsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/stats', { params: { path: { id: projectId } } })),
    select: (data) => data as Stats,
    enabled: leftIsCurrent && diff.data?.money !== undefined,
  });
  const exporting = useMutation({
    mutationFn: () =>
      downloadExport(
        () =>
          call(() =>
            api.POST('/snapshots/{id}/diff/export', {
              params: { path: { id: sides?.right ?? '' } },
              body: { with: sides?.left ?? 'current' },
            }),
          ),
        { fallbackName: 'compare.xlsx' },
      ),
  });

  const items = snapshots.data ?? [];
  const byId = new Map(items.map((s) => [s.id, s]));
  const option = (s: Snapshot) => ({
    value: s.id,
    label: `📷 ${s.name} · ${formatDateTime(s.created_at, undefined, false)}, ${s.created_by.full_name}${
      s.is_invalid ? ` · ${t('compare.invalid')}` : ''
    }`,
  });
  const go = (left: string, right: string) => navigate(compareHref(projectId, left, right));
  const data = diff.data;
  const rows = (data?.rows ?? []).filter((r) => filter === null || r.change === filter);
  const counts = countByChange(data?.rows ?? []);
  const base = sides ? byId.get(sides.right) : undefined;

  return (
    <div className="settings stats compare">
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{project.data?.name ?? ''}</Link>
        <span aria-hidden="true"> › </span>
        <Link to={`/projects/${projectId}/stats/snapshots`}>{t('stats.title')}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('compare.title')}</h1>
        <span className="sp" />
        {perms.includes('export.hours') && sides ? (
          <Button size="xs" variant="default" loading={exporting.isPending} onClick={() => exporting.mutate()}>
            {t('compare.export')}
          </Button>
        ) : null}
        <Link to={`/projects/${projectId}/stats/snapshots`} className="btn-link">
          ← {t('compare.back')}
        </Link>
      </div>
      {exporting.error ? (
        <div className="err" role="alert">
          {exporting.error instanceof ExportTimeout ? t('stats.exportTimeout') : errorMessage(exporting.error)}
        </div>
      ) : null}
      <div className="cmp-pick">
        <span className="sub">{t('compare.what')}</span>
        <Select
          size="sm"
          className="cmp-side"
          aria-label={t('compare.left')}
          value={sides?.left ?? 'current'}
          allowDeselect={false}
          data={[{ value: 'current', label: t('compare.current') }, ...items.map(option)]}
          renderOption={({ option: o }) => (byId.get(o.value)?.is_invalid ? <s>{o.label}</s> : <span>{o.label}</span>)}
          onChange={(v) => v && sides && go(v, sides.right)}
        />
        <span aria-hidden="true">↔</span>
        <Select
          size="sm"
          className="cmp-side wide"
          aria-label={t('compare.right')}
          placeholder={t('compare.pickSnapshot')}
          value={sides?.right ?? null}
          allowDeselect={false}
          data={items.map(option)}
          renderOption={({ option: o }) => (byId.get(o.value)?.is_invalid ? <s>{o.label}</s> : <span>{o.label}</span>)}
          onChange={(v) => v && go(sides?.left ?? 'current', v)}
        />
      </div>
      {!sides ? <p className="card-hint">{t('compare.none')}</p> : null}
      <ErrorText error={diff.error ?? snapshots.error} />
      {data && base ? (
        <>
          <div className="cmp-cards">
            <SummaryCard label={t('compare.totalE')} before={base.totals.e} delta={data.totals_delta.e} pct />
            <SummaryCard label={t('compare.totalP80')} before={base.totals.p80} delta={data.totals_delta.p80} />
            {data.money ? (
              <>
                <section className="cmp-card money" aria-label={t('compare.rub')}>
                  <div className="lbl">🔒 {t('compare.rub')}</div>
                  {/* «было → стало» в рублях в контракте пока нет (CR-008) — только разница */}
                  <div className="val">
                    {data.money.total_delta_rub === null ? '—' : `${signed(data.money.total_delta_rub, 0)} ₽`}
                  </div>
                  <div className="dl">
                    {data.money.rates_effect_rub === null || data.money.rates_effect_rub === '0'
                      ? t('compare.ratesSame')
                      : t('compare.ratesEffect', { value: signed(data.money.rates_effect_rub, 0) })}
                  </div>
                </section>
                <CurrencyCard
                  before={base.money?.quote_cur ?? null}
                  after={
                    leftIsCurrent
                      ? (stats.data?.money?.dynamics?.at(-1)?.quote_cur ?? null)
                      : (byId.get(sides?.left ?? '')?.money?.quote_cur ?? null)
                  }
                  currency={base.money?.currency ?? ''}
                  exchange={data.money.exchange_effect_cur}
                />
              </>
            ) : null}
          </div>
          <div className="chips cmp-chips" role="group" aria-label={t('compare.filter')}>
            {([null, ...CHANGES] as const).map((c) => (
              <button
                key={c ?? 'all'}
                type="button"
                className={`chip sm${filter === c ? ' on' : ''}`}
                aria-pressed={filter === c}
                onClick={() => setFilter(c)}
              >
                {t(`compare.chip.${c ?? 'all'}`)} <span className="c">{counts.get(c ?? 'all') ?? 0}</span>
              </button>
            ))}
          </div>
          <section className="card cmp-table-card">
            {rows.length === 0 ? <p className="card-hint">{t('compare.empty')}</p> : null}
            {rows.length > 0 ? (
              <table className="t cmp-table">
                <thead>
                  <tr>
                    <th>{t('compare.change')}</th>
                    <th>{t('compare.node')}</th>
                    <th>{t('compare.fields')}</th>
                    <th className="r">{t('compare.deltaE')}</th>
                    <th>{t('compare.lastBy')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.node_id}>
                      <td>
                        <span className={`pill ${CHANGE_TONE.get(r.change) ?? 'gray'}`}>
                          {t(`compare.kind.${r.change}`)}
                        </span>
                      </td>
                      <td>
                        <span className="sub">{r.path.map((p) => `${p} › `).join('')}</span>
                        <b>{r.title}</b>
                      </td>
                      <td className="sub">
                        {r.change === 'changed' || r.change === 'moved'
                          ? r.fields.length > 0
                            ? t('compare.changedFields', {
                                fields: r.fields.map((f) => t(`compare.field.${f}`, { defaultValue: f })).join(', '),
                              })
                            : '—'
                          : r.change === 'added'
                            ? t('compare.wasNone')
                            : t('compare.nowNone')}
                      </td>
                      <td className={`r num ${deltaTone(r.delta_e) ?? ''}`}>{signed(r.delta_e, 1)}</td>
                      <td>{r.last_changed_by?.full_name ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="card-hint">
              {t('compare.pmNote', {
                pct: project.data ? formatNumber(project.data.pm_percent, 1) : '—',
                delta: signed(pmDelta(data), 1),
              })}
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function SummaryCard({
  label,
  before,
  delta,
  pct = false,
}: {
  label: string;
  before: string;
  delta: string;
  pct?: boolean;
}) {
  const v = beforeAfter(before, delta);
  return (
    <section className="cmp-card" aria-label={label}>
      <div className="lbl">{label}</div>
      <div className="val">
        {formatHours(v.before)} → {formatHours(v.after, { unit: true })}
      </div>
      <div className={`dl ${deltaTone(delta) ?? ''}`}>
        {signed(delta, 1)} ч
        {pct && v.pct !== null ? ` (${v.pct > 0 ? '+' : ''}${formatNumber(String(v.pct), 1)}%)` : ''}
      </div>
    </section>
  );
}

function CurrencyCard({
  before,
  after,
  currency,
  exchange,
}: {
  before: string | null;
  after: string | null;
  currency: string;
  exchange: string | null;
}) {
  const { t } = useTranslation();
  const label = t('compare.cur', { currency });
  const delta = before !== null && after !== null ? String(Number(after) - Number(before)) : null;
  return (
    <section className="cmp-card money" aria-label={label}>
      <div className="lbl">🔒 {label}</div>
      <div className="val">
        {before === null ? '—' : formatNumber(before, 0)} → {after === null ? '—' : formatNumber(after, 0)}
      </div>
      <div className={`dl ${delta ? (deltaTone(delta) ?? '') : ''}`}>
        {delta === null ? '—' : `${signed(delta, 0)} ${currency}`}
        {exchange !== null && exchange !== '0'
          ? `, ${t('compare.exchangeEffect', { value: signed(exchange, 0) })}`
          : ''}
      </div>
    </section>
  );
}
