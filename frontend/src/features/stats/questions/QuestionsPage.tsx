/**
 * FE-043 · вкладка «Вопросы заказчику» (SPEC 11.11, FR-CQ-02…04; DESIGN.md 7.5, 10.10): чипы
 * статусов с числами, фильтр по дисциплине, флажки и «⇩ Выгрузить в Word» / «⇩ Excel» (только с
 * `cq.manage`; у остальных колонки флажков и кнопок нет в DOM), номер В-NNN, плашки статуса,
 * «изменён после отправки», ответ заказчика, снятый вопрос с причиной. «Внести ответ заказчика» и
 * «Снять» — окном с текстом. Клик по вопросу открывает узел на рабочем экране.
 */
import { Button, Checkbox, Group, Modal, Select, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { useSession } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { ExportTimeout, downloadExport } from '../../../shared/api/exports';
import { call, errorMessage } from '../../../shared/api/problem';
import { formatDate, formatTime } from '../../../shared/format/date';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { StatsShell } from '../details/StatsShell';
import {
  CQ_STATUSES,
  countByStatus,
  cqActions,
  defaultSelection,
  pathLabel,
  questionNo,
  statusDate,
  waitingDays,
  type CustomerStatus,
} from './questions';

type CustomerQuestion = components['schemas']['CustomerQuestion'];
type Project = components['schemas']['Project'];

export const cqKey = (projectId: string) => ['cq', projectId] as const;

export const CQ_TONE = new Map<CustomerStatus, string>([
  ['new', 'acc'],
  ['sent', 'warn'],
  ['answered', 'ok'],
  ['closed', 'gray'],
  ['withdrawn', 'gray'],
]);

/** «сегодня 11:20» или «02.11 15:02». */
export function useWhen() {
  const { t } = useTranslation();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  return (iso: string) => {
    const day = formatDate(iso, timeZone, true);
    const today = formatDate(new Date(), timeZone, true);
    return `${day === today ? t('stats.questions.today') : day} ${formatTime(iso, timeZone)}`;
  };
}

/** Окно с одним полем текста: ответ заказчика или причина снятия. */
export function TextDialog({
  opened,
  title,
  label,
  confirm,
  maxLength,
  busy,
  error,
  danger = false,
  onSubmit,
  onClose,
}: {
  opened: boolean;
  title: string;
  label: string;
  confirm: string;
  maxLength: number;
  busy: boolean;
  error: unknown;
  danger?: boolean;
  onSubmit: (text: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const close = () => {
    setText('');
    onClose();
  };
  return (
    <Modal opened={opened} onClose={close} title={title} centered>
      <Textarea
        label={label}
        value={text}
        maxLength={maxLength}
        autosize
        minRows={3}
        data-autofocus
        onChange={(e) => setText(e.currentTarget.value)}
        description={`${text.length} / ${maxLength}`}
      />
      <ErrorText error={error} />
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={close}>
          {t('common.cancel')}
        </Button>
        <Button
          color={danger ? 'red' : 'accent'}
          loading={busy}
          disabled={!text.trim()}
          onClick={() => onSubmit(text.trim())}
        >
          {confirm}
        </Button>
      </Group>
    </Modal>
  );
}

type Dialog = { kind: 'answer' | 'withdraw'; id: string; no: string } | null;

export function QuestionsPage({ projectId }: { projectId: string }) {
  return (
    <StatsShell projectId={projectId} active="questions">
      {({ project, perms }) => <Questions project={project} perms={perms} />}
    </StatsShell>
  );
}

function Questions({ project, perms }: { project: Project; perms: readonly string[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const when = useWhen();
  const { session } = useSession();
  const meId = session.state === 'ready' ? session.me.id : null;
  const [status, setStatus] = useState<CustomerStatus | null>(null);
  const [discipline, setDiscipline] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const manage = perms.includes('cq.manage');
  const list = useQuery({
    queryKey: [...cqKey(project.id), 'list', discipline],
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/customer-questions', {
          params: {
            path: { id: project.id },
            query: { limit: 200, ...(discipline ? { discipline_id: discipline } : {}) },
          },
        }),
      ),
    select: (data) => data.items as CustomerQuestion[],
  });
  const items = list.data ?? [];
  const counts = countByStatus(items);
  const shown = items.filter((q) => status === null || q.thread.customer_status === status);
  const selectable = new Set(items.map((q) => q.thread.id));
  const selected = (picked ?? defaultSelection(items)).filter((id) => selectable.has(id));
  const refresh = () => qc.invalidateQueries({ queryKey: cqKey(project.id) });

  const exporting = useMutation({
    mutationFn: (format: 'docx' | 'xlsx') =>
      downloadExport(
        () =>
          call(() =>
            api.POST('/projects/{id}/customer-questions/export', {
              params: { path: { id: project.id } },
              body: { thread_ids: selected, format },
            }),
          ),
        { fallbackName: `questions.${format}` },
      ),
    onSettled: () => {
      setPicked(null);
      void refresh();
    },
  });
  const acting = useMutation({
    mutationFn: ({ kind, id, text }: { kind: 'answer' | 'withdraw'; id: string; text: string }) =>
      kind === 'answer'
        ? call(() => api.POST('/threads/{id}/answer', { params: { path: { id } }, body: { body: text } }))
        : call(() => api.POST('/threads/{id}/withdraw', { params: { path: { id } }, body: { reason: text } })),
    onSuccess: () => {
      setDialog(null);
      void refresh();
    },
  });
  const toggle = (id: string) =>
    setPicked(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="det-one">
      <section className="card cq-card" aria-label={t('stats.questions.title')}>
        <div className="cq-tools">
          <div className="chips" role="group" aria-label={t('stats.questions.statusFilter')}>
            {([null, ...CQ_STATUSES] as const).map((s) => (
              <button
                key={s ?? 'all'}
                type="button"
                className={`chip sm${status === s ? ' on' : ''}`}
                aria-pressed={status === s}
                onClick={() => setStatus(s)}
              >
                {t(`stats.questions.chip.${s ?? 'all'}`)} <span className="c">{counts.get(s ?? 'all') ?? 0}</span>
              </button>
            ))}
          </div>
          <Select
            size="xs"
            className="cq-disc"
            aria-label={t('stats.questions.discipline')}
            value={discipline ?? 'all'}
            allowDeselect={false}
            data={[
              { value: 'all', label: t('stats.questions.disciplineAll') },
              ...project.disciplines.map((d) => ({ value: d.discipline_id, label: d.name })),
            ]}
            onChange={(v) => setDiscipline(v && v !== 'all' ? v : null)}
          />
          {manage ? (
            <span className="cq-export">
              <span className="sub">{t('stats.questions.selected', { count: selected.length })}</span>
              <Button
                size="xs"
                disabled={selected.length === 0}
                loading={exporting.isPending && exporting.variables === 'docx'}
                onClick={() => exporting.mutate('docx')}
              >
                ⇩ {t('stats.questions.word')}
              </Button>
              <Button
                size="xs"
                variant="default"
                disabled={selected.length === 0}
                loading={exporting.isPending && exporting.variables === 'xlsx'}
                onClick={() => exporting.mutate('xlsx')}
              >
                ⇩ Excel
              </Button>
            </span>
          ) : null}
        </div>
        {exporting.error ? (
          <div className="err" role="alert">
            {exporting.error instanceof ExportTimeout ? t('stats.exportTimeout') : errorMessage(exporting.error)}
          </div>
        ) : null}
        <ErrorText error={list.error} />
        {list.isSuccess && shown.length === 0 ? <p className="card-hint">{t('stats.questions.empty')}</p> : null}
        {shown.length > 0 ? (
          <table className="t cq-table">
            <thead>
              <tr>
                {manage ? (
                  <th className="cb">
                    <span className="sr-only">{t('stats.questions.pick')}</span>
                  </th>
                ) : null}
                <th className="no">№</th>
                <th>{t('stats.questions.question')}</th>
                <th className="who">{t('stats.questions.author')}</th>
                <th className="st">{t('stats.questions.status')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((q) => {
                const th = q.thread;
                const s = th.customer_status ?? 'new';
                const no = questionNo(th.customer_question_no);
                const on = selected.includes(th.id);
                const date = statusDate(th);
                const actions = cqActions(th, perms, meId);
                const open = () =>
                  navigate(th.node_id ? `/projects/${project.id}?node=${th.node_id}` : `/projects/${project.id}`);
                return (
                  <tr key={th.id} className={[on ? 'sel' : '', `cq-${s}`].join(' ').trim()}>
                    {manage ? (
                      <td className="cb">
                        <Checkbox
                          size="xs"
                          aria-label={t('stats.questions.pickOne', { no })}
                          checked={on}
                          onChange={() => toggle(th.id)}
                        />
                      </td>
                    ) : null}
                    <td className="no">{s === 'withdrawn' ? <s>{no}</s> : no}</td>
                    <td>
                      <button type="button" className="cq-open" onClick={open}>
                        {s === 'withdrawn' ? <s>{th.first_message.body}</s> : th.first_message.body}
                      </button>
                      <div className="sub">
                        {s === 'withdrawn'
                          ? t('stats.questions.withdrawn', { reason: th.withdraw_reason ?? '' })
                          : pathLabel(q.path, t('stats.questions.whole'))}
                      </div>
                      {q.answer && s === 'answered' ? (
                        <div className="cq-answer">
                          <b>{t('discussion.customerAnswer')}</b> ·{' '}
                          {t('stats.questions.answeredBy', {
                            name: q.answer.author?.full_name ?? '',
                            date: formatDate(q.answer.created_at, undefined, true),
                          })}
                          : {q.answer.body}
                        </div>
                      ) : q.answer && s === 'closed' ? (
                        <div className="cq-answer faded">{q.answer.body}</div>
                      ) : null}
                      {actions.answer || actions.withdraw ? (
                        <div className="cq-actions">
                          {actions.answer ? (
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              onClick={() => setDialog({ kind: 'answer', id: th.id, no })}
                            >
                              {t('stats.questions.answer')}
                            </Button>
                          ) : null}
                          {actions.withdraw ? (
                            <Button
                              size="compact-xs"
                              variant="subtle"
                              color="gray"
                              onClick={() => setDialog({ kind: 'withdraw', id: th.id, no })}
                            >
                              {t('stats.questions.withdraw')}
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                    <td className="who">
                      {th.opened_by.full_name}
                      <div className="sub">{when(th.first_message.created_at)}</div>
                    </td>
                    <td className="st">
                      <span className={`pill ${CQ_TONE.get(s) ?? 'gray'}`}>
                        {s === 'closed' ? '✓ ' : ''}
                        {t(`discussion.cq.${s}`)}
                        {date ? ` ${formatDate(date, undefined, true)}` : ''}
                      </span>
                      {th.edited_after_sent ? (
                        <div>
                          <span className="pill gray">{t('stats.questions.edited')}</span>
                        </div>
                      ) : s === 'sent' && th.sent_at ? (
                        <div className="sub">
                          {t('stats.questions.waiting', { count: waitingDays(th.sent_at, new Date()) })}
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
        <p className="card-hint">{t('stats.questions.hint')}</p>
      </section>
      <TextDialog
        key={dialog ? `${dialog.kind}/${dialog.id}` : 'none'}
        opened={dialog !== null}
        title={
          dialog?.kind === 'answer'
            ? t('stats.questions.answerTitle', { no: dialog.no })
            : t('stats.questions.withdrawTitle', { no: dialog?.no ?? '' })
        }
        label={dialog?.kind === 'answer' ? t('stats.questions.answerLabel') : t('stats.questions.reasonLabel')}
        confirm={dialog?.kind === 'answer' ? t('stats.questions.answerSave') : t('stats.questions.withdraw')}
        maxLength={dialog?.kind === 'answer' ? 10_000 : 500}
        danger={dialog?.kind === 'withdraw'}
        busy={acting.isPending}
        error={acting.error}
        onSubmit={(text) => dialog && acting.mutate({ kind: dialog.kind, id: dialog.id, text })}
        onClose={() => {
          acting.reset();
          setDialog(null);
        }}
      />
    </div>
  );
}
