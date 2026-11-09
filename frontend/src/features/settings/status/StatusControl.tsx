/**
 * FE-015 · кнопка статуса проекта с меню переходов (FR-PRJ-05, диаграмма 4.2; DESIGN.md 6.1, 6.12)
 * и меню «⋯» → «Копировать проект…» (FR-PRJ-02).
 *
 * Переходы — только по стрелкам 4.2. Подтверждение собирается на клиенте из того, что уже есть
 * у модератора: состав команды, статусы веток дерева, вопросы заказчику, снимки. Окончательно
 * переход проверяет сервер (409 INVALID_TRANSITION). Без права `project.status` — плашка статуса.
 */
import { Button, Group, Menu, Modal, Text, TextInput, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { StatusBadge } from '../../../shared/ui/StatusBadge';
import { membersKey } from '../team/TeamSection';
import { projectKey, type Project } from '../useProject';

type ProjectStatus = components['schemas']['ProjectStatus'];
type BranchStatus = components['schemas']['BranchStatus'];
type Member = components['schemas']['Member'];

export type TransitionKey =
  | 'start'
  | 'consolidate'
  | 'return'
  | 'complete'
  | 'reopen'
  | 'cancel'
  | 'archive'
  | 'restore';

export interface Transition {
  key: TransitionKey;
  to: ProjectStatus;
  danger?: boolean;
}

/** Стрелки диаграммы 4.2, которые выполняет модератор (FR-PRJ-05). */
export const TRANSITIONS: ReadonlyMap<ProjectStatus, readonly Transition[]> = new Map<ProjectStatus, Transition[]>([
  ['preparation', [{ key: 'start', to: 'estimation' }]],
  [
    'estimation',
    [
      { key: 'consolidate', to: 'consolidation' },
      { key: 'cancel', to: 'archived', danger: true },
    ],
  ],
  [
    'consolidation',
    [
      { key: 'return', to: 'estimation' },
      { key: 'complete', to: 'completed' },
    ],
  ],
  [
    'completed',
    [
      { key: 'reopen', to: 'estimation' },
      { key: 'archive', to: 'archived' },
    ],
  ],
  ['archived', [{ key: 'restore', to: 'completed' }]],
]);

/** Что знает клиент к моменту подтверждения. */
export interface StatusFacts {
  experts: number;
  disciplinesWithoutExpert: string[];
  /** «Фаза · Дисциплина» веток «черновик» и «не начато». */
  branchesNotDone: string[];
  openQuestions: number | null;
  hasSnapshot: boolean | null;
}

export type Confirmation =
  | { kind: 'none' }
  | { kind: 'confirm'; question: string | null; warnings: string[] }
  | { kind: 'reason' };

/** Нужное подтверждение по таблице FR-PRJ-05; `t` — переводчик. */
export function confirmationFor(key: TransitionKey, facts: StatusFacts, t: TFunction): Confirmation {
  const branches = facts.branchesNotDone.length
    ? [t('status.warn.branches', { list: facts.branchesNotDone.join(', ') })]
    : [];
  switch (key) {
    case 'start':
      return {
        kind: 'confirm',
        question: t('status.ask.start', { count: facts.experts }),
        warnings: facts.disciplinesWithoutExpert.length
          ? [t('status.warn.noExpert', { list: facts.disciplinesWithoutExpert.join(', ') })]
          : [],
      };
    case 'consolidate':
      return branches.length ? { kind: 'confirm', question: null, warnings: branches } : { kind: 'none' };
    case 'return':
      return { kind: 'none' };
    case 'complete': {
      const warnings = [...branches];
      if (facts.openQuestions) warnings.push(t('status.warn.questions', { count: facts.openQuestions }));
      if (facts.hasSnapshot === false) warnings.push(t('status.warn.noSnapshot'));
      return { kind: 'confirm', question: t('status.ask.complete'), warnings };
    }
    case 'reopen':
      return { kind: 'confirm', question: t('status.ask.reopen'), warnings: [] };
    case 'cancel':
      return { kind: 'reason' };
    case 'archive':
      return { kind: 'confirm', question: t('status.ask.archive'), warnings: [] };
    case 'restore':
      return { kind: 'confirm', question: t('status.ask.restore'), warnings: [] };
  }
}

export const REASON_MIN = 10;
export const REASON_MAX = 500;

function useStatusFacts(project: Project, enabled: boolean): StatusFacts | null {
  const id = project.id;
  const members = useQuery({
    queryKey: membersKey(id),
    queryFn: () => call(() => api.GET('/projects/{id}/members', { params: { path: { id } } })),
    select: (data) => data.items as Member[],
    enabled,
  });
  const tree = useQuery({
    queryKey: ['tree', id],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id } } })),
    select: (data) => data.branch_statuses as BranchStatus[],
    enabled,
  });
  const questions = useQuery({
    queryKey: ['customer-questions', id, 'open-count'],
    queryFn: () =>
      call(() => api.GET('/projects/{id}/customer-questions', { params: { path: { id }, query: { limit: 200 } } })),
    select: (data) =>
      data.items.filter((q) => q.thread.customer_status === 'new' || q.thread.customer_status === 'sent').length,
    enabled: enabled && project.my_permissions.includes('cq.read'),
  });
  const snapshots = useQuery({
    queryKey: ['snapshots', id, 'any'],
    queryFn: () => call(() => api.GET('/projects/{id}/snapshots', { params: { path: { id } } })),
    select: (data) => data.items.length > 0,
    enabled: enabled && project.my_permissions.includes('snapshot.read'),
  });
  if (!members.data || !tree.data) return null;

  const phase = new Map(project.phases.map((p) => [p.phase_id, p.name]));
  const discipline = new Map(project.disciplines.map((d) => [d.discipline_id, d.name]));
  return {
    experts: new Set(members.data.filter((m) => m.role === 'expert').map((m) => m.user.id)).size,
    disciplinesWithoutExpert: project.disciplines.filter((d) => !d.has_expert).map((d) => d.name),
    branchesNotDone: tree.data
      .filter((b) => b.status === 'draft' || b.status === 'not_started')
      .map((b) => `${phase.get(b.phase_id) ?? '—'} · ${discipline.get(b.discipline_id) ?? '—'}`),
    openQuestions: questions.data ?? null,
    hasSnapshot: snapshots.data ?? null,
  };
}

