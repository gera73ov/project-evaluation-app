/**
 * FE-044 · сравнение со снимком (SPEC 11.12, FR-SNAP-03/04/05; DESIGN.md 10.11): выбор «что с чем»
 * (слева — текущее состояние или снимок, справа — снимок; ошибочные зачёркнуты, но выбираются),
 * сводка E и P80 «было → стало», денежные карточки только когда сервер прислал `money`, фильтры
 * видов изменения и «Параметры» с числами, таблица «было → стало (O–R–P × N)» с ΔE и «кто и когда
 * последним», строки параметров проекта (денежные — только с деньгами, их присылает сервер),
 * пояснение про пересчёт УП и «Экспорт сравнения в Excel». Контракт строк — CR-008.
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
import { formatHours, formatHoursInput, formatNumber, formatRate } from '../../shared/format/number';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useProject } from '../settings/useProject';
import { snapshotsKey } from '../snapshots/keys';
import {
  FILTERS,
  compareHref,
  countByFilter,
  deltaPct,
  deltaTone,
  forkOf,
  sidesOf,
  type Change,
  type DiffParam,
  type DiffRow,
  type Filter,
} from './compare';

type Snapshot = components['schemas']['Snapshot'];
type Diff = components['schemas']['Diff'];
type DiffMoney = components['schemas']['DiffMoney'];

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
  const [filter, setFilter] = useState<Filter | null>(null);
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
  const params = data?.params ?? [];
  const rows: DiffRow[] =
    filter === 'params' ? [] : (data?.rows ?? []).filter((r) => filter === null || r.change === filter);
  const paramRows: DiffParam[] = filter === null || filter === 'params' ? params : [];
  const counts = countByFilter(data?.rows ?? [], params);
  const when = (by: { full_name: string } | null, at: string | null) =>
    by ? `${by.full_name}${at ? ` · ${formatDateTime(at, undefined, true)}` : ''}` : '—';

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
      {data ? (
        <>
          <div className="cmp-cards">
            <SummaryCard
              label={t('compare.totalE')}
              before={data.base.totals.e}
              after={data.with.totals.e}
              delta={data.totals_delta.e}
              pct
            />
            <SummaryCard
              label={t('compare.totalP80')}
              before={data.base.totals.p80}
              after={data.with.totals.p80}
              delta={data.totals_delta.p80}
            />
            {data.money ? <MoneyCards money={data.money} /> : null}
          </div>
          <div className="chips cmp-chips" role="group" aria-label={t('compare.filter')}>
            {([null, ...FILTERS] as const).map((c) => (
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
            {rows.length + paramRows.length === 0 ? <p className="card-hint">{t('compare.empty')}</p> : null}
            {rows.length + paramRows.length > 0 ? (
              <table className="t cmp-table">
                <thead>
                  <tr>
                    <th>{t('compare.change')}</th>
                    <th>{t('compare.node')}</th>
                    <th>{t('compare.values')}</th>
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
                      <td>
                        <BeforeAfter before={forkOf(r.before)} after={forkOf(r.after)} />
                      </td>
                      <td className={`r num ${deltaTone(r.delta_e) ?? ''}`}>{signed(r.delta_e, 1)}</td>
                      <td>{when(r.last_changed_by, r.last_changed_at)}</td>
                    </tr>
                  ))}
                  {paramRows.map((r) => (
                    <tr
                      key={`${r.key}-${r.discipline_id ?? ''}-${r.phase_id ?? ''}`}
                      className={r.is_money ? 'cmp-param money' : 'cmp-param'}
                    >
                      <td>
                        <span className="pill money">
                          {t('compare.kind.param')}
                          {r.is_money ? ' 🔒' : ''}
                        </span>
                      </td>
                      <td>{r.label}</td>
                      <td>
                        <BeforeAfter before={paramValue(r, r.before, t)} after={paramValue(r, r.after, t)} />
                      </td>
                      <td className="r num">—</td>
                      <td>{when(r.last_changed_by, r.last_changed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="card-hint">
              {data.pm
                ? `${t('compare.pmNote', {
                    pct: formatHoursInput(data.pm.percent_after),
                    delta: signed(data.pm.delta_e, 1),
                  })} `
                : ''}
              {data.pm && data.pm.percent_before !== data.pm.percent_after
                ? `${t('compare.pmPercent', { before: formatHoursInput(data.pm.percent_before), after: formatNumber(data.pm.percent_after, 1) })} `
                : ''}
              {t('compare.byId')}
            </p>
          </section>
        </>
      ) : null}
    </div>
  );
}

/** «было» зачёркнуто, «—» — значения на этой стороне нет. */
function BeforeAfter({ before, after }: { before: string | null; after: string | null }) {
  return (
    <span className="cmp-ba">
      {before === null ? '—' : <s>{before}</s>} → {after ?? '—'}
    </span>
  );
}

