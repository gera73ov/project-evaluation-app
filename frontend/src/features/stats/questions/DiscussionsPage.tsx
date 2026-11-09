/**
 * FE-043 · вкладка «Обсуждения» (SPEC 11.10, абзац под таблицей): устроена как «Вопросы заказчику»,
 * но показывает все вопросы проекта (`GET /projects/{id}/threads`) с фильтрами по адресату
 * («все» / «мне»), статусу (открыт / решён) и дисциплине. Без флажков и выгрузки. Клик по вопросу
 * открывает узел на рабочем экране. Путь узла берётся из дерева проекта.
 */
import { Select } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { pathOf } from '../details/details';
import { StatsShell, useTree } from '../details/StatsShell';
import { addresseeKinds, pathLabel, questionNo } from './questions';
import { CQ_TONE, useWhen } from './QuestionsPage';

type Thread = components['schemas']['Thread'];
type Node = components['schemas']['Node'];
type Project = components['schemas']['Project'];

type ThreadStatus = Thread['status'];

export function DiscussionsPage({ projectId }: { projectId: string }) {
  return (
    <StatsShell projectId={projectId} active="discussions">
      {({ project }) => <Discussions project={project} />}
    </StatsShell>
  );
}

function Discussions({ project }: { project: Project }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const when = useWhen();
  const [status, setStatus] = useState<ThreadStatus | null>(null);
  const [mine, setMine] = useState(false);
  const [discipline, setDiscipline] = useState<string | null>(null);
  const tree = useTree(project.id);
  const list = useQuery({
    queryKey: ['threads', project.id, discipline, mine],
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/threads', {
          params: {
            path: { id: project.id },
            query: {
              limit: 200,
              addressee: mine ? 'me' : 'any',
              ...(discipline ? { discipline_id: discipline } : {}),
            },
          },
        }),
      ),
    select: (data) => data.items as Thread[],
  });
  const byId = new Map<string, Node>((tree.data?.nodes ?? []).map((n) => [n.id, n]));
  const pathFor = (id: string | null) => {
    const node = id ? byId.get(id) : undefined;
    return node ? [...pathOf(node.id, byId), node.title] : [];
  };
  const items = list.data ?? [];
  const counts = new Map<ThreadStatus | 'all', number>([
    ['all', items.length],
    ['open', items.filter((x) => x.status === 'open').length],
    ['resolved', items.filter((x) => x.status === 'resolved').length],
  ]);
  const shown = items.filter((x) => status === null || x.status === status);
  return (
    <div className="det-one">
      <section className="card cq-card" aria-label={t('stats.discussions.title')}>
        <div className="cq-tools">
          <div className="chips" role="group" aria-label={t('stats.questions.statusFilter')}>
            {([null, 'open', 'resolved'] as const).map((s) => (
              <button
                key={s ?? 'all'}
                type="button"
                className={`chip sm${status === s ? ' on' : ''}`}
                aria-pressed={status === s}
                onClick={() => setStatus(s)}
              >
                {t(`stats.discussions.chip.${s ?? 'all'}`)} <span className="c">{counts.get(s ?? 'all') ?? 0}</span>
              </button>
            ))}
          </div>
          <Select
            size="xs"
            className="cq-disc"
            aria-label={t('stats.discussions.addressee')}
            value={mine ? 'me' : 'any'}
            allowDeselect={false}
            data={[
              { value: 'any', label: t('stats.discussions.toAny') },
              { value: 'me', label: t('stats.discussions.toMe') },
            ]}
            onChange={(v) => setMine(v === 'me')}
          />
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
        </div>
        <ErrorText error={list.error} />
        {list.isSuccess && shown.length === 0 ? <p className="card-hint">{t('stats.discussions.empty')}</p> : null}
        {shown.length > 0 ? (
          <table className="t cq-table">
            <thead>
              <tr>
                <th>{t('stats.questions.question')}</th>
                <th className="who">{t('stats.discussions.to')}</th>
                <th className="who">{t('stats.questions.author')}</th>
                <th className="st">{t('stats.questions.status')}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((th) => {
                const open = () =>
                  navigate(th.node_id ? `/projects/${project.id}?node=${th.node_id}` : `/projects/${project.id}`);
                const kinds = addresseeKinds(th);
                return (
                  <tr key={th.id} className={th.status === 'resolved' ? 'cq-closed' : undefined}>
                    <td>
                      <button type="button" className="cq-open" onClick={open}>
                        {th.is_customer ? <span className="cq-no">{questionNo(th.customer_question_no)} </span> : null}
                        {th.first_message.body}
                      </button>
                      <div className="sub">{pathLabel(pathFor(th.node_id), t('stats.questions.whole'))}</div>
                    </td>
                    <td className="who">
                      {kinds.length === 0
                        ? '—'
                        : kinds.map((k) => t(`stats.discussions.kind.${k}`, { defaultValue: k })).join(', ')}
                    </td>
                    <td className="who">
                      {th.opened_by.full_name}
                      <div className="sub">{when(th.first_message.created_at)}</div>
                    </td>
                    <td className="st">
                      {th.is_customer && th.customer_status ? (
                        <span className={`pill ${CQ_TONE.get(th.customer_status) ?? 'gray'}`}>
                          {t('stats.discussions.customer', { status: t(`discussion.cq.${th.customer_status}`) })}
                        </span>
                      ) : (
                        <span className={`pill ${th.status === 'resolved' ? 'gray' : 'warn'}`}>
                          {th.status === 'resolved' ? '✓ ' : ''}
                          {t(`stats.discussions.state.${th.status}`)}
                        </span>
                      )}
                      {th.replies_count > 0 ? (
                        <div className="sub">{t('stats.discussions.replies', { count: th.replies_count })}</div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
        <p className="card-hint">{t('stats.discussions.hint')}</p>
      </section>
    </div>
  );
}
