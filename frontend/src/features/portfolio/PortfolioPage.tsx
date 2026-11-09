/**
 * FE-050 · портфель руководителя пресейла (SPEC 11.13 №1–7, FR-PORT-01…03; DESIGN.md 10.12).
 *
 * Фильтры (период по дате создания, статус, результат, модератор, поиск) → реестр
 * `GET /portfolio/projects`; показатели — `GET /portfolio/summary` за период. В контракте сводка
 * зависит только от периода, поэтому остальные фильтры действуют на реестр. Полосы по месяцам
 * и «договор / в КП» считаются по реестру периода. «⇩ Excel» — задание выгрузки
 * `POST /portfolio/export`, затем файл. Все запросы портфеля закрыты вторым фактором
 * (x-totp-gate): на 403 TOTP_REQUIRED — ввод кода и повтор.
 */
import { Button, Popover, Select, TextInput } from '@mantine/core';
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link, useNavigate } from '../../app/router';
import type { Me } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call, errorMessage } from '../../shared/api/problem';
import { formatDate } from '../../shared/format/date';
import { formatHours, formatMillions, formatMoney, formatNumber, formatPercent } from '../../shared/format/number';
import { formatWhen } from '../../shared/format/relative';
import { EmptyState } from '../../shared/ui/EmptyState';
import { MoneyGuard, isTotpRequired } from '../../shared/ui/MoneyGuard';
import { StatusBadge } from '../../shared/ui/StatusBadge';
import { StepUpModal } from '../../shared/ui/StepUpModal';
import {
  contractRatios,
  defaultPeriod,
  joinState,
  kpis,
  monthBars,
  monthName,
  type Period,
  type PortfolioItem,
  type PortfolioSummary,
} from './portfolio';

type ProjectStatus = components['schemas']['ProjectStatus'];
type Outcome = components['schemas']['Outcome'];

const STATUSES: readonly ProjectStatus[] = ['preparation', 'estimation', 'consolidation', 'completed', 'archived'];
const OUTCOMES: readonly Outcome[] = ['unknown', 'won', 'lost', 'cancelled'];
const OUTCOME_TONE = new Map<Outcome, string>([
  ['unknown', 'gray'],
  ['won', 'ok'],
  ['lost', 'bad'],
  ['cancelled', 'gray'],
]);
const RATIOS_SHOWN = 4;
const SEARCH_MIN = 2;

