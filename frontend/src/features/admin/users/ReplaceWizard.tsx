/**
 * FE-070 · мастер «Заменить участника» (SPEC 7.5, FR-ADM-05, Q-29): выбор замены → список активных
 * проектов с ролями заменяемого (dry run) → снятие отметок → подтверждение → итог. Проект, где
 * у замены нет нужной системной роли (модератор, пресейл), отметить нельзя — рядом предупреждение.
 */
import { Button, Checkbox, Group, Modal, Select, Stack } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { replacementCandidates, usersKey, type User } from './users';

type Report = components['schemas']['ReplaceReport'];
type Step = 'pick' | 'projects' | 'confirm' | 'done';

export function ReplaceWizard({ user, opened, onClose }: { user: User; opened: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onClose} title={t('admin.replace.title', { name: user.full_name })} size="lg">
      {opened ? <Wizard user={user} onClose={onClose} /> : null}
    </Modal>
  );
}

function Wizard({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>('pick');
  const [to, setTo] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<Report | null>(null);
  const all = useQuery({
    queryKey: [...usersKey, 'candidates'],
    queryFn: () => call(() => api.GET('/admin/users', { params: { query: { limit: 200, status: 'active' } } })),
  });
  const disciplines = useQuery({
    queryKey: ['admin', 'disciplines'],
    queryFn: () => call(() => api.GET('/admin/disciplines')),
  });
  const discName = (id: string | null) => (id ? (disciplines.data?.items.find((d) => d.id === id)?.name ?? '') : '');
  const candidates = replacementCandidates(all.data?.items ?? [], user);
  const replacement = candidates.find((c) => c.id === to) ?? null;

  const preview = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/users/{id}/replace', {
          params: { path: { id: user.id } },
          body: { replacement_user_id: to ?? '', dry_run: true },
        }),
      ),
    onSuccess: (r) => {
      setReport(r);
      setChosen(r.projects.filter((p) => p.applicable).map((p) => p.project_id));
      setStep('projects');
    },
  });
  const apply = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/admin/users/{id}/replace', {
          params: { path: { id: user.id } },
          body: { replacement_user_id: to ?? '', dry_run: false, project_ids: chosen },
        }),
      ),
    onSuccess: (r) => {
      setResult(r);
      setStep('done');
      void qc.invalidateQueries({ queryKey: usersKey });
    },
  });

  const roleText = (r: Report['projects'][number]['roles'][number]) =>
    [t(`home.roles.${r.role}`), discName(r.discipline_id), r.is_reviewer ? t('admin.replace.reviewer') : '']
      .filter(Boolean)
      .join(' · ');

  if (step === 'pick')
    return (
      <Stack gap="sm">
        <p>{t('admin.replace.intro')}</p>
        <Select
          label={t('admin.replace.to')}
          placeholder={t('admin.replace.toPlaceholder')}
          searchable
          value={to}
          data={candidates.map((c) => ({ value: c.id, label: `${c.full_name} · ${c.login}` }))}
          onChange={setTo}
        />
        <ErrorText error={all.error ?? preview.error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button disabled={!to} loading={preview.isPending} onClick={() => preview.mutate()}>
            {t('admin.replace.next')}
          </Button>
        </Group>
      </Stack>
    );

  if (step === 'projects' && report)
    return (
      <Stack gap="sm">
        {report.projects.length === 0 ? (
          <p className="sys-empty">{t('admin.replace.noProjects')}</p>
        ) : (
          <>
            <p>{t('admin.replace.projectsIntro', { to: replacement?.full_name ?? '' })}</p>
            <Checkbox.Group value={chosen} onChange={setChosen}>
              <ul className="adm-replace-list">
                {report.projects.map((p) => (
                  <li key={p.project_id}>
                    <Checkbox value={p.project_id} disabled={!p.applicable} label={<b>{p.name}</b>} />
                    <div className="sub">{p.roles.map(roleText).join('; ')}</div>
                    {p.problem ? (
                      <div className="set-danger" role="alert">
                        {t(`admin.replace.problem.${p.problem}`, { to: replacement?.full_name ?? '' })}
                      </div>
                    ) : null}
                    {p.open_questions > 0 ? (
                      <div className="auth-hint">{t('admin.replace.questions', { count: p.open_questions })}</div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Checkbox.Group>
          </>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setStep('pick')}>
            {t('admin.replace.back')}
          </Button>
          <Button disabled={chosen.length === 0} onClick={() => setStep('confirm')}>
            {t('admin.replace.replace')}
          </Button>
        </Group>
      </Stack>
    );

  if (step === 'confirm')
    return (
      <Stack gap="sm">
        <p>
          {t('admin.replace.confirm', {
            from: user.full_name,
            to: replacement?.full_name ?? '',
            count: chosen.length,
          })}
        </p>
        <p className="auth-hint">{t('admin.replace.confirmHint')}</p>
        <ErrorText error={apply.error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setStep('projects')}>
            {t('admin.replace.back')}
          </Button>
          <Button color="red" loading={apply.isPending} onClick={() => apply.mutate()}>
            {t('admin.replace.apply')}
          </Button>
        </Group>
      </Stack>
    );

  return (
    <Stack gap="sm">
      <p className="auth-ok" role="status">
        ✓ {t('admin.replace.done', { count: result?.projects.length ?? 0, to: replacement?.full_name ?? '' })}
      </p>
      <ul className="adm-replace-done">
        {(result?.projects ?? []).map((p) => (
          <li key={p.project_id}>{p.name}</li>
        ))}
      </ul>
      <Group justify="flex-end">
        <Button onClick={onClose}>{t('common.close')}</Button>
      </Group>
    </Stack>
  );
}
