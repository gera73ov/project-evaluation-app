/**
 * FE-040 · «Статистика: готовность» (SPEC 11.8 №1–10, 10.1, FR-REV-03/04, GAP-08; DESIGN.md 10.7).
 *
 * Сетка «фаза × дисциплина»: ячейка — кнопка, ведёт на рабочий экран с раскрытой веткой
 * (`/projects/:id?node=`). Строка «Стоимость» и денежные строки «Итога проекта» — только с деньгами:
 * у остальных их нет в DOM (сервер блок `money` им не отдаёт). «Напомнить не начавшим» — с правом
 * `team.remind`; если напоминать некому, кнопка неактивна и рядом объяснение.
 */
import { useMutation, useQuery } from '@tanstack/react-query';
import Decimal from 'decimal.js';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { useSession } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { call, errorMessage } from '../../../shared/api/problem';
import { formatDate, formatTime } from '../../../shared/format/date';
import { formatHours, formatNumber, formatPercent } from '../../../shared/format/number';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { useReadOnlyOffline } from '../../../shared/ws/WsProvider';
import { moneyKey } from '../../settings/money/MoneySection';
import { useProject } from '../../settings/useProject';
import { StatsHeader } from '../StatsTabs';
import { buildGrid, cellKey, remindState, type Cell } from './readiness';
import { RatioList, useRatioName } from './RatioList';

type Stats = components['schemas']['Stats'];
type Tree = components['schemas']['Tree'];
type Figure = components['schemas']['MoneyFigure'];

export const statsKey = (projectId: string) => ['stats', projectId] as const;

const STATUS_MARK = new Map([
  ['done', '✓'],
  ['draft', '✎'],
  ['not_started', '○'],
]);

function CellView({ cell, timeZone, onOpen }: { cell: Cell; timeZone: string | undefined; onOpen: () => void }) {
  const { t } = useTranslation();
  const status = cell.status;
  if (status === 'not_needed')
    return (
      <div className="rg-cell not_needed" role="cell">
        {t('status.branch.not_needed')}
      </div>
    );
  const today = cell.at ? formatDate(cell.at, timeZone) === formatDate(new Date(), timeZone) : false;
  const when = cell.at
    ? today
      ? `${t('stats.grid.today')} ${formatTime(cell.at, timeZone)}`
      : formatDate(cell.at, timeZone, true)
    : null;
  return (
    <div role="cell" className="rg-td">
      <button type="button" className={`rg-cell ${status}`} onClick={onOpen} disabled={!cell.nodeId}>
        <span className="rg-status">
          {STATUS_MARK.get(status)} {t(`status.branch.${status}`)}
        </span>
        <span className="rg-e">{cell.e !== null && status !== 'not_started' ? formatHours(cell.e) : '—'}</span>
        {cell.who && status !== 'not_started' ? (
          <span className="rg-who">
            {cell.who}
            {when ? ` · ${when}` : ''}
          </span>
        ) : null}
        <span className="rg-flags">
          {cell.large ? <span className="flag acc">◆ {t('stats.grid.large')}</span> : null}
          {cell.wideFork ? <span className="flag warn">↔ {t('stats.grid.wideFork')}</span> : null}
          {cell.questions ? (
            <span className="flag warn">? {t('stats.grid.questions', { count: cell.questions })}</span>
          ) : null}
          {cell.unaccounted ? (
            <span className="flag bad">{t('stats.grid.unaccounted', { count: cell.unaccounted })}</span>
          ) : null}
          {cell.noExpert ? <span className="flag bad">{t('stats.grid.noExpert')}</span> : null}
          {cell.overdueDays ? (
            <span className="flag bad">⏰ {t('stats.grid.overdue', { count: cell.overdueDays })}</span>
          ) : null}
        </span>
      </button>
    </div>
  );
}