interface Filters {
  status: ProjectStatus | null;
  outcome: Outcome | null;
  moderator: string | null;
  q: string;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

const periodQuery = (p: Period) => ({ from: p.from, to: p.to });

/** Реестр за период без прочих фильтров: модераторы для фильтра, итоги месяцев, «договор / в КП». */
function usePeriodItems(period: Period) {
  return useQuery({
    queryKey: ['portfolio', 'projects', period, 'all'],
    queryFn: () =>
      call(() => api.GET('/portfolio/projects', { params: { query: { ...periodQuery(period), limit: 200 } } })),
    select: (data) => data.items as PortfolioItem[],
    retry: false,
  });
}

/** Выгрузка: задание → ожидание готовности → файл с именем из задания. */
async function exportExcel(period: Period): Promise<void> {
  let job = await call(() => api.POST('/portfolio/export', { body: periodQuery(period) }));
  for (let attempt = 0; job.status !== 'ready' && attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const id = job.id;
    job = await call(() => api.GET('/exports/{id}', { params: { path: { id } } }));
  }
  if (job.status !== 'ready') throw new Error('export timeout');
  const id = job.id;
  const blob = await call(() => api.GET('/exports/{id}/download', { params: { path: { id } }, parseAs: 'blob' }));
  const url = URL.createObjectURL(blob as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = job.file_name ?? 'portfolio.xlsx';
  a.click();
  URL.revokeObjectURL(url);
}

export function PortfolioPage({ me }: { me: Me }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const timeZone = me.timezone ?? undefined;
  const [period, setPeriod] = useState<Period>(() => defaultPeriod(new Date()));
  const [filters, setFilters] = useState<Filters>({ status: null, outcome: null, moderator: null, q: '' });
  const q = useDebounced(filters.q.trim(), 300);
  const search = q.length >= SEARCH_MIN ? q : '';
  const [stepUp, setStepUp] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const summary = useQuery({
    queryKey: ['portfolio', 'summary', period],
    queryFn: () => call(() => api.GET('/portfolio/summary', { params: { query: periodQuery(period) } })),
    select: (data) => data as PortfolioSummary,
    retry: false,
  });
  const periodItems = usePeriodItems(period);
  const registry = useInfiniteQuery({
    queryKey: ['portfolio', 'projects', period, filters.status, filters.outcome, filters.moderator, search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(() =>
        api.GET('/portfolio/projects', {
          params: {
            query: {
              ...periodQuery(period),
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
              ...(filters.status ? { status: filters.status } : {}),
              ...(filters.outcome ? { outcome: filters.outcome } : {}),
              ...(filters.moderator ? { moderator_id: filters.moderator } : {}),
              ...(search ? { q: search } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
    // при смене фильтра реестр не мигает пустым
    placeholderData: keepPreviousData,
    retry: false,
  });
  const items = useMemo(
    () => (registry.data?.pages.flatMap((page) => page.items) ?? []) as PortfolioItem[],
    [registry.data],
  );

  const moderators = useMemo(() => {
    const byId = new Map<string, string>();
    for (const item of periodItems.data ?? []) for (const m of item.moderators) byId.set(m.id, m.full_name);
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1], 'ru'));
  }, [periodItems.data]);

  const exporting = useMutation({
    mutationFn: () => exportExcel(period),
    onError: (error) => {
      if (isTotpRequired(error)) setStepUp(true);
    },
  });

  const join = useMutation({
    mutationFn: (item: PortfolioItem) =>
      call(() => api.POST('/projects/{id}/join-as-moderator', { params: { path: { id: item.id } } })),
    onSuccess: (_data, item) => {
      setNotice(t('portfolio.joined', { name: item.name }));
      void client.invalidateQueries({ queryKey: ['portfolio'] });
    },
  });

  const gateError = [summary.error, registry.error, periodItems.error].find(isTotpRequired) ?? null;
  const otherError = [summary.error, registry.error].find((e) => e && !isTotpRequired(e)) ?? null;
  const filtered = filters.status !== null || filters.outcome !== null || filters.moderator !== null || search !== '';

  return (
    <div className="portfolio">
      <div className="pf-tools">
        <PeriodPicker period={period} timeZone={timeZone} onChange={setPeriod} />
        <Select
          className="pf-filter"
          aria-label={t('portfolio.filter.status')}
          allowDeselect={false}
          value={filters.status ?? 'all'}
          data={[
            { value: 'all', label: t('portfolio.filter.statusAll') },
            ...STATUSES.map((s) => ({
              value: s,
              label: `${t('portfolio.filter.statusOne')}${t(`status.project.${s}`)}`,
            })),
          ]}
          onChange={(v) => setFilters({ ...filters, status: v && v !== 'all' ? (v as ProjectStatus) : null })}
        />
        <Select
          className="pf-filter"
          aria-label={t('portfolio.filter.outcome')}
          allowDeselect={false}
          value={filters.outcome ?? 'all'}
          data={[
            { value: 'all', label: t('portfolio.filter.outcomeAll') },
            ...OUTCOMES.map((o) => ({
              value: o,
              label: `${t('portfolio.filter.outcomeOne')}${t(`outcome.value.${o}`)}`,
            })),
          ]}
          onChange={(v) => setFilters({ ...filters, outcome: v && v !== 'all' ? (v as Outcome) : null })}
        />
        <Select
          className="pf-filter"
          aria-label={t('portfolio.filter.moderator')}
          allowDeselect={false}
          value={filters.moderator ?? 'all'}
          data={[
            { value: 'all', label: t('portfolio.filter.moderatorAll') },
            ...moderators.map(([id, name]) => ({ value: id, label: `${t('portfolio.filter.moderatorOne')}${name}` })),
          ]}
          onChange={(v) => setFilters({ ...filters, moderator: v && v !== 'all' ? v : null })}
        />
        <TextInput
          className="pf-search"
          aria-label={t('portfolio.filter.search')}
          placeholder={t('portfolio.filter.search')}
          leftSection={<span aria-hidden="true">🔍</span>}
          value={filters.q}
          maxLength={200}
          onChange={(e) => setFilters({ ...filters, q: e.currentTarget.value })}
        />
        <span className="sp" />
        <Button variant="default" loading={exporting.isPending} onClick={() => exporting.mutate()}>
          ⇩ {t('portfolio.excel')}
        </Button>
      </div>
      {exporting.error && !isTotpRequired(exporting.error) ? (
        <div className="err pf-msg" role="alert">
          {exporting.error instanceof Error && exporting.error.message === 'export timeout'
            ? t('portfolio.exportTimeout')
            : errorMessage(exporting.error)}
        </div>
      ) : null}
      <StepUpModal
        opened={stepUp}
        totpOnly
        onClose={() => setStepUp(false)}
        onSuccess={() => {
          setStepUp(false);
          exporting.mutate();
        }}
      />

      <MoneyGuard
        error={gateError}
        totpEnabled={me.totp_enabled}
        onUnlocked={() => void client.invalidateQueries({ queryKey: ['portfolio'] })}
        onEnroll={() => navigate('/profile')}
      >
        {otherError ? (
          <div className="err pf-msg" role="alert">
            {errorMessage(otherError)}
          </div>
        ) : null}
        {summary.data ? <Kpis summary={summary.data} /> : null}
        {summary.data ? (
          <div className="pf-charts">
            <MonthsCard summary={summary.data} items={periodItems.data ?? []} />
            <LossCard summary={summary.data} />
            <RatiosCard items={periodItems.data ?? []} />
          </div>
        ) : null}

        <div className="pf-main">
          {notice ? (
            <div className="pf-notice" role="status">
              {notice}
            </div>
          ) : null}
          {join.error ? (
            <div className="err pf-msg" role="alert">
              {errorMessage(join.error)}
            </div>
          ) : null}
          {registry.isSuccess && items.length === 0 ? (
            <EmptyState title={filtered ? t('portfolio.notFound') : t('portfolio.empty')} />
          ) : null}
          {items.length > 0 ? (
            <table className="t pf-table">
              <thead>
                <tr>
                  <th>{t('portfolio.col.project')}</th>
                  <th>{t('portfolio.col.team')}</th>
                  <th>{t('portfolio.col.status')}</th>
                  <th className="r">{t('portfolio.col.hours')}</th>
                  <th className="r m">🔒 {t('portfolio.col.quoteCur')}</th>
                  <th className="r m">🔒 {t('portfolio.col.quoteRub')}</th>
                  <th>{t('portfolio.col.outcome')}</th>
                  <th className="r m">🔒 {t('portfolio.col.contract')}</th>
                  <th>{t('portfolio.col.updated')}</th>
                  <th>
                    <span className="sr-only">{t('portfolio.col.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <RegistryRow
                    key={item.id}
                    item={item}
                    meId={me.id}
                    timeZone={timeZone}
                    joining={join.isPending && join.variables.id === item.id}
                    onJoin={() => {
                      setNotice(null);
                      join.mutate(item);
                    }}
                  />
                ))}
              </tbody>
            </table>
          ) : null}
          {registry.hasNextPage ? (
            <Button
              variant="default"
              size="xs"
              loading={registry.isFetchingNextPage}
              onClick={() => void registry.fetchNextPage()}
            >
              {t('portfolio.more')}
            </Button>
          ) : null}
          <p className="caption">{t('portfolio.caption')}</p>
        </div>
      </MoneyGuard>
    </div>
  );
}

function PeriodPicker({
  period,
  timeZone,
  onChange,
}: {
  period: Period;
  timeZone: string | undefined;
  onChange: (p: Period) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(period);
  const valid = draft.from !== '' && draft.to !== '' && draft.from <= draft.to;
  const label = `${formatDate(`${period.from}T12:00:00Z`, timeZone, true)} – ${formatDate(`${period.to}T12:00:00Z`, timeZone)}`;
  return (
    <Popover
      opened={open}
      onChange={setOpen}
      position="bottom-start"
      shadow="md"
      onOpen={() => setDraft(period)}
      trapFocus
    >
      <Popover.Target>
        <Button variant="default" className="pf-period" onClick={() => setOpen((o) => !o)}>
          {t('portfolio.period', { range: label })} ▾
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <div className="pf-period-form">
          <TextInput
            type="date"
            label={t('portfolio.periodFrom')}
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.currentTarget.value })}
          />
          <TextInput
            type="date"
            label={t('portfolio.periodTo')}
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.currentTarget.value })}
          />
          <p className="pf-hint">{t('portfolio.periodHint')}</p>
          <Button
            size="xs"
            disabled={!valid}
            onClick={() => {
              onChange(draft);
              setOpen(false);
            }}
          >
            {t('portfolio.apply')}
          </Button>
        </div>
      </Popover.Dropdown>
    </Popover>
  );
}

