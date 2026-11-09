/**
 * FE-022 · рабочий экран проекта `/projects/:id` (SPEC 8.4, 11.4; DESIGN.md 9): дерево оценки.
 *
 * Кто что правит: модератор — все ветки, эксперт — ветки своих дисциплин (`tree.write`, область
 * own_discipline); в «Завершена» и «Архив» и без связи — только просмотр. Окончательно права
 * проверяет сервер (403). Верхняя полоса — FE-023, инструменты — FE-024.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useReadOnlyOffline } from '../../shared/ws/WsProvider';
import { membersKey } from '../settings/team/TeamSection';
import { useProject, type Project } from '../settings/useProject';
import { useProjectTree } from './store/useProjectTree';
import { TreeTable, type TreeContext } from './tree/TreeTable';

type Member = components['schemas']['Member'];

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

export function WorkPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const project = useProject(projectId);
  const tree = useProjectTree(project.data);
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
    select: (data) => new Map(data.items.map((tag) => [tag.id, tag.short_name])),
  });

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
    tags: tags.data ?? new Map(),
    pmPercent: String(data.pm_percent),
    pmReason: data.pm_percent_reason ?? '',
    settingsHref: data.my_permissions.includes('project.settings.write') ? `/projects/${data.id}/settings` : null,
  };

  return (
    <div className="work">
      <h1 className="sr-only">{t('tree.title', { name: data.name })}</h1>
      <TreeTable store={tree.store} ctx={ctx} />
    </div>
  );
}
