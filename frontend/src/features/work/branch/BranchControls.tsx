/**
 * FE-029 · кнопка «Отметить «Готово»» в строке ветки (11.4 №7, BR-BR-01) и клетка «Проверено»
 * (11.4 №12, FR-REV-01, FR-REV-04; DESIGN.md 9.5).
 */
import { Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import type { BranchStatus } from '../../../shared/calc';
import type { BranchReadiness } from './branch';

/** «Готово · 2 открытых вопроса» рядом с плашкой статуса, кнопка «Отметить «Готово»» у черновика. */
export function BranchControls({
  status,
  readiness,
  canDone,
  busy,
  onDone,
}: {
  status: BranchStatus | undefined;
  readiness: BranchReadiness;
  canDone: boolean;
  busy: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  if (status === 'done')
    return readiness.open ? (
      <span className="branch-open">· {t('branch.openQuestions', { count: readiness.open })}</span>
    ) : null;
  if (status !== 'draft' || !canDone) return null;
  const blocked = readiness.empty + readiness.invalid > 0;
  const why = [
    readiness.empty ? t('branch.empty', { count: readiness.empty }) : null,
    readiness.invalid ? t('branch.invalid', { count: readiness.invalid }) : null,
  ]
    .filter(Boolean)
    .join(t('filters.and'));
  const button = (
    <button
      type="button"
      className="btn-sm done-btn"
      disabled={blocked || busy}
      aria-disabled={blocked || busy}
      {...(blocked ? { 'aria-description': t('branch.notReady', { why }) } : {})}
      onClick={onDone}
    >
      {t('branch.markDone')}
    </button>
  );
  if (!blocked) return button;
  // у неактивной кнопки подсказка на обёртке: disabled-кнопка не получает наведение
  return (
    <Tooltip label={t('branch.notReady', { why })} withinPortal>
      <span className="done-wrap" tabIndex={0}>
        {button}
      </span>
    </Tooltip>
  );
}

/** Клетка ✓: ✓ — проверено, ◐ — самопроверка; ревьюер и модератор ставят и снимают отметку. */
export function ReviewCell({
  title,
  reviewed,
  self,
  canReview,
  busy,
  onToggle,
}: {
  title: string;
  reviewed: boolean;
  self: boolean;
  canReview: boolean;
  busy: boolean;
  onToggle: (reviewed: boolean) => void;
}) {
  const { t } = useTranslation();
  const mark = reviewed ? (
    self ? (
      <span className="half" title={t('tree.selfReview')} aria-hidden="true" />
    ) : (
      <span className="ok-mark" aria-hidden="true">
        ✓
      </span>
    )
  ) : null;
  const state = reviewed ? (self ? t('tree.selfReview') : t('tree.reviewed')) : null;
  if (!canReview)
    return (
      <div className="td rv" role="cell">
        {reviewed ? (
          self ? (
            <span className="half" title={t('tree.selfReview')} aria-label={t('tree.selfReview')} />
          ) : (
            <span className="ok-mark" aria-label={t('tree.reviewed')}>
              ✓
            </span>
          )
        ) : null}
      </div>
    );
  return (
    <div className="td rv" role="cell">
      <button
        type="button"
        className={reviewed ? 'rv-btn on' : 'rv-btn'}
        aria-pressed={reviewed}
        aria-label={t(reviewed ? 'branch.unreview' : 'branch.review', { name: title })}
        title={state ?? t('branch.reviewHint')}
        disabled={busy}
        onClick={() => onToggle(!reviewed)}
      >
        {mark ?? (
          <span className="rv-ghost" aria-hidden="true">
            ✓
          </span>
        )}
      </button>
    </div>
  );
}