function Kpis({ summary }: { summary: PortfolioSummary }) {
  const { t } = useTranslation();
  const k = kpis(summary);
  return (
    <div className="pf-kpis">
      <div className="kpi">
        <div className="lbl">{t('portfolio.kpi.total')}</div>
        <div className="v">{k.total}</div>
        <div className="d">
          {t('portfolio.kpi.totalHint', { inWork: k.inWork, done: k.completed, archived: k.archived })}
        </div>
      </div>
      <div className="kpi">
        <div className="lbl">{t('portfolio.kpi.won')}</div>
        <div className="v">{t('portfolio.kpi.wonValue', { won: k.won, decided: k.decided })}</div>
        <div className="d">
          {t('portfolio.kpi.wonHint', {
            pct: formatPercent(k.wonPct),
            cancelled: t('portfolio.kpi.cancelled', { count: k.cancelled }),
            unknown: k.unknown,
          })}
        </div>
      </div>
      <div className="kpi m">
        <div className="lbl">🔒 {t('portfolio.kpi.moneyShare')}</div>
        <div className="v">{formatPercent(k.moneyPct)}</div>
        <div className="d">
          {t('portfolio.kpi.moneyShareHint', { won: formatMillions(k.wonRub), all: formatMillions(k.decidedRub) })}
        </div>
      </div>
      <div className="kpi m">
        <div className="lbl">🔒 {t('portfolio.kpi.contract')}</div>
        <div className="v">{k.contractRatio === null ? t('common.empty') : formatNumber(k.contractRatio, 2)}</div>
        <div className="d">
          {k.discountPct === null
            ? t('portfolio.kpi.contractNone')
            : t('portfolio.kpi.contractHint', { pct: formatPercent(k.discountPct) })}
        </div>
      </div>
      <div className="kpi m">
        <div className="lbl">🔒 {t('portfolio.kpi.inWork')}</div>
        <div className="v">{formatMillions(k.inWorkRub)}</div>
        <div className="d">{t('portfolio.kpi.inWorkHint', { count: k.inWork })}</div>
      </div>
      {k.firstSnapshotDays !== null ? (
        <div className="pf-plate">
          {t('portfolio.kpi.firstSnapshot', { days: formatNumber(k.firstSnapshotDays, 1) })}
        </div>
      ) : null}
    </div>
  );
}

