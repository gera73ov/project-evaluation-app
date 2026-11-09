/**
 * FE-022 · рабочий экран проекта `/projects/:id` (SPEC 8.4, 11.4; DESIGN.md 9): дерево оценки.
 *
 * Кто что правит: модератор — все ветки, эксперт — ветки своих дисциплин (`tree.write`, область
 * own_discipline); в «Завершена» и «Архив» и без связи — только просмотр. Окончательно права
 * проверяет сервер (403). Сверху — полоса проекта (FE-023); инструменты — FE-024.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { useSearchParam } from '../../app/router';

import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useReadOnlyOffline } from '../../shared/ws/WsProvider';
import { moneyKey } from '../settings/money/MoneySection';
import { membersKey } from '../settings/team/TeamSection';
import { useProject, type Project } from '../settings/useProject';
import type { TreeState } from './store/treeStore';
import { useProjectTree, useTree } from './store/useProjectTree';
import { TopBar, type OpenQuestion } from './topbar/TopBar';
import { TreeTable, type TreeContext, type TreeTableApi } from './tree/TreeTable';

type Member = components['schemas']['Member'];
type Money = components['schemas']['ProjectMoney'];

interface CommentLine {
  tag_id: string | null;
}

const READ_ONLY_STATUSES = new Set(['completed', 'archived']);

/** Правила правки веток для текущего пользователя. */
export function editRule(
  project: Project,
  members: readonly Member[],
  userId: string | null,
  offline: boolean,
): (disciplineId: string | null) => boolean {
  const mine = members.filter((m) => m.user.id === userId);
  const moderator = mine.some((m) => m.role === 'moderator');
  const disciplines = new Set(mine.filter((m) => m.role === 'expert').map((m) => m.discipline_id));
  const allowed = project.my_permissions.includes('tree.write') && !offline && !READ_ONLY_STATUSES.has(project.status);
  return (disciplineId) => allowed && (moderator || (disciplineId !== null && disciplines.has(disciplineId)));
}

/** Узлы с открытыми вопросами (счётчик «Открыто», 11.4 №3): сначала адресованные мне. */
export function openQuestions(state: Pick<TreeState, 'nodes'>): OpenQuestion[] {
  const out: OpenQuestion[] = [];
  for (const node of state.nodes.values()) {
    const extra = new Map(Object.entries(node.extra));
    const open = Number(extra.get('open_questions') ?? 0);
    if (open > 0)
      out.push({ nodeId: node.id, title: node.title, open, toMe: Number(extra.get('questions_to_me') ?? 0) });
  }
  return out.sort((a, b) => b.toMe - a.toMe || a.title.localeCompare(b.title, 'ru'));
}

/** Листья с меткой категории «Риск» в комментарии (счётчик рисков, 11.4 №3). */
export function riskCount(state: Pick<TreeState, 'nodes'>, riskTags: ReadonlySet<string>): number {
  let count = 0;
  for (const node of state.nodes.values()) {
    const lines = (new Map(Object.entries(node.extra)).get('comment_lines') ?? []) as CommentLine[] | null;
    if ((lines ?? []).some((l) => l.tag_id !== null && riskTags.has(l.tag_id))) count += 1;
  }
  return count;
}

export function WorkPage({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const client = useQueryClient();
  const tree = useProjectTree(project.data, (event) => {
    if (event.event === 'money.updated') void client.invalidateQueries({ queryKey: moneyKey(projectId) });
  });
  const tableRef = useRef<TreeTableApi>(null);
  const focusNode = useSearchParam('node');
  const offline = useReadOnlyOffline();
  const { session } = useSession();
  const userId = session.state === 'ready' ? session.me.id : null;

  const members = useQuery({
    queryKey: membersKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/members', { params: { path: { id: projectId } } })),
    select: (data) => data.items as Member[],
  });
  const nodeTypes = useQuery({
    queryKey: ['dict', 'node-types'],
    queryFn: () => call(() => api.GET('/admin/node-types')),
    staleTime: 10 * 60_000,
    select: (data) => new Map(data.items.map((n) => [n.id, { name: n.name, icon: n.icon }])),
  });
  const tags = useQuery({
    queryKey: ['dict', 'tags'],
    queryFn: () => call(() => api.GET('/admin/tags')),
    staleTime: 10 * 60_000,
    select: (data) => data.items,
  });
  const canMoney = project.data?.my_permissions.includes('money.read') ?? false;
  const money = useQuery({
    queryKey: moneyKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/money', { params: { path: { id: projectId } } })),
    select: (data) => data as Money,
    enabled: canMoney,
    retry: false,
  });
  const nodesRevision = useTree(tree.store, (s) => s.nodes);
  const riskTags = new Set((tags.data ?? []).filter((tag) => tag.category === 'risk').map((tag) => tag.id));
  const questions = openQuestions({ nodes: nodesRevision });
  const risks = riskCount({ nodes: nodesRevision }, riskTags);

  // ссылка из уведомления `?node=` открывает строку узла (FR-NOTIF-01)
  useEffect(() => {
    if (tree.loaded && focusNode) tableRef.current?.show(focusNode);
  }, [tree.loaded, focusNode]);

  if (project.error || tree.error) {
    return (
      <div className="main">
        <ErrorText error={project.error ?? tree.error} />
      </div>
    );
  }
  const data = project.data;
  if (!data || !tree.loaded) return <div className="main" aria-busy="true" />;

  const ctx: TreeContext = {
    canEdit: editRule(data, members.data ?? [], userId, offline),
    withoutExpert: new Set(data.disciplines.filter((d) => !d.has_expert).map((d) => d.discipline_id)),
    disciplineNames: new Map(data.disciplines.map((d) => [d.discipline_id, d.name])),
    nodeTypes: nodeTypes.data ?? new Map(),
    tags: new Map((tags.data ?? []).map((tag) => [tag.id, tag.short_name])),
    pmPercent: String(data.pm_percent),
    pmReason: data.pm_percent_reason ?? '',
    settingsHref: data.my_permissions.includes('project.settings.write') ? `/projects/${data.id}/settings` : null,
  };

  return (
    <div className="work-page">
      <TopBar
        project={data}
        store={tree.store}
        money={money.data}
        moneyError={money.error}
        questions={questions}
        risks={risks}
        onShowNode={(id) => tableRef.current?.show(id)}
        readOnly={offline}
      />
      <div className="work">
        <TreeTable store={tree.store} ctx={ctx} apiRef={tableRef} />
      </div>
    </div>
  );
}