/** Значение параметра для таблицы: курс и ставки — числом, флаги — словами, коды — как есть. */
function paramValue(r: DiffParam, value: string | null, t: (k: string) => string): string | null {
  if (value === null) return null;
  if (value === 'true' || value === 'false') return t(`compare.flag.${value}`);
  if (r.key === 'exchange_rate') return formatRate(value);
  if (r.key === 'pm_percent' || r.key === 'vat') return `${formatHoursInput(value)}%`;
  if (r.key === 'rate') return `${formatNumber(value, 0)} ₽/ч`;
  return value;
}

function MoneyCards({ money }: { money: DiffMoney }) {
  const { t } = useTranslation();
  const cur = money.with.currency;
  const label = t('compare.cur', { currency: cur });
  const rateChanged = money.base.exchange_rate !== money.with.exchange_rate;
  return (
    <>
      <section className="cmp-card money" aria-label={t('compare.rub')}>
        <div className="lbl">🔒 {t('compare.rub')}</div>
        <div className="val">
          {amount(money.base.total_rub)} → {amount(money.with.total_rub)}
        </div>
        <div className={`dl ${money.total_delta_rub ? (deltaTone(money.total_delta_rub) ?? '') : ''}`}>
          {money.total_delta_rub === null ? '—' : `${signed(money.total_delta_rub, 0)} ₽`}{' '}
          {money.rates_changed && money.rates_effect_rub !== null
            ? `(${t('compare.ratesEffect', { value: signed(money.rates_effect_rub, 0) })})`
            : `(${t('compare.ratesSame')})`}
        </div>
      </section>
      <section className="cmp-card money" aria-label={label}>
        <div className="lbl">🔒 {label}</div>
        <div className="val">
          {amount(money.base.total_cur)} → {amount(money.with.total_cur)}
        </div>
        <div className={`dl ${money.total_delta_cur ? (deltaTone(money.total_delta_cur) ?? '') : ''}`}>
          {money.total_delta_cur === null ? '—' : `${signed(money.total_delta_cur, 0)} ${cur}`}
          {rateChanged && money.exchange_effect_cur !== null
            ? `, ${t('compare.exchangeEffect', {
                before: formatNumber(money.base.exchange_rate, 1),
                after: formatNumber(money.with.exchange_rate, 1),
                value: signed(money.exchange_effect_cur, 0),
              })}`
            : ''}
        </div>
      </section>
    </>
  );
}

const amount = (v: string | null) => (v === null ? '—' : formatNumber(v, 0));

function SummaryCard({
  label,
  before,
  after,
  delta,
  pct = false,
}: {
  label: string;
  before: string;
  after: string;
  delta: string;
  pct?: boolean;
}) {
  const p = deltaPct(before, delta);
  return (
    <section className="cmp-card" aria-label={label}>
      <div className="lbl">{label}</div>
      <div className="val">
        {formatHours(before)} → {formatHours(after, { unit: true })}
      </div>
      <div className={`dl ${deltaTone(delta) ?? ''}`}>
        {signed(delta, 1)} ч{pct && p !== null ? ` (${p > 0 ? '+' : ''}${formatNumber(String(p), 1)}%)` : ''}
      </div>
    </section>
  );
}