const pct = (part: number, whole: number) => `${whole ? (part / whole) * 100 : 0}%`;

function MonthsCard({ summary, items }: { summary: PortfolioSummary; items: readonly PortfolioItem[] }) {
  const { t } = useTranslation();
  const bars = monthBars(summary, items);
  return (
    <section className="pf-card" aria-label={t('portfolio.months.title')}>
      <h4>{t('portfolio.months.title')}</h4>
      {bars.length === 0 ? <p className="pf-hint">{t('portfolio.months.empty')}</p> : null}
      {bars.map((b) => (
        <div key={b.month} className="hb">
          <span>{monthName(b.month)}</span>
          <div
            className="stack"
            role="img"
            aria-label={t('portfolio.months.bar', { won: b.won, lost: b.lost, none: b.none })}
          >
            <i className="won" style={{ width: pct(b.won, b.total) }} />
            <i className="lost" style={{ width: pct(b.lost, b.total) }} />
            <i className="none" style={{ width: pct(b.none, b.total) }} />
          </div>
          <span>{b.total}</span>
        </div>
      ))}
      <div className="pf-legend">
        <span>
          <b className="won">■</b> {t('outcome.value.won')}
        </span>
        <span>
          <b className="lost">■</b> {t('outcome.value.lost')}
        </span>
        <span>
          <b className="none">■</b> {t('portfolio.months.none')}
        </span>
        <span>· {t('portfolio.months.byCreated')}</span>
      </div>
    </section>
  );
}

function LossCard({ summary }: { summary: PortfolioSummary }) {
  const { t } = useTranslation();
  const [shown, setShown] = useState<string | null>(null);
  const max = Math.max(1, ...summary.loss_reasons.map((r) => r.count));
  const texts = summary.loss_reasons.find((r) => (r.loss_reason_id ?? r.name) === shown)?.texts ?? [];
  return (
    <section className="pf-card" aria-label={t('portfolio.loss.title')}>
      <h4>{t('portfolio.loss.title')}</h4>
      {summary.loss_reasons.length === 0 ? <p className="pf-hint">{t('portfolio.loss.empty')}</p> : null}
      {summary.loss_reasons.map((r) => {
        const key = r.loss_reason_id ?? r.name;
        return (
          <div key={key} className="hb">
            {r.texts.length > 0 ? (
              <button
                type="button"
                className="link"
                aria-expanded={shown === key}
                onClick={() => setShown(shown === key ? null : key)}
              >
                {r.name}
              </button>
            ) : (
              <span>{r.name}</span>
            )}
            <div className="b lost" style={{ width: pct(r.count, max) }} />
            <span>{r.count}</span>
          </div>
        );
      })}
      {texts.length > 0 ? (
        <ul className="pf-texts">
          {texts.map((text, i) => (
            <li key={i}>«{text}»</li>
          ))}
        </ul>
      ) : null}
      <p className="pf-hint">{t('portfolio.loss.hint')}</p>
    </section>
  );
}