function MoneyRows({ figure, label, cur }: { figure: Figure; label: string; cur: string | undefined }) {
  const { t } = useTranslation();
  const rows: [string, string | null, boolean][] = [
    [t('stats.total.noVat'), figure.total_rub, true],
    [t('stats.total.vat'), figure.vat_rub, false],
    [t('stats.total.withVat'), figure.total_with_vat_rub, true],
  ];
  if (cur && cur !== 'RUB')
    rows.push(
      [t('stats.total.quoteCur', { figure: label, currency: cur }), figure.total_cur, true],
      [t('stats.total.quoteCurVat', { currency: cur }), figure.total_with_vat_cur, true],
    );
  return (
    <dl className="tot-money">
      {rows.map(([name, value, strong], i) => (
        <div key={name} className={i === 3 ? 'sep' : undefined}>
          <dt>
            <span aria-hidden="true">🔒</span> {name}
          </dt>
          <dd className={strong ? 'strong' : undefined}>{value === null ? '—' : formatNumber(value, 0)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ReadinessPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const offline = useReadOnlyOffline();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const project = useProject(projectId);
  const stats = useQuery({
    queryKey: statsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/stats', { params: { path: { id: projectId } } })),
    select: (data) => data as Stats,
  });
  const tree = useQuery({
    queryKey: ['tree', projectId],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id: projectId } } })),
    select: (data) => data as Tree,
    staleTime: 30_000,
  });
  // валюта КП — из денег проекта (тот же запрос, что у настроек); без денег не запрашивается
  const currency = useQuery({
    queryKey: moneyKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/money', { params: { path: { id: projectId } } })),
    select: (data) => data.currency,
    enabled: Boolean(stats.data?.money),
    retry: false,
  });
  const ratioName = useRatioName(new Map((project.data?.disciplines ?? []).map((d) => [d.discipline_id, d.name])));
  const [reminded, setReminded] = useState<number | null>(null);
  const remind = useMutation({
    mutationFn: () => call(() => api.POST('/projects/{id}/remind', { params: { path: { id: projectId } } })),
    onSuccess: (data) => setReminded(data.sent_to),
  });

  const data = project.data;
  const perms = data?.my_permissions ?? [];
  const head = (
    <StatsHeader
      projectId={projectId}
      projectName={data?.name ?? ''}
      active="readiness"
      canReadQuestions={perms.includes('cq.read')}
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
  const grid = buildGrid(data, s, tree.data);
  const names = new Map(grid.disciplines.map((d) => [d.id, d.name]));
  const money = s.money;
  const cost = new Map((money?.cost_by_discipline ?? []).map((c) => [c.discipline_id, c.cost_rub]));
  const quote = s.totals.quote_figure;
  const figure = money?.figures ? new Map(Object.entries(money.figures)).get(quote) : undefined;
  const reminder = remindState(grid);
  const canRemind = perms.includes('team.remind') && !offline;
  const totals = s.totals;
  const hoursOf = (id: string) => totals.by_discipline.find((d) => d.discipline_id === id)?.hours.e ?? '0';
  const open = (cell: Cell) => cell.nodeId && navigate(`/projects/${projectId}?node=${cell.nodeId}`);
  const columns = { gridTemplateColumns: `170px repeat(${grid.disciplines.length}, minmax(0, 1fr))` };

  return (
    <div className="settings stats">
      {head}
      <div className="stats-grid">
        <section className="rg-main" aria-label={t('stats.tabs.readiness')}>
          <div className="rg" role="table" aria-label={t('stats.grid.title')} style={columns}>
            <div role="row" className="rg-row">
              <span role="columnheader" className="rg-h">
                {t('stats.grid.corner')}
              </span>
              {grid.disciplines.map((d) => (
                <span key={d.id} role="columnheader" className="rg-h">
                  {d.name}
                </span>
              ))}
            </div>
            {grid.phases.map((phase) => (
              <div key={phase.id} role="row" className="rg-row">
                <span role="rowheader" className="rg-phase">
                  {phase.name}
                </span>
                {grid.disciplines.map((d) => {
                  const cell = grid.cells.get(cellKey(phase.id, d.id));
                  return cell ? (
                    <CellView key={d.id} cell={cell} timeZone={timeZone} onOpen={() => open(cell)} />
                  ) : null;
                })}
              </div>
            ))}
            {money ? (
              <div role="row" className="rg-row rg-cost">
                <span role="rowheader" className="rg-phase money">
                  <span aria-hidden="true">🔒</span> {t('stats.grid.cost')}
                </span>
                {grid.disciplines.map((d) => {
                  const value = cost.get(d.id) ?? null;
                  return (
                    <span key={d.id} role="cell" className="rg-money">
                      {value === null ? '—' : formatNumber(value, 0)}
                    </span>
                  );
                })}
              </div>
            ) : null}
          </div>
          <p className="rg-legend">{t('stats.grid.legend')}</p>
          <p className="rg-legend">{t('stats.grid.click')}</p>
          {canRemind ? (
            <div className="rg-remind">
              <button
                type="button"
                className="btn-sm"
                disabled={!reminder.canRemind || remind.isPending}
                onClick={() => remind.mutate()}
              >
                ✉ {t('stats.remind.button')}
              </button>
              <span className="rg-remind-why">
                {reminded !== null
                  ? t('stats.remind.sent', { count: reminded })
                  : reminder.canRemind
                    ? t('stats.remind.hint')
                    : reminder.withoutExpert.length
                      ? t('stats.remind.noneNoExpert', { names: reminder.withoutExpert.join(', ') })
                      : t('stats.remind.none')}
              </span>
            </div>
          ) : null}
          {remind.error ? (
            <div className="err" role="alert">
              {errorMessage(remind.error)}
            </div>
          ) : null}
        </section>

        <aside className="docs-side">
          <section className="card" aria-labelledby="st-total">
            <h3 id="st-total">{t('stats.total.title')}</h3>
            <dl className="tot-list">
              <div>
                <dt>{t('stats.total.works')}</dt>
                <dd>{formatHours(totals.works.e, { unit: true })}</dd>
              </div>
              <div>
                <dt>{t('stats.total.pm', { percent: formatPercent(String(data.pm_percent)) })}</dt>
                <dd>{formatHours(totals.pm.e, { unit: true })}</dd>
              </div>
              <div className="sum">
                <dt>{t('stats.total.forks')}</dt>
                <dd>
                  {(['e', 'p80', 'p90'] as const).map((k, i) => (
                    <span key={k}>
                      {i ? ' / ' : ''}
                      <span className={k === quote ? 'quote' : undefined}>
                        {formatHours(k === 'e' ? totals.total.e : k === 'p80' ? totals.total.p80 : totals.total.p90)}
                      </span>
                    </span>
                  ))}{' '}
                  {t('top.hours')}
                </dd>
              </div>
            </dl>
            <p className="card-hint">
              {t('stats.total.quote', { figure: quote.toUpperCase() })}
              {totals.duration_weeks ? ` · ${t('stats.total.weeks', { count: totals.duration_weeks })}` : ''}
            </p>
            {figure ? <MoneyRows figure={figure} label={quote.toUpperCase()} cur={currency.data} /> : null}
          </section>

          <section className="card" aria-labelledby="st-ratios">
            <h3 id="st-ratios">{t('stats.ratios.title')}</h3>
            <RatioList ratios={s.ratios} name={ratioName} />
          </section>

          <section className="card" aria-labelledby="st-reviewed">
            <h3 id="st-reviewed">{t('stats.reviewed.title')}</h3>
            <dl className="tot-list">
              {s.reviewed.map((r) => {
                const total = new Decimal(hoursOf(r.discipline_id));
                const reviewed = r.reviewed_pct === null ? null : total.times(r.reviewed_pct).div(100);
                const self = reviewed && r.self_review_pct !== null ? reviewed.times(r.self_review_pct).div(100) : null;
                return (
                  <div key={r.discipline_id} className="rev">
                    <dt>{names.get(r.discipline_id) ?? '?'}</dt>
                    <dd>
                      {t('stats.reviewed.line', {
                        done: formatHours(reviewed ?? '0'),
                        total: formatHours(total),
                        pct: formatPercent(r.reviewed_pct),
                      })}
                    </dd>
                    {self && !self.isZero() ? (
                      <div className="self">
                        {t('stats.reviewed.self', {
                          hours: formatHours(self),
                          pct: formatPercent(r.self_review_pct),
                        })}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </dl>
          </section>
        </aside>
      </div>
    </div>
  );
}
