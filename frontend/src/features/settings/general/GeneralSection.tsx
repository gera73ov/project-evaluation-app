/**
 * FE-012 · блок «Основное» и УП настроек проекта (SPEC 11.6 №2, №3, №10, №11; FR-PRJ-01,
 * BR-CALC-05, BR-MONEY-06, BR-PRJ-06; DESIGN.md 10.5).
 *
 * Каждое поле сохраняется при уходе фокуса (`PATCH /projects/{id}` одним полем), рядом на 2 с —
 * «✓ сохранено». Выключение фазы с оценками сервер отклоняет 409 CONFIRMATION_REQUIRED — диалог
 * и повтор с `confirm: true`. Сквозная фаза «Управление проектом» включена всегда. Без права
 * `project.settings.write` (эксперт) и без связи — только чтение.
 */
import { SegmentedControl, TextInput, Textarea } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import Decimal from 'decimal.js';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { asDecimalString } from '../../../shared/api/decimal';
import { call } from '../../../shared/api/problem';
import { formatDate } from '../../../shared/format/date';
import { formatHours, formatNumber } from '../../../shared/format/number';
import { AutoLinkText } from '../../../shared/ui/AutoLinkText';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { useProjectPatch, useTreeTotals, type Project, type ProjectPatch } from '../useProject';

type DetailLevel = components['schemas']['DetailLevel'];
type QuoteFigure = components['schemas']['QuoteFigure'];

const LEVELS: readonly DetailLevel[] = ['coarse', 'medium', 'detailed'];
const FIGURES: readonly QuoteFigure[] = ['e', 'p80', 'p90'];

/** «18», «18,5», «18.5» → каноническая строка; вне 0–50 или не кратно 0,5 — null. */
export function parsePercent(input: string): string | null {
  const text = input.replace(',', '.').replace('%', '').trim();
  const [whole = '', fraction, extra] = text.split('.');
  if (extra !== undefined || !/^\d{1,2}$/.test(whole) || (fraction !== undefined && !/^\d{1,2}$/.test(fraction))) return null;
  const value = new Decimal(text);
  if (value.lt(0) || value.gt(50) || !value.mul(2).isInteger()) return null;
  return value.toFixed(value.isInteger() ? 0 : 1);
}

/** «14» → 14; пусто → null; вне 1–260 или не целое — undefined (ошибка). */
export function parseWeeks(input: string): number | null | undefined {
  const text = input.trim();
  if (text === '') return null;
  if (!/^\d{1,3}$/.test(text)) return undefined;
  const value = Number(text);
  return value >= 1 && value <= 260 ? value : undefined;
}

function Row({ label, labelFor, children }: { label: string; labelFor?: string; children: ReactNode }) {
  return (
    <div className="set-row">
      {labelFor ? (
        <label className="set-label" htmlFor={labelFor}>
          {label}
        </label>
      ) : (
        <div className="set-label">{label}</div>
      )}
      <div className="set-field">{children}</div>
    </div>
  );
}

function Saved({ field, saved }: { field: string; saved: string | null }) {
  const { t } = useTranslation();
  return saved === field ? (
    <span className="saved" role="status">
      {t('settings.saved')}
    </span>
  ) : null;
}

/** Текстовое поле, которое сохраняется при уходе фокуса, если значение изменилось и прошло проверку. */
function BlurText({
  id,
  value,
  readOnly,
  validate,
  onCommit,
  multiline = false,
  placeholder,
  w,
}: {
  id: string;
  value: string;
  readOnly: boolean;
  validate: (draft: string) => string | null;
  onCommit: (draft: string) => void;
  multiline?: boolean;
  placeholder?: string;
  w?: number;
}) {
  const [draft, setDraft] = useState(value);
  const [base, setBase] = useState(value);
  const [error, setError] = useState<string | null>(null);
  // значение пришло с сервера (своё сохранение или правка коллеги) — показываем его
  if (value !== base) {
    setBase(value);
    setDraft(value);
  }
  const common = {
    id,
    value: draft,
    readOnly,
    error,
    placeholder,
    onChange: (e: { currentTarget: { value: string } }) => setDraft(e.currentTarget.value),
    onBlur: () => {
      if (draft === value) return setError(null);
      const problem = validate(draft);
      setError(problem);
      if (!problem) onCommit(draft);
    },
  };
  return multiline ? (
    <Textarea {...common} autosize minRows={1} maxRows={6} />
  ) : (
    <TextInput {...common} {...(w ? { w } : {})} />
  );
}