function RatiosCard({ items }: { items: readonly PortfolioItem[] }) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  const ratios = contractRatios(items);
  const shown = all ? ratios : ratios.slice(0, RATIOS_SHOWN);
  const max = Math.max(1, ...ratios.map((r) => Number(r.ratio)));
  return (
    <section className="pf-card m" aria-label={t('portfolio.ratios.title')}>
      <h4 className="money">
        🔒 {t('portfolio.ratios.title')}{' '}
        {ratios.length > RATIOS_SHOWN ? (
          <button type="button" className="link pf-sub" onClick={() => setAll(!all)}>
            {all
              ? t('portfolio.ratios.collapse')
              : t('portfolio.ratios.some', { shown: RATIOS_SHOWN, count: ratios.length })}
          </button>
        ) : null}
      </h4>
      {ratios.length === 0 ? <p className="pf-hint">{t('portfolio.ratios.empty')}</p> : null}
      {shown.map((r) => (
        <div key={r.id} className="hb">
          <span>{r.name}</span>
          <div className="b money" style={{ width: pct(Number(r.ratio), max) }} />
          <span>{formatNumber(r.ratio, 2)}</span>
        </div>
      ))}
      <p className="pf-hint">{t('portfolio.ratios.hint')}</p>
    </section>
  );
}

function RegistryRow({
  item,
  meId,
  timeZone,
  joining,
  onJoin,
}: {
  item: PortfolioItem;
  meId: string;
  timeZone: string | undefined;
  joining: boolean;
  onJoin: () => void;
}) {
  const { t } = useTranslation();
  const money = item.money;
  const join = joinState(item, meId);
  const people = (list: PortfolioItem['moderators']) =>
    list.length ? list.map((u) => u.full_name).join(', ') : t('common.empty');
  return (
    <tr className={item.no_moderator ? 'muted' : undefined}>
      <td>
        <b>{item.name}</b>
        <div className="sub">{item.customer}</div>
      </td>
      <td>
        {item.no_moderator ? <span className="pill bad">{t('portfolio.noModerator')}</span> : people(item.moderators)}
        {' · '}
        {people(item.presales)}
      </td>
      <td>
        <StatusBadge kind="project" status={item.status} />
      </td>
      <td className="r">
        {item.quote_hours === null ? (
          t('common.empty')
        ) : (
          <>
            {formatHours(item.quote_hours)} <span className="figure">{t(`home.figure.${item.quote_figure}`)}</span>
          </>
        )}
      </td>
      <td className="r m">
        {money.rates_missing ? t('portfolio.ratesMissing') : formatMoney(money.quote_cur, money.currency)}
      </td>
      <td className="r m">{money.quote_rub === null ? t('common.empty') : formatNumber(money.quote_rub, 0)}</td>
      <td>
        <span className={`pill ${OUTCOME_TONE.get(item.outcome) ?? 'gray'}`}>{t(`outcome.value.${item.outcome}`)}</span>
      </td>
      <td className="r m">
        {money.contract_amount === null ? t('common.empty') : formatMoney(money.contract_amount, money.currency)}
      </td>
      <td>{formatWhen(item.updated_at, { timeZone })}</td>
      <td className="r pf-actions">
        <Link to={`/projects/${item.id}`} className="btn-sm">
          {t('portfolio.open')}
        </Link>
        {join === 'hidden' ? null : join === 'archived' ? (
          // неактивная кнопка не показывает title — подсказку держит обёртка (FR-PORT-03)
          <span className="pf-join-off" title={t('portfolio.restoreFirst')}>
            <button type="button" className="btn-sm" disabled aria-label={`${t('portfolio.join')}: ${item.name}`}>
              {t('portfolio.join')}
            </button>
            <span className="sr-only">{t('portfolio.restoreFirst')}</span>
          </span>
        ) : (
          <button
            type="button"
            className="btn-sm"
            disabled={joining}
            aria-label={`${t('portfolio.join')}: ${item.name}`}
            onClick={onJoin}
          >
            {t('portfolio.join')}
          </button>
        )}
      </td>
    </tr>
  );
}
