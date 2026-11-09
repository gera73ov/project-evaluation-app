/**
 * FE-040, FE-042 · контрольные соотношения (6.6, 11.8 №9, 11.10 №1): шкала, зелёная пунктирная
 * зона нормы и цветная полоса факта; ниже или выше нормы — плашка с разницей в п.п.
 */
import { useQuery } from '@tanstack/react-query';
import Decimal from 'decimal.js';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatNumber, formatPercent } from '../../../shared/format/number';
import { ratioScale } from './readiness';

type Stats = components['schemas']['Stats'];
type Ratio = components['schemas']['Ratio'];

/** Название соотношения из справочника: «QA к (Бэкенд + Фронтенд)». */
export function useRatioName(names: ReadonlyMap<string, string>) {
  const { t } = useTranslation();
  const ratios = useQuery({
    queryKey: ['dict', 'ratios'],
    queryFn: () => call(() => api.GET('/admin/ratios')),
    select: (data) => data.items as Ratio[],
    staleTime: 10 * 60_000,
  });
  return (ratioId: string) => {
    const r = ratios.data?.find((x) => x.id === ratioId);
    if (!r) return t('stats.ratios.unknown');
    const b = r.disciplines_b.map((id) => names.get(id) ?? '?');
    return `${names.get(r.discipline_a_id) ?? '?'} ${t('stats.ratios.to')} (${b.join(' + ')})`;
  };
}

export function RatioList({ ratios, name }: { ratios: Stats['ratios']; name: (ratioId: string) => string }) {
  const { t } = useTranslation();
  return (
    <>
      {ratios.length ? null : <p className="card-hint">{t('stats.ratios.empty')}</p>}
      {ratios.map((r) => {
        const min = Number(r.min_pct);
        const max = Number(r.max_pct);
        const scale = ratioScale(max);
        const pct = r.pct === null ? null : Number(r.pct);
        const gap =
          r.verdict === 'below' && pct !== null
            ? new Decimal(min).minus(pct)
            : r.verdict === 'above' && pct !== null
              ? new Decimal(pct).minus(max)
              : null;
        return (
          <div key={r.ratio_id} className="ratio">
            <div className="ratio-head">
              <span>{name(r.ratio_id)}</span>
              <b className={r.verdict === 'ok' ? 'ok' : 'warn'}>{pct === null ? '—' : formatPercent(String(pct))}</b>
            </div>
            <div className="ratio-bar" aria-hidden="true">
              <i
                className={r.verdict === 'ok' ? 'ok' : 'warn'}
                style={{ width: `${Math.min(100, ((pct ?? 0) / scale) * 100)}%` }}
              />
              <em style={{ left: `${(min / scale) * 100}%`, width: `${((max - min) / scale) * 100}%` }} />
            </div>
            <div className="ratio-axis">
              <span>0%</span>
              <span>{t('stats.ratios.norm', { min: formatPercent(r.min_pct), max: formatPercent(r.max_pct) })}</span>
              <span>{scale}%</span>
            </div>
            {gap ? (
              <span className="pill warn">
                ⚠ {t(`stats.ratios.${r.verdict ?? 'below'}`, { pp: formatNumber(gap.abs(), 0) })}
              </span>
            ) : null}
          </div>
        );
      })}
    </>
  );
}
