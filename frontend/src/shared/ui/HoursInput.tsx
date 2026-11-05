/**
 * FE-004 · поле часов O/R/P (FR-TREE-21, BR-CALC-03): запятая или точка, шаг 0,5 по ROUND_HALF_UP
 * с подсказкой «округлено до …», диапазон 0–99 999,5. Нормализует FE-002 `normalizeHours`.
 */
import { TextInput } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { CalcInputError, normalizeHours } from '../calc/leaf';
import { formatHoursInput } from '../format/number';

export interface HoursInputProps {
  label: string;
  /** Каноническая строка API ("12.5") или null — пусто. */
  value: string | null;
  onCommit: (value: string | null) => void;
  disabled?: boolean | undefined;
}

export function HoursInput({ label, value, onCommit, disabled }: HoursInputProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(formatHoursInput(value));
  const [hint, setHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function commit() {
    if (draft.trim() === '') {
      setError(null);
      setHint(null);
      onCommit(null);
      return;
    }
    try {
      const result = normalizeHours(draft);
      setError(null);
      setHint(result.rounded ? t('hours.rounded', { value: formatHoursInput(result.text) }) : null);
      setDraft(formatHoursInput(result.text));
      onCommit(result.text);
    } catch (e) {
      const code = e instanceof CalcInputError ? e.code : 'VALIDATION_FAILED';
      setHint(null);
      setError(code === 'VALUE_OUT_OF_RANGE' ? t('hours.range') : t('hours.invalid'));
    }
  }

  return (
    <div>
      <TextInput
        label={label}
        value={draft}
        inputMode="decimal"
        disabled={disabled ?? false}
        error={error}
        onChange={(e) => setDraft(e.currentTarget.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
      />
      {hint ? (
        <div className="hours-hint" role="status">
          {hint}
        </div>
      ) : null}
    </div>
  );
}