export function GeneralSection({ project, readOnly }: { project: Project; readOnly: boolean }) {
  const { t } = useTranslation();
  const { save, retryConfirmed, saved, error, confirm, cancelConfirm, busy } = useProjectPatch(project.id);
  const totals = useTreeTotals(project.id);
  const method = useQuery({
    queryKey: ['dict', 'method-settings'],
    queryFn: () => call(() => api.GET('/admin/method-settings')),
    staleTime: 10 * 60_000,
  });
  const commit = (field: string, patch: ProjectPatch) => save(field, patch);
  const enabled = project.phases.filter((p) => p.is_enabled);
  const figureNow = totals.data?.total;
  const threshold =
    project.detail_level === 'coarse' ? null : method.data?.large_leaf_hours[project.detail_level];
  const confirmPhase = confirm
    ? project.phases.find((p) => p.phase_id === confirm.patch.phases?.[0]?.phase_id)
    : undefined;

  return (
    <section className="sec set-sec" aria-labelledby="set-general">
      <h3 id="set-general">{t('settings.general.title')}</h3>
      <ErrorText error={error} />

      <Row label={t('settings.general.name')} labelFor="set-name">
        <BlurText
          id="set-name"
          value={project.name}
          readOnly={readOnly}
          validate={(v) => (v.trim().length < 3 || v.trim().length > 200 ? t('settings.general.errors.name') : null)}
          onCommit={(v) => commit('name', { name: v.trim() })}
        />
        <Saved field="name" saved={saved} />
      </Row>

      <Row label={t('settings.general.customer')} labelFor="set-customer">
        <BlurText
          id="set-customer"
          value={project.customer}
          readOnly={readOnly}
          validate={(v) => (v.trim().length < 1 || v.trim().length > 200 ? t('settings.general.errors.customer') : null)}
          onCommit={(v) => commit('customer', { customer: v.trim() })}
        />
        <Saved field="customer" saved={saved} />
      </Row>

      <Row label={t('settings.general.description')} labelFor="set-description">
        {readOnly ? (
          <div id="set-description" className="set-text">
            <AutoLinkText text={project.description || t('common.empty')} />
          </div>
        ) : (
          <BlurText
            id="set-description"
            multiline
            value={project.description}
            readOnly={readOnly}
            validate={(v) => (v.length > 10_000 ? t('projectCreate.errors.description') : null)}
            onCommit={(v) => commit('description', { description: v })}
          />
        )}
        <Saved field="description" saved={saved} />
      </Row>

      <Row label={t('settings.general.phases')}>
        <div className="chips" role="group" aria-label={t('settings.general.phases')}>
          {project.phases.map((phase) => (
            <button
              key={phase.phase_id}
              type="button"
              className={`chip${phase.is_enabled ? ' on' : ''}`}
              aria-pressed={phase.is_enabled}
              disabled={readOnly || phase.is_cross_cutting || busy}
              onClick={() =>
                commit('phases', { phases: [{ phase_id: phase.phase_id, is_enabled: !phase.is_enabled }] })
              }
            >
              {phase.is_enabled ? <span aria-hidden="true">✓ </span> : null}
              {phase.name}
              {phase.is_cross_cutting ? ` · ${t('settings.general.always')}` : null}
            </button>
          ))}
        </div>
        <Saved field="phases" saved={saved} />
      </Row>

      <Row label={t('settings.general.detail')}>
        <SegmentedControl
          aria-label={t('settings.general.detail')}
          value={project.detail_level}
          disabled={readOnly}
          data={LEVELS.map((level) => ({ value: level, label: t(`projectCreate.detailLevel.${level}`) }))}
          onChange={(value) => commit('detail_level', { detail_level: value as DetailLevel })}
        />
        <span className="set-hint">
          {t(`settings.general.detailHint.${project.detail_level}`, {
            hours: threshold ? formatNumber(String(threshold), 0) : '…',
          })}
        </span>
        <Saved field="detail_level" saved={saved} />
      </Row>

      <Row label={t('settings.general.pm')} labelFor="set-pm">
        <div className="set-inline">
          <BlurText
            id="set-pm"
            w={90}
            value={formatNumber(String(project.pm_percent), new Decimal(String(project.pm_percent)).isInteger() ? 0 : 1)}
            readOnly={readOnly}
            validate={(v) => (parsePercent(v) === null ? t('settings.general.errors.percent') : null)}
            onCommit={(v) => commit('pm_percent', { pm_percent: asDecimalString(parsePercent(v) ?? '0') })}
          />
          <span className="set-unit">%</span>
          <div className="grow">
            <BlurText
              id="set-pm-reason"
              value={project.pm_percent_reason}
              readOnly={readOnly}
              placeholder={t('settings.general.pmReasonPlaceholder')}
              validate={(v) => (v.length > 1000 ? t('settings.general.errors.reason') : null)}
              onCommit={(v) => commit('pm_percent_reason', { pm_percent_reason: v })}
            />
          </div>
        </div>
        {new Decimal(project.pm_percent).isZero() ? <span className="set-hint">{t('settings.general.pmOff')}</span> : null}
        <Saved field="pm_percent" saved={saved} />
        <Saved field="pm_percent_reason" saved={saved} />
      </Row>

      <Row label={t('settings.general.pmBase')}>
        <div className="chips" role="group" aria-label={t('settings.general.pmBase')}>
          {enabled
            .filter((phase) => !phase.is_cross_cutting)
            .map((phase) => (
              <button
                key={phase.phase_id}
                type="button"
                className={`chip${phase.in_pm_base ? ' on' : ''}`}
                aria-pressed={phase.in_pm_base}
                disabled={readOnly || busy}
                onClick={() =>
                  commit('pm_base', { phases: [{ phase_id: phase.phase_id, in_pm_base: !phase.in_pm_base }] })
                }
              >
                {phase.in_pm_base ? <span aria-hidden="true">✓ </span> : null}
                {phase.name}
              </button>
            ))}
        </div>
        <span className="set-hint">{t('settings.general.pmBaseHint')}</span>
        <Saved field="pm_base" saved={saved} />
      </Row>

      <Row label={t('settings.general.figure')}>
        <SegmentedControl
          aria-label={t('settings.general.figure')}
          value={project.quote_figure}
          disabled={readOnly}
          data={FIGURES.map((figure) => ({ value: figure, label: t(`home.figure.${figure}`) }))}
          onChange={(value) => commit('quote_figure', { quote_figure: value as QuoteFigure })}
        />
        {figureNow ? (
          <span className="set-hint">
            {t('settings.general.figureNow', {
              hours: formatHours(new Map(Object.entries(figureNow)).get(project.quote_figure) ?? null, { unit: true }),
            })}
          </span>
        ) : null}
        <Saved field="quote_figure" saved={saved} />
      </Row>

      <Row label={t('settings.general.deadline')} labelFor="set-deadline">
        <div className="set-inline">
          {readOnly ? (
            <span id="set-deadline">{project.deadline ? formatDate(project.deadline) : t('common.empty')}</span>
          ) : (
            <TextInput
              id="set-deadline"
              type="date"
              w={170}
              defaultValue={project.deadline ?? ''}
              key={project.deadline ?? ''}
              onBlur={(e) => {
                const value = e.currentTarget.value || null;
                if (value !== project.deadline) commit('deadline', { deadline: value });
              }}
            />
          )}
          <label className="set-label inline" htmlFor="set-weeks">
            {t('settings.general.duration')}
          </label>
          <BlurText
            id="set-weeks"
            w={80}
            value={project.duration_weeks === null ? '' : String(project.duration_weeks)}
            readOnly={readOnly}
            validate={(v) => (parseWeeks(v) === undefined ? t('settings.general.errors.duration') : null)}
            onCommit={(v) => commit('duration_weeks', { duration_weeks: parseWeeks(v) ?? null })}
          />
          <span className="set-hint">{t('settings.general.durationHint')}</span>
        </div>
        <Saved field="deadline" saved={saved} />
        <Saved field="duration_weeks" saved={saved} />
      </Row>

      <ConfirmDialog
        opened={confirm !== null}
        title={t('settings.general.phaseOffTitle', { name: confirmPhase?.name ?? '' })}
        message={t('settings.general.phaseOffText', { count: confirm?.affected ?? 0 })}
        confirmLabel={t('settings.general.phaseOffConfirm')}
        danger
        busy={busy}
        onConfirm={() => confirm && retryConfirmed(confirm)}
        onCancel={cancelConfirm}
      />
    </section>
  );
}
