/**
 * FE-041 · график «Динамика итога» (11.9 №4, DESIGN.md 7.5): собственный SVG без библиотеки.
 * Сетка — горизонтальные линии, линия E — `--accent` 2,5 px, P80 — `--warn` 2 px, последние точки —
 * круги; снимки — вертикальный пунктир `4 3` с подписью «📷 …». У каждой точки подсказка с датой и
 * значениями; для экранных дикторов те же данные — в скрытой таблице.
 */
import { useTranslation } from 'react-i18next';

import { formatDate } from '../../../shared/format/date';
import { niceScale } from './totals';

export interface Series {
  key: string;
  label: string;
  className: string;
  values: (number | null)[];
}

export interface Marker {
  id: string;
  date: string;
  label: string;
}

const W = 560;
const H = 250;
const PAD = { left: 46, right: 14, top: 26, bottom: 30 };

export function DynamicsChart({
  dates,
  series,
  markers,
  format,
  title,
}: {
  dates: readonly string[];
  series: readonly Series[];
  markers: readonly Marker[];
  format: (value: number) => string;
  title: string;
}) {
  const { t } = useTranslation();
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const { top, step } = niceScale(Math.max(0, ...all));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (dates.length > 1 ? (i / (dates.length - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + innerH - (v / top) * innerH;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(v);
  const day = (d: string) => formatDate(`${d}T12:00:00Z`, 'UTC', true);
  const path = (values: (number | null)[]) =>
    values
      .map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`))
      .filter(Boolean)
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${p}`)
      .join(' ');

  return (
    <figure className="dyn">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {ticks.map((v) => (
          <g key={v}>
            <line className="dyn-grid" x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
            <text className="dyn-axis" x={PAD.left - 8} y={y(v) + 4} textAnchor="end">
              {format(v)}
            </text>
          </g>
        ))}
        {dates.map((d, i) => (
          <text key={d} className="dyn-axis" x={x(i)} y={H - 8} textAnchor="middle">
            {day(d)}
          </text>
        ))}
        {markers.map((m, n) => {
          const i = dates.indexOf(m.date);
          if (i < 0) return null;
          const labelY = PAD.top - 10 + (n % 2) * 16;
          return (
            <g key={m.id} className="dyn-snap">
              <line x1={x(i)} x2={x(i)} y1={PAD.top - 4} y2={PAD.top + innerH} />
              <text x={Math.min(x(i), W - PAD.right - 4)} y={labelY} textAnchor="end">
                📷 {m.label}
              </text>
            </g>
          );
        })}
        {series.map((s) => (
          <g key={s.key} className={`dyn-line ${s.className}`}>
            <path d={path(s.values)} fill="none" />
            {s.values.map((v, i) =>
              v === null ? null : (
                <circle
                  key={dates.at(i)}
                  cx={x(i)}
                  cy={y(v)}
                  r={i === s.values.length - 1 ? 3.5 : 6}
                  className={i === s.values.length - 1 ? 'last' : 'hit'}
                >
                  <title>{`${day(dates.at(i) ?? '')}: ${s.label} ${format(v)}`}</title>
                </circle>
              ),
            )}
          </g>
        ))}
      </svg>
      <figcaption className="dyn-legend">
        {series.map((s) => (
          <span key={s.key}>
            <i className={s.className} aria-hidden="true" /> {s.label}
          </span>
        ))}
        <span>{t('stats.dynamics.legend')}</span>
      </figcaption>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th>{t('stats.dynamics.date')}</th>
            {series.map((s) => (
              <th key={s.key}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((d, i) => (
            <tr key={d}>
              <td>{day(d)}</td>
              {series.map((s) => {
                const v = s.values.at(i);
                return <td key={s.key}>{v === null || v === undefined ? '—' : format(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
