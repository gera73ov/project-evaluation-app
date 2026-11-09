/**
 * FE-041 · «Статистика: итоги» (SPEC 11.9 №1–4, GAP-01; DESIGN.md 10.8, 7.5).
 *
 * По фазам и по дисциплинам — часы из `GET /projects/{id}/stats` (`totals`), деньги — из его блока
 * `money` (только у ролей с деньгами и пройденным TOTP; у эксперта денежных колонок и карточки
 * «Сумма для КП» нет в DOM). Ставки, валюта, курс и НДС — из `GET /projects/{id}/money`.
 * График динамики — по `dynamics` (точка в день, GAP-01) с отметками снимков; режим «валюта» —
 * по `money.dynamics`. «⇩ Excel» — задание выгрузки вкладки с отметками FR-EXP-06.
 */
import { Button, SegmentedControl } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../../shared/api/exports';
import { call, errorMessage } from '../../../shared/api/problem';
import { formatHours, formatNumber, formatPercent, formatRate } from '../../../shared/format/number';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { moneyKey } from '../../settings/money/MoneySection';
import { useProject } from '../../settings/useProject';
import { statsKey } from '../grid/ReadinessPage';
import { StatsHeader } from '../StatsTabs';
import { DynamicsChart, type Marker, type Series } from './DynamicsChart';
import { disciplineRows, phaseRows, pmBasePhases, shareOf, sumCosts, type Row } from './totals';

type Stats = components['schemas']['Stats'];
type Money = components['schemas']['ProjectMoney'];
type Figure = components['schemas']['MoneyFigure'];
type Hours = components['schemas']['HoursTotals'];
type QuoteFigure = components['schemas']['QuoteFigure'];

const FIGURES: readonly QuoteFigure[] = ['e', 'p80', 'p90'];
const LABEL = new Map<QuoteFigure, string>([
  ['e', 'E'],
  ['p80', 'P80'],
  ['p90', 'P90'],
]);

const money0 = (v: string | null) => (v === null ? '—' : formatNumber(v, 0));

function Share({ value, pm = false }: { value: string | null; pm?: boolean }) {
  if (value === null) return <>—</>;
  return (
    <span className="share">
      <i className={pm ? 'pm' : undefined} style={{ width: `${Math.min(100, Number(value)) * 0.6}px` }} />
      {formatPercent(value)}
    </span>
  );
}

function HoursCells({ hours, pm = false }: { hours: Hours | null; pm?: boolean }) {
  return (
    <>
      <td className="r">{formatHours(hours?.e ?? null)}</td>
      <td className="r">{formatHours(hours?.sigma ?? null)}</td>
      <td className="r">{pm ? '—' : formatHours(hours?.p80 ?? null)}</td>
      <td className="r">{pm ? '—' : formatHours(hours?.p90 ?? null)}</td>
    </>
  );
}

function PhasesCard({
  rows,
  stats,
  pmLabel,
  hasMoney,
  pmCost,
  totalCost,
}: {
  rows: Row[];
  stats: Stats;
  pmLabel: { pct: string; base: number };
  hasMoney: boolean;
  pmCost: string | null;
  totalCost: string | null;
}) {
  const { t } = useTranslation();
  const tot = stats.totals;
  return (
    <section className="card tot-card" aria-labelledby="tot-phases">
      <div className="card-head">
        <h3 id="tot-phases">{t('stats.totals.byPhase')}</h3>
        <span className="pill acc">{t('stats.totals.quote', { figure: LABEL.get(tot.quote_figure) })}</span>
      </div>
      <table className="t tot-table">
        <thead>
          <tr>
            <th>{t('stats.totals.phase')}</th>
            <th className="r">{t('stats.totals.e')}</th>
            <th className="r">σ</th>
            <th className="r">P80</th>
            <th className="r">P90</th>
            <th>{t('stats.totals.share')}</th>
            {hasMoney ? <th className="r m">🔒 {t('stats.totals.cost')}</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <HoursCells hours={r.hours} />
              <td>
                <Share value={r.share} />
              </td>
              {hasMoney ? <td className="r m">{money0(r.cost)}</td> : null}
            </tr>
          ))}
          <tr className="sum">
            <td>{t('stats.totals.works')}</td>
            <HoursCells hours={tot.works} />
            <td>{formatPercent(shareOf(tot.works.e, tot.total.e))}</td>
            {hasMoney ? <td className="r m">{money0(sumCosts(rows))}</td> : null}
          </tr>
          <tr>
            <td>
              {t('stats.totals.pm', { pct: formatNumber(pmLabel.pct, 0) })}{' '}
              <span className="sub">{t('stats.totals.pmBase', { count: pmLabel.base })}</span>
            </td>
            <HoursCells hours={tot.pm} pm />
            <td>
              <Share value={shareOf(tot.pm.e, tot.total.e)} pm />
            </td>
            {hasMoney ? <td className="r m">{money0(pmCost)}</td> : null}
          </tr>
          <tr className="total">
            <td>{t('stats.totals.total')}</td>
            <HoursCells hours={tot.total} />
            <td>{formatPercent('100')}</td>
            {hasMoney ? <td className="r m">{money0(totalCost)}</td> : null}
          </tr>
        </tbody>
      </table>
      <p className="card-hint">{t('stats.totals.phaseHint')}</p>
    </section>
  );
}