export function StatusControl({
  project,
  readOnly,
  label = true,
}: {
  project: Project;
  readOnly: boolean;
  /** Подпись «Статус» — в шапке настроек; в верхней полосе её нет (DESIGN.md 9.2). */
  label?: boolean;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const canChange = project.my_permissions.includes('project.status');
  const canCopy = project.my_permissions.includes('project.copy');
  const [pending, setPending] = useState<Transition | null>(null);
  const [copyOpen, setCopyOpen] = useState(false);
  const facts = useStatusFacts(project, canChange);

  const change = useMutation({
    mutationFn: (body: components['schemas']['StatusChange']) =>
      call(() => api.POST('/projects/{id}/status', { params: { path: { id: project.id } }, body })),
    onSuccess: () => {
      setPending(null);
      void client.invalidateQueries({ queryKey: projectKey(project.id) });
      void client.invalidateQueries({ queryKey: ['tree', project.id] });
      void client.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  function choose(transition: Transition) {
    change.reset();
    const confirmation = facts ? confirmationFor(transition.key, facts, t) : null;
    if (confirmation?.kind === 'none') change.mutate({ to: transition.to });
    else setPending(transition);
  }

  const transitions = TRANSITIONS.get(project.status) ?? [];
  return (
    <div className="status-ctl">
      {label ? <span className="set-unit">{t('status.label')}</span> : null}
      {canChange && !readOnly ? (
        <Menu position="bottom-end" width={240}>
          <Menu.Target>
            <button
              type="button"
              className="status-btn"
              aria-label={t('status.button', { status: t(`status.project.${project.status}`) })}
            >
              {t(`status.project.${project.status}`)} ▾
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            {transitions.map((tr) => (
              <Menu.Item
                key={tr.key}
                {...(tr.danger ? { className: 'danger' } : {})}
                disabled={!facts}
                onClick={() => choose(tr)}
              >
                {t(`status.action.${tr.key}`)}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      ) : (
        <StatusBadge kind="project" status={project.status} />
      )}
      {canCopy && !readOnly ? (
        <Menu position="bottom-end">
          <Menu.Target>
            <button type="button" className="ghost-btn" aria-label={t('status.more')}>
              ⋯
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => setCopyOpen(true)}>{t('status.copy.action')}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      ) : null}
      {pending && facts ? (
        <StatusDialog
          transition={pending}
          confirmation={confirmationFor(pending.key, facts, t)}
          busy={change.isPending}
          error={change.error}
          onConfirm={(reason) => change.mutate({ to: pending.to, ...(reason ? { reason } : {}) })}
          onCancel={() => setPending(null)}
        />
      ) : null}
      {!pending && change.error ? <ErrorText error={change.error} /> : null}
      {copyOpen ? <CopyDialog project={project} onClose={() => setCopyOpen(false)} /> : null}
    </div>
  );
}

function StatusDialog({
  transition,
  confirmation,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  transition: Transition;
  confirmation: Confirmation;
  busy: boolean;
  error: Error | null;
  onConfirm: (reason: string | null) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const needsReason = confirmation.kind === 'reason';
  const trimmed = reason.trim();
  const reasonOk = trimmed.length >= REASON_MIN && trimmed.length <= REASON_MAX;
  const title = t(`status.title.${transition.key}`);

  return (
    <Modal opened onClose={onCancel} title={title} centered size={440} closeOnClickOutside={!needsReason}>
      <ErrorText error={error} />
      {confirmation.kind === 'confirm' && confirmation.question ? <Text mb="sm">{confirmation.question}</Text> : null}
      {confirmation.kind === 'confirm' && confirmation.warnings.length ? (
        <ul className="confirm-warn">
          {confirmation.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {needsReason ? (
        <Textarea
          label={t('status.reason.label')}
          description={t('status.reason.hint')}
          value={reason}
          autosize
          minRows={3}
          maxLength={REASON_MAX}
          data-autofocus
          error={touched && !reasonOk ? t('status.reason.error') : undefined}
          onChange={(e) => setReason(e.currentTarget.value)}
          onBlur={() => setTouched(true)}
          mb={4}
        />
      ) : null}
      {needsReason ? (
        <div className="char-count">
          {reason.length} / {REASON_MAX}
        </div>
      ) : null}
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button
          color={transition.danger ? 'red' : 'accent'}
          loading={busy}
          {...(needsReason ? {} : { 'data-autofocus': true })}
          onClick={() => {
            if (needsReason && !reasonOk) return setTouched(true);
            onConfirm(needsReason ? trimmed : null);
          }}
        >
          {t(`status.confirm.${transition.key}`)}
        </Button>
      </Group>
    </Modal>
  );
}

function CopyDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState(() => t('status.copy.defaultName', { name: project.name }).slice(0, 200));
  const trimmed = name.trim();
  const valid = trimmed.length >= 3 && trimmed.length <= 200;
  const copy = useMutation({
    mutationFn: () =>
      call(() => api.POST('/projects/{id}/copy', { params: { path: { id: project.id } }, body: { name: trimmed } })),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ['projects'] });
      onClose();
      navigate(`/projects/${result.project.id}/settings`);
    },
  });
  return (
    <Modal opened onClose={onClose} title={t('status.copy.title')} centered size={440}>
      <ErrorText error={copy.error} />
      <TextInput
        label={t('status.copy.name')}
        value={name}
        maxLength={200}
        data-autofocus
        error={valid ? undefined : t('projectCreate.errors.name')}
        onChange={(e) => setName(e.currentTarget.value)}
        mb="sm"
      />
      <Text size="sm" c="dimmed">
        {t('status.copy.note')}
      </Text>
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button loading={copy.isPending} disabled={!valid} onClick={() => copy.mutate()}>
          {t('status.copy.submit')}
        </Button>
      </Group>
    </Modal>
  );
}
