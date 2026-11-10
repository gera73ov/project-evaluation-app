/**
 * FE-071 · «Пороги и проценты» (SPEC 7.5, GAP-13, settings.schema.json method.*): порог крупного
 * листа для Средне/Детально, ожидаемое число единиц для Средне, % УП по умолчанию, срок
 * автоархивации. У каждого поля — когда действует: сразу на все проекты или только на новые.
 */
import { Button, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { dec, decimal, dictKey, hoursValid, type MethodSettings } from './dictionaries';

type Draft = { medium: string; detailed: string; min: string; max: string; pm: string; archive: string };

const toDraft = (m: MethodSettings): Draft => ({
  medium: m.large_leaf_hours.medium,
  detailed: m.large_leaf_hours.detailed,
  min: String(m.medium_expected_units.min),
  max: String(m.medium_expected_units.max),
  pm: m.pm_percent_default,
  archive: String(m.autoarchive_days),
});

const int = (s: string, min: number, max: number) => /^\d{1,4}$/.test(s) && Number(s) >= min && Number(s) <= max;

/** Ошибки полей по settings.schema.json: часы > 0, единицы 1–1000 и min ≤ max, УП 0–50 шагом 0,5. */
export function methodErrors(d: Draft) {
  const pm = Number(decimal(d.pm));
  return {
    medium: !hoursValid(d.medium) || Number(decimal(d.medium)) <= 0,
    detailed: !hoursValid(d.detailed) || Number(decimal(d.detailed)) <= 0,
    min: !int(d.min, 1, 1000),
    max: !int(d.max, 1, 1000) || (int(d.min, 1, 1000) && Number(d.min) > Number(d.max)),
    pm: !hoursValid(d.pm) || pm > 50 || (pm * 2) % 1 !== 0,
    archive: !int(d.archive, 0, 3650),
  };
}

export function MethodForm() {
  const settings = useQuery({
    queryKey: dictKey('method'),
    queryFn: () => call(() => api.GET('/admin/method-settings')) as Promise<MethodSettings>,
  });
  if (!settings.data) return <ErrorText error={settings.error} />;
  return <Form initial={settings.data} />;
}

function Form({ initial }: { initial: MethodSettings }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [d, setD] = useState<Draft>(toDraft(initial));
  const [done, setDone] = useState(false);
  const errors = methodErrors(d);
  const valid = !Object.values(errors).some(Boolean);
  const set = (patch: Partial<Draft>) => {
    setDone(false);
    setD((x) => ({ ...x, ...patch }));
  };
  const save = useMutation({
    mutationFn: () =>
      call(() =>
        api.PUT('/admin/method-settings', {
          body: {
            large_leaf_hours: { medium: dec(d.medium), detailed: dec(d.detailed) },
            medium_expected_units: { min: Number(d.min), max: Number(d.max) },
            pm_percent_default: dec(d.pm),
            autoarchive_days: Number(d.archive),
          },
        }),
      ),
    onSuccess: () => {
      setDone(true);
      void qc.invalidateQueries({ queryKey: dictKey('method') });
    },
  });
  const values = new Map(Object.entries(d));
  const bad = new Map(Object.entries(errors));
  const field = (key: keyof Draft, label: string, hint: string, unit?: string) => (
    <TextInput
      label={label}
      description={hint}
      required
      value={values.get(key) ?? ''}
      maxLength={8}
      rightSection={unit}
      rightSectionWidth={unit && unit.length > 2 ? 48 : undefined}
      error={bad.get(key) ? t(`admin.dict.method.err.${key}`) : null}
      onChange={(e) => set({ [key]: e.currentTarget.value })}
    />
  );
  return (
    <section className="sec adm-method">
      <h3>{t('admin.dict.method.leaf')}</h3>
      <p className="sys-sub">{t('admin.dict.method.now')}</p>
      <div className="adm-pair">
        {field('medium', t('admin.dict.method.medium'), t('admin.dict.method.mediumHint'), t('admin.dict.method.h'))}
        {field(
          'detailed',
          t('admin.dict.method.detailed'),
          t('admin.dict.method.detailedHint'),
          t('admin.dict.method.h'),
        )}
      </div>
      <h3>{t('admin.dict.method.units')}</h3>
      <p className="sys-sub">{t('admin.dict.method.now')}</p>
      <div className="adm-pair">
        {field('min', t('admin.dict.method.min'), t('admin.dict.method.unitsHint'))}
        {field('max', t('admin.dict.method.max'), t('admin.dict.method.unitsHint'))}
      </div>
      <h3>{t('admin.dict.method.pmTitle')}</h3>
      <p className="sys-sub">{t('admin.dict.method.newOnly')}</p>
      {field('pm', t('admin.dict.method.pm'), t('admin.dict.method.pmHint'), '%')}
      <h3>{t('admin.dict.method.archiveTitle')}</h3>
      <p className="sys-sub">{t('admin.dict.method.now')}</p>
      {field(
        'archive',
        t('admin.dict.method.archive'),
        t('admin.dict.method.archiveHint'),
        t('admin.dict.method.days'),
      )}
      <ErrorText error={save.error} />
      {done ? (
        <p className="auth-ok" role="status">
          ✓ {t('admin.dict.saved')}
        </p>
      ) : null}
      <div className="sys-actions">
        <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>
          {t('common.save')}
        </Button>
      </div>
    </section>
  );
}