function DisciplinesCard({
  rows,
  stats,
  money,
  hasMoney,
}: {
  rows: Row[];
  stats: Stats;
  money: Money | undefined;
  hasMoney: boolean;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'hours' | 'pct'>('hours');
  const works = stats.totals.works;
  const rates = new Map((money?.rates ?? []).map((r) => [r.discipline_id, r.rate_rub]));
  const cell = (value: string | undefined, whole: string | undefined) => {
    if (value === undefined) return '—';
    if (mode === 'hours') return formatHours(value);
    return whole === undefined ? '—' : formatPercent(shareOf(value, whole), 1);
  };
  return (
    <section className="card tot-card" aria-labelledby="tot-disc">
      <div className="card-head">
        <h3 id="tot-disc">{t('stats.totals.byDiscipline')}</h3>
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={(v) => setMode(v as 'hours' | 'pct')}
          data={[
            { value: 'hours', label: t('stats.totals.hours') },
            { value: 'pct', label: t('stats.totals.pctWorks') },
          ]}
        />
      </div>
      <table className="t tot-table">
        <thead>
          <tr>
            <th>{t('stats.totals.discipline')}</th>
            <th className="r">{mode === 'hours' ? t('stats.totals.e') : 'E, %'}</th>
            <th className="r">σ</th>
            <th className="r">P80</th>
            <th className="r">P90</th>
            {hasMoney ? <th className="r m">🔒 {t('stats.totals.rate')}</th> : null}
            {hasMoney ? <th className="r m">🔒 {t('stats.totals.cost')}</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const rate = rates.get(r.id) ?? null;
            return (
              <tr key={r.id} className={r.hours ? undefined : 'empty'}>
                <td>
                  {r.name} {r.hours ? null : <span className="pill gray">{t('stats.totals.noHours')}</span>}
                </td>
                <td className="r">{cell(r.hours?.e, works.e)}</td>
                <td className="r">{mode === 'hours' ? formatHours(r.hours?.sigma ?? null) : '—'}</td>
                <td className="r">{cell(r.hours?.p80, works.p80)}</td>
                <td className="r">{cell(r.hours?.p90, works.p90)}</td>
                {hasMoney ? (
                  <td className={rate === null ? 'r rate-missing' : 'r m'}>
                    {rate === null ? t('stats.totals.rateMissing') : formatNumber(rate, 0)}
                  </td>
                ) : null}
                {hasMoney ? <td className="r m">{money0(rate === null ? null : r.cost)}</td> : null}
              </tr>
            );
          })}
          <tr className="sum">
            <td>{t('stats.totals.works')}</td>
            <td className="r">{mode === 'hours' ? formatHours(works.e) : formatPercent('100')}</td>
            <td className="r">{mode === 'hours' ? formatHours(works.sigma ?? null) : '—'}</td>
            <td className="r">{mode === 'hours' ? formatHours(works.p80) : formatPercent('100')}</td>
            <td className="r">{mode === 'hours' ? formatHours(works.p90) : formatPercent('100')}</td>
            {hasMoney ? <td /> : null}
            {hasMoney ? <td className="r m">{money0(sumCosts(rows))}</td> : null}
          </tr>
        </tbody>
      </table>
      {hasMoney ? <p className="card-hint">{t('stats.totals.disciplineHint')}</p> : null}
    </section>
  );
}

