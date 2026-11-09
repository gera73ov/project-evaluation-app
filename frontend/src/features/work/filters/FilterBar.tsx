/**
 * FE-024 · полоса инструментов над деревом (FR-TREE-12, 11.4 №5–6, FR-REV-04; DESIGN.md 9.3, 6.3):
 * поиск, чипы-фильтры с числом строк, «Показать: до фаз / до дисциплин / всё раскрыть»,
 * предупреждение о неучтённых листьях (включает «Без оценки»).
 */
import { useTranslation } from 'react-i18next';

import { CHIPS, type FilterKey } from './filters';

export function FilterBar({
  query,
  onQuery,
  filters,
  onToggle,
  counts,
  moderator,
  unaccounted,
  onCollapse,
}: {
  query: string;
  onQuery: (value: string) => void;
  filters: ReadonlySet<FilterKey>;
  onToggle: (key: FilterKey) => void;
  counts: ReadonlyMap<FilterKey, number>;
  /** Чип «Самопроверка» — только у модератора (FR-REV-04). */
  moderator: boolean;
  unaccounted: { empty: number; invalid: number };
  onCollapse: (level: 'phases' | 'disciplines' | 'none') => void;
}) {
  const { t } = useTranslation();
  const chips = CHIPS.filter((key) => key !== 'selfReview' || moderator);
  // «Риски» включается кликом по счётчику в верхней полосе и показывается чипом, пока включён
  if (filters.has('risk')) chips.push('risk');
  const missing = unaccounted.empty + unaccounted.invalid;
  const kinds = [
    unaccounted.empty ? t('filters.empty', { count: unaccounted.empty }) : null,
    unaccounted.invalid ? t('filters.invalid', { count: unaccounted.invalid }) : null,
  ].filter(Boolean);

  return (
    <div className="tools" role="toolbar" aria-label={t('filters.label')}>
      <input
        type="search"
        className="tools-search"
        placeholder={`🔍 ${t('filters.search')}`}
        aria-label={t('filters.search')}
        value={query}
        onChange={(e) => onQuery(e.currentTarget.value)}
      />
      {chips.map((key) => {
        const on = filters.has(key);
        return (
          <button
            key={key}
            type="button"
            className={on ? 'chip sm on' : 'chip sm'}
            aria-pressed={on}
            onClick={() => onToggle(key)}
          >
            {on ? '✓ ' : ''}
            {t(`filters.chip.${key}`)}
            {key === 'mine' ? null : <span className="c">{counts.get(key) ?? 0}</span>}
          </button>
        );
      })}
      <span className="tools-show">
        <span className="k">{t('filters.show')}</span>
        <button type="button" className="btn-sm" onClick={() => onCollapse('phases')}>
          {t('filters.toPhases')}
        </button>
        <button type="button" className="btn-sm" onClick={() => onCollapse('disciplines')}>
          {t('filters.toDisciplines')}
        </button>
        <button type="button" className="btn-sm" onClick={() => onCollapse('none')}>
          {t('filters.expandAll')}
        </button>
      </span>
      {missing ? (
        <button
          type="button"
          className="tools-warn"
          onClick={() => filters.has('unestimated') || onToggle('unestimated')}
        >
          ⚠ {t('filters.unaccounted', { count: missing })}: {kinds.join(t('filters.and'))}
        </button>
      ) : null}
    </div>
  );
}
