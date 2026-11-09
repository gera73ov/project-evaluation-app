/**
 * FE-011 · создание проекта (FR-PRJ-05 «Создание», FR-PRJ-01; DESIGN.md 10.3).
 *
 * Одна страница `/projects/new`, форма как секция «Основное» настроек: название, заказчик,
 * описание и ссылки, фазы (по умолчанию все активные; сквозная «Управление проектом» — всегда),
 * уровень детализации (по умолчанию «Средне»), дедлайн. Остальное получает значения по умолчанию
 * и правится в настройках. После «Создать» — настройки проекта в статусе «Подготовка».
 */
import { Button, Checkbox, Group, SegmentedControl, TextInput, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../app/router';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';

type DetailLevel = components['schemas']['DetailLevel'];
type ProjectCreate = components['schemas']['ProjectCreate'];

const LEVELS: readonly DetailLevel[] = ['coarse', 'medium', 'detailed'];

export interface CreateForm {
  name: string;
  customer: string;
  description: string;
  phaseIds: string[];
  detailLevel: DetailLevel;
  deadline: string;
}

export type FieldErrors = Partial<Record<'name' | 'customer' | 'description' | 'phases' | 'deadline', string>>;

/** Сегодня в формате поля даты (YYYY-MM-DD) по часам браузера. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Проверки FR-PRJ-01 на клиенте; сервер проверяет то же самое (VALIDATION_FAILED). */
export function validate(form: CreateForm, today: string): FieldErrors {
  const errors: FieldErrors = {};
  const name = form.name.trim();
  const customer = form.customer.trim();
  if (name.length < 3 || name.length > 200) errors.name = 'projectCreate.errors.name';
  if (customer.length < 1 || customer.length > 200) errors.customer = 'projectCreate.errors.customer';
  if (form.description.length > 10_000) errors.description = 'projectCreate.errors.description';
  if (form.phaseIds.length === 0) errors.phases = 'projectCreate.errors.phases';
  if (form.deadline && form.deadline < today) errors.deadline = 'projectCreate.errors.deadline';
  return errors;
}

export function toRequest(form: CreateForm): ProjectCreate {
  return {
    name: form.name.trim(),
    customer: form.customer.trim(),
    ...(form.description.trim() ? { description: form.description } : {}),
    phase_ids: form.phaseIds,
    detail_level: form.detailLevel,
    deadline: form.deadline || null,
  };
}

export function ProjectCreatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Omit<CreateForm, 'phaseIds'>>({
    name: '',
    customer: '',
    description: '',
    detailLevel: 'medium',
    deadline: '',
  });
  const [touched, setTouched] = useState(false);
  const today = todayIso();

  const phases = useQuery({
    queryKey: ['dict', 'phases'],
    queryFn: () => call(() => api.GET('/admin/phases')),
    staleTime: 10 * 60_000,
    select: (data) => data.items.filter((p) => p.is_active).sort((a, b) => a.sort_order - b.sort_order),
  });

  // по умолчанию включены все активные фазы (FR-PRJ-01): храним только выключенные
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const phaseIds = (phases.data ?? [])
    .filter((p) => p.is_cross_cutting || !excluded.has(p.id))
    .map((p) => p.id);
  const current: CreateForm = { ...form, phaseIds };

  const create = useMutation({
    mutationFn: (body: ProjectCreate) => call(() => api.POST('/projects', { body })),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${result.project.id}/settings`, { replace: true });
    },
  });

  const errors = new Map(Object.entries(touched ? validate(current, today) : {}));
  const error = (key: keyof FieldErrors) => {
    const message = errors.get(key);
    return message ? t(message) : undefined;
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(validate(current, today)).length > 0) return;
    create.mutate(toRequest(current));
  }

  function togglePhase(id: string, on: boolean) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (on) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="page-narrow">
      <h1>{t('projectCreate.title')}</h1>
      <form className="sec create-form" onSubmit={submit} noValidate aria-labelledby="create-section">
        <h3 id="create-section">{t('projectCreate.section')}</h3>
        <ErrorText error={create.error} />
        <TextInput
          label={t('projectCreate.name')}
          description={t('projectCreate.nameHint')}
          value={form.name}
          maxLength={200}
          required
          autoFocus
          error={error('name')}
          onChange={(e) => setForm({ ...form, name: e.currentTarget.value })}
          mb="md"
        />
        <TextInput
          label={t('projectCreate.customer')}
          value={form.customer}
          maxLength={200}
          required
          error={error('customer')}
          onChange={(e) => setForm({ ...form, customer: e.currentTarget.value })}
          mb="md"
        />
        <Textarea
          label={t('projectCreate.description')}
          description={t('projectCreate.descriptionHint')}
          value={form.description}
          autosize
          minRows={3}
          maxRows={10}
          error={error('description')}
          onChange={(e) => setForm({ ...form, description: e.currentTarget.value })}
          mb="md"
        />
        <fieldset className="phase-list">
          <legend className="field-label">{t('projectCreate.phases')}</legend>
            {(phases.data ?? []).map((phase) => (
              <Checkbox
                key={phase.id}
                checked={phaseIds.includes(phase.id)}
                disabled={phase.is_cross_cutting}
                onChange={(e) => togglePhase(phase.id, e.currentTarget.checked)}
                label={
                  <>
                    {phase.name}
                    {phase.is_cross_cutting ? <span className="pill gray always">{t('projectCreate.always')}</span> : null}
                  </>
                }
              />
            ))}
          {error('phases') ? <div className="field-error">{error('phases')}</div> : null}
        </fieldset>
        <div className="field-label" id="detail-label">
          {t('projectCreate.detail')}
        </div>
        <SegmentedControl
          aria-labelledby="detail-label"
          value={form.detailLevel}
          data={LEVELS.map((level) => ({ value: level, label: t(`projectCreate.detailLevel.${level}`) }))}
          onChange={(value) => setForm({ ...form, detailLevel: value as DetailLevel })}
          mb="md"
        />
        <TextInput
          type="date"
          label={t('projectCreate.deadline')}
          description={t('projectCreate.deadlineHint')}
          value={form.deadline}
          min={today}
          error={error('deadline')}
          onChange={(e) => setForm({ ...form, deadline: e.currentTarget.value })}
          w={220}
          mb="md"
        />
        <p className="muted-note">{t('projectCreate.note')}</p>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => navigate('/')}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={create.isPending}>
            {t('projectCreate.submit')}
          </Button>
        </Group>
      </form>
    </div>
  );
}