function QuoteCard({
  stats,
  money,
  figures,
}: {
  stats: Stats;
  money: Money | undefined;
  figures: Map<string, Figure>;
}) {
  const { t } = useTranslation();
  const quote = stats.totals.quote_figure;
  const cur = money?.currency;
  const foreign = cur !== undefined && cur !== 'RUB';
  const hours = new Map(Object.entries(stats.totals.total)) as Map<string, string>;
  const row = (label: string, pick: (f: Figure) => string | null, strong = false) => (
    <tr className={strong ? 'strong' : undefined}>
      <th scope="row">{label}</th>
      {FIGURES.map((f) => {
        const fig = figures.get(f);
        return (
          <td key={f} className={f === quote ? 'r on' : 'r'}>
            {fig ? money0(pick(fig)) : '—'}
          </td>
        );
      })}
    </tr>
  );
  return (
    <section className="card tot-card m" aria-labelledby="tot-quote">
      <div className="card-head">
        <h3 id="tot-quote" className="money">
          🔒 {t('stats.totals.quoteSum')}
        </h3>
        {money ? (
          <span className="sub">
            {[
              foreign ? t('stats.totals.rateLine', { currency: cur, rate: formatRate(money.exchange_rate) }) : cur,
              money.vat_percent === null
                ? null
                : t('stats.totals.vatLine', { pct: formatNumber(money.vat_percent, 0) }),
              stats.totals.duration_weeks ? t('stats.totals.weeks', { count: stats.totals.duration_weeks }) : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        ) : null}
      </div>
      <table className="t tot-quote">
        <thead>
          <tr>
            <td />
            {FIGURES.map((f) => (
              <th key={f} className={f === quote ? 'r on' : 'r'}>
                {LABEL.get(f)}
                {f === quote ? ` · ${t('stats.totals.inQuote')}` : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">{t('stats.totals.hoursRow')}</th>
            {FIGURES.map((f) => (
              <td key={f} className={f === quote ? 'r on' : 'r'}>
                {formatHours(hours.get(f) ?? null)}
              </td>
            ))}
          </tr>
          {row(t('stats.totals.noVatRub'), (f) => f.total_rub)}
          {row(
            t('stats.totals.vatRub', { pct: money?.vat_percent ? formatNumber(money.vat_percent, 0) : '' }),
            (f) => f.vat_rub,
          )}
          {row(t('stats.totals.withVatRub'), (f) => f.total_with_vat_rub, true)}
          {foreign ? row(t('stats.totals.noVatCur', { currency: cur }), (f) => f.total_cur) : null}
          {foreign ? row(t('stats.totals.withVatCur', { currency: cur }), (f) => f.total_with_vat_cur) : null}
        </tbody>
      </table>
      <p className="card-hint">{t('stats.totals.quoteHint')}</p>
    </section>
  );
}

function DynamicsCard({
  projectId,
  stats,
  currency,
  canSnapshots,
}: {
  projectId: string;
  stats: Stats;
  currency: string | undefined;
  canSnapshots: boolean;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'hours' | 'money'>('hours');
  const snapshots = useQuery({
    queryKey: ['snapshots', projectId],
    queryFn: () => call(() => api.GET('/projects/{id}/snapshots', { params: { path: { id: projectId } } })),
    enabled: canSnapshots,
  });
  const markers: Marker[] = (snapshots.data?.items ?? [])
    .filter((s) => !s.is_invalid)
    .map((s) => ({ id: s.id, date: s.created_at.slice(0, 10), label: s.name }));
  const moneyDyn = stats.money?.dynamics ?? [];
  const money = mode === 'money' && stats.money !== undefined && currency !== undefined;
  const num = (v: string | null) => (v === null ? null : Number(v));
  const dates = money ? moneyDyn.map((d) => d.date) : stats.dynamics.map((d) => d.date);
  const series: Series[] = money
    ? [
        {
          key: 'quote',
          label: t('stats.dynamics.quote', { currency }),
          className: 'p80',
          values: moneyDyn.map((d) => num(d.quote_cur)),
        },
      ]
    : [
        { key: 'e', label: 'E', className: 'e', values: stats.dynamics.map((d) => num(d.e)) },
        { key: 'p80', label: 'P80', className: 'p80', values: stats.dynamics.map((d) => num(d.p80)) },
      ];
  return (
    <section className="card tot-card" aria-labelledby="tot-dyn">
      <div className="card-head">
        <h3 id="tot-dyn">{t('stats.dynamics.title')}</h3>
        {stats.money && currency ? (
          <SegmentedControl
            size="xs"
            value={mode}
            onChange={(v) => setMode(v as 'hours' | 'money')}
            data={[
              { value: 'hours', label: t('stats.totals.hours') },
              { value: 'money', label: `${currency} 🔒` },
            ]}
          />
        ) : null}
      </div>
      {dates.length === 0 ? (
        <p className="card-hint">{t('stats.dynamics.empty')}</p>
      ) : (
        <DynamicsChart
          title={t('stats.dynamics.title')}
          dates={dates}
          series={series}
          markers={markers}
          format={(v) => (money ? formatNumber(String(Math.round(v)), 0) : formatNumber(String(v), 0))}
        />
      )}
    </section>
  );
}

export function TotalsPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const project = useProject(projectId);
  const stats = useQuery({
    queryKey: statsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/stats', { params: { path: { id: projectId } } })),
    select: (data) => data as Stats,
  });
  const money = useQuery({
    queryKey: moneyKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/money', { params: { path: { id: projectId } } })),
    select: (data) => data as Money,
    enabled: Boolean(stats.data?.money),
    retry: false,
  });
  const exporting = useMutation({
    mutationFn: () =>
      downloadExport(
        () =>
          call(() =>
            api.GET('/projects/{id}/stats/{tab}/export', {
              params: { path: { id: projectId, tab: 'totals' }, query: { format: 'xlsx' } },
            }),
          ),
        { fallbackName: 'totals.xlsx' },
      ),
  });

  const data = project.data;
  const perms = data?.my_permissions ?? [];
  const head = (
    <StatsHeader
      projectId={projectId}
      projectName={data?.name ?? ''}
      active="totals"
      canReadQuestions={perms.includes('cq.read')}
      actions={
        perms.includes('export.hours') ? (
          <Button variant="default" size="xs" loading={exporting.isPending} onClick={() => exporting.mutate()}>
            ⇩ {t('stats.excel')}
          </Button>
        ) : null
      }
    />
  );
  if (!data || !stats.data)
    return (
      <div className="settings stats">
        {head}
        <ErrorText error={project.error ?? stats.error} />
      </div>
    );

  const s = stats.data;
  const hasMoney = s.money !== undefined;
  const figures = new Map(Object.entries(s.money?.figures ?? {})) as Map<string, Figure>;
  const e = figures.get('e');
  const pmCost = e?.rows_rub.find((r) => r.discipline_id === null)?.amount ?? null;
  return (
    <div className="settings stats">
      {head}
      {exporting.error ? (
        <div className="err tot-err" role="alert">
          {exporting.error instanceof ExportTimeout ? t('stats.exportTimeout') : errorMessage(exporting.error)}
        </div>
      ) : null}
      <div className="tot-grid">
        <PhasesCard
          rows={phaseRows(data, s)}
          stats={s}
          pmLabel={{ pct: data.pm_percent, base: pmBasePhases(data) }}
          hasMoney={hasMoney}
          pmCost={pmCost}
          totalCost={e?.total_rub ?? null}
        />
        <DisciplinesCard rows={disciplineRows(data, s)} stats={s} money={money.data} hasMoney={hasMoney} />
        {hasMoney ? <QuoteCard stats={s} money={money.data} figures={figures} /> : null}
        <DynamicsCard
          projectId={projectId}
          stats={s}
          currency={money.data?.currency}
          canSnapshots={perms.includes('snapshot.read')}
        />
      </div>
    </div>
  );
}
