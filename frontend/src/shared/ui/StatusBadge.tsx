/**
 * FE-004 · плашка статуса (DESIGN.md 7.1, 7.2): цвет, символ и текст выбираются по типу и значению.
 * У статусов ветки есть символ — цвет не единственный носитель смысла (FR-UI-04, D-05); у статуса
 * проекта носитель смысла — само слово.
 */
import { useTranslation } from 'react-i18next';

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'gray' | 'acc' | 'money';

interface Look {
  tone: BadgeTone;
  symbol: string | null;
}

const LOOKS = new Map<string, Look>([
  ['project/preparation', { tone: 'gray', symbol: null }],
  ['project/estimation', { tone: 'acc', symbol: null }],
  ['project/consolidation', { tone: 'warn', symbol: null }],
  ['project/completed', { tone: 'ok', symbol: null }],
  ['project/archived', { tone: 'gray', symbol: null }],
  ['branch/not_started', { tone: 'gray', symbol: '○' }],
  ['branch/draft', { tone: 'warn', symbol: '✎' }],
  ['branch/done', { tone: 'ok', symbol: '✓' }],
  ['branch/not_needed', { tone: 'gray', symbol: '▨' }],
]);

export function StatusBadge({ kind, status }: { kind: 'branch' | 'project'; status: string }) {
  const { t } = useTranslation();
  const look = LOOKS.get(`${kind}/${status}`) ?? { tone: 'gray', symbol: null };
  const label = t(`status.${kind}.${status}`, { defaultValue: status });
  return (
    <span className={`pill ${look.tone}`}>
      {look.symbol ? <span aria-hidden="true">{look.symbol}</span> : null}
      {label}
    </span>
  );
}
