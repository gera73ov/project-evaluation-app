/**
 * FE-062 · общий каркас формы раздела настроек: чтение `GET /system/settings/{section}`, черновик,
 * «Отмена» и «Сохранить…» (активна, когда есть изменения и нет ошибок) — сохранение со step-up
 * (SEC-AUTH-05), после него — «Сохранено» и перечитанный раздел.
 */
import { Button, NumberInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { settingsKey } from '../layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';
import { intError, limits } from './settings';

type Section = components['schemas']['SettingsSection'];

export function useSection(section: string) {
  return useQuery({
    queryKey: settingsKey(section),
    queryFn: () => call(() => api.GET('/system/settings/{section}', { params: { path: { section } } })),
  });
}

/**
 * Карточка с формой раздела: `toForm` строит черновик из значений, `toValues` — тело PUT,
 * `errors` — ключи полей с ошибкой (кнопка неактивна, поля подсвечены после первой попытки).
 */
export function SectionForm<F>({
  section,
  title,
  data,
  toForm,
  toValues,
  errors,
  hint,
  children,
}: {
  section: string;
  title: string;
  data: Section;
  toForm: (values: object) => F;
  toValues: (form: F) => Record<string, unknown>;
  errors: (form: F) => string[];
  hint?: string;
  children: (form: F, set: (patch: Partial<F>) => void, shown: (field: string) => boolean) => ReactNode;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const initial = toForm(data.values);
  const [form, setForm] = useState<F>(initial);
  const [saved, setSaved] = useState(false);
  const [tried, setTried] = useState(false);
  const dirty = JSON.stringify(toValues(form)) !== JSON.stringify(toValues(initial));
  const errs = errors(form);
  const save = useMutation({
    mutationFn: () =>
      run(() =>
        call(() =>
          api.PUT('/system/settings/{section}', {
            params: { path: { section } },
            body: { values: toValues(form) as never },
          }),
        ),
      ),
    onSuccess: (next) => {
      qc.setQueryData(settingsKey(section), next);
      setForm(toForm(next.values));
      setSaved(true);
      setTried(false);
    },
  });
  useEffect(() => {
    if (!saved) return;
    const id = setTimeout(() => setSaved(false), 4000);
    return () => clearTimeout(id);
  }, [saved]);
  const set = (patch: Partial<F>) => {
    setSaved(false);
    setForm((f) => ({ ...f, ...patch }));
  };
  const error = save.error instanceof StepUpCancelled ? null : save.error;
  return (
    <section className="sec auth-sec" aria-label={title}>
      <h2>{title}</h2>
      {children(form, set, (field) => (tried || dirty) && errs.includes(field))}
      <div className="auth-foot">
        {hint ? <span className="auth-hint">{hint}</span> : null}
        <ErrorText error={error} />
        {saved ? (
          <span className="auth-ok" role="status">
            ✓ {t('system.settings.saved')}
          </span>
        ) : null}
        <Button
          variant="default"
          disabled={!dirty}
          onClick={() => {
            setForm(initial);
            setTried(false);
            save.reset();
          }}
        >
          {t('common.cancel')}
        </Button>
        <Button
          disabled={!dirty}
          loading={save.isPending}
          onClick={() => {
            setTried(true);
            if (errs.length === 0) save.mutate();
          }}
        >
          {t('system.settings.save')}
        </Button>
      </div>
      {modal}
    </section>
  );
}

/** Целое с границами из settings.schema.json и подсказкой «от … до …». */
export function IntField({
  label,
  value,
  onChange,
  settingKey,
  field,
  invalid,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  settingKey: string;
  field?: string;
  invalid: boolean;
}) {
  const { t } = useTranslation();
  const { min, max } = limits(settingKey, field);
  const bad = invalid && intError(value, settingKey, field);
  return (
    <NumberInput
      label={label}
      value={value ?? ''}
      min={min}
      max={max}
      allowDecimal={false}
      allowNegative={false}
      clampBehavior="none"
      description={t('system.settings.range', { min, max })}
      error={bad ? t('system.settings.rangeError', { min, max }) : null}
      onChange={(v) => onChange(v === '' ? null : Number(v))}
    />
  );
}
