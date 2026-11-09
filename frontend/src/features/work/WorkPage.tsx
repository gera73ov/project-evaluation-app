/**
 * FE-022 · рабочий экран проекта `/projects/:id` (SPEC 8.4, 11.4; DESIGN.md 9): дерево оценки.
 *
 * Кто что правит: модератор — все ветки, эксперт — ветки своих дисциплин (`tree.write`, область
 * own_discipline); в «Завершена» и «Архив» и без связи — только просмотр. Окончательно права
 * проверяет сервер (403). Сверху — полоса проекта (FE-023), под ней — поиск и фильтры (FE-024);
 * свёртка и фильтры сохраняются на сервере (FR-TREE-14).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { useSearchParam } from '../../app/router';

import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { DEFAULT_LARGE_LEAF_HOURS, largeLeafThreshold } from '../../shared/calc';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useReadOnlyOffline } from '../../shared/ws/WsProvider';
import { moneyKey } from '../settings/money/MoneySection';
import { membersKey } from '../settings/team/TeamSection';
import { useProject, type Project } from '../settings/useProject';
import { useCollab, useCollabState, type Collab } from './collab/useCollab';
import { FilterBar } from './filters/FilterBar';
import type { MenuSetup } from './menu/useRowMenus';
import { localTypesKey, useTreeOps } from './menu/useTreeOps';
import {
  chipCounts,
  collapseTo,
  unaccountedLeaves,
  visibleNodes,
  type FilterInput,
  type FilterKey,
} from './filters/filters';
import { parseView, useSaveView, useSavedView, type WorkView } from './filters/viewState';
import type { TreeState, TreeStore } from './store/treeStore';
import { useProjectTree, useTree } from './store/useProjectTree';
import { TopBar, type OpenQuestion } from './topbar/TopBar';
import { TreeTable, type TreeContext, type TreeTableApi } from './tree/TreeTable';

type Member = components['schemas']['Member'];
type Money = components['schemas']['ProjectMoney'];
type NodeType = components['schemas']['NodeType'];

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

/** Дисциплины «моих веток»: экспертные связи; модератор без них — все ветки (null). */
export function myDisciplines(members: readonly Member[], userId: string | null): ReadonlySet<string> | null {
  const mine = members.filter((m) => m.user.id === userId);
  const expert = new Set(
    mine.filter((m) => m.role === 'expert' && m.discipline_id).map((m) => m.discipline_id as string),
  );
  if (expert.size) return expert;
  return mine.some((m) => m.role === 'moderator') ? null : expert;
}

export function WorkPage({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const client = useQueryClient();
  const { session } = useSession();
  const userId = session.state === 'ready' ? session.me.id : null;
  const collab = useCollab(projectId, userId);
  const tree = useProjectTree(
    project.data,
    (event) => {
      if (event.event === 'money.updated') void client.invalidateQueries({ queryKey: moneyKey(projectId) });
      else collab.onEvent(event);
    },
    collab.onEvent,
  );
  const members = useQuery({
    queryKey: membersKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/members', { params: { path: { id: projectId } } })),
    select: (data) => data.items as Member[],
  });
  const saved = useSavedView(projectId);

  if (project.error || tree.error) {
    return (
      <div className="main">
        <ErrorText error={project.error ?? tree.error} />
      </div>
    );
  }
  const data = project.data;
  const ready = data && tree.loaded && !members.isPending && !saved.isPending;
  if (!ready) return <div className="main" aria-busy="true" />;
  const list = members.data ?? [];
  const isModerator = list.some((m) => m.user.id === userId && m.role === 'moderator');
  const isExpert = list.some((m) => m.user.id === userId && m.role === 'expert');
  // «Мои ветки» при первом входе: включён у эксперта, выключен у модератора (11.4 №5)
  const initial = parseView(saved.data, isExpert && !isModerator);
  return (
    <WorkScreen
      project={data}
      store={tree.store}
      confirm={tree.confirm}
      confirmMutation={tree.confirmMutation}
      collab={collab}
      members={list}
      userId={userId}
      moderator={isModerator}
      initial={initial}
    />
  );
}

function WorkScreen({
  project: data,
  store,
  confirm,
  confirmMutation,
  collab,
  members,
  userId,
  moderator,
  initial,
}: {
  project: Project;
  store: TreeStore;
  confirm: ReturnType<typeof useProjectTree>['confirm'];
  confirmMutation: ReturnType<typeof useProjectTree>['confirmMutation'];
  collab: Collab;
  members: Member[];
  userId: string | null;
  moderator: boolean;
  initial: WorkView;
}) {
  const { t } = useTranslation();
  const projectId = data.id;
  const tableRef = useRef<TreeTableApi>(null);
  const focusNode = useSearchParam('node');
  const offline = useReadOnlyOffline();
  const [view, setView] = useState<WorkView>(initial);
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  useSaveView(projectId, view);

  const nodeTypes = useQuery({
    queryKey: ['dict', 'node-types'],
    queryFn: () => call(() => api.GET('/admin/node-types')),
    staleTime: 10 * 60_000,
    select: (data) =>
      new Map(
        data.items.map((n) => [
          n.id,
          {
            name: n.name,
            icon: n.icon,
            active: n.is_active,
            norms: n.norms.map((m) => ({ ...m, o: String(m.o), r: String(m.r), p: String(m.p) })),
          },
        ]),
      ),
  });
  // локальные типы проекта, созданные в этой сессии (список с сервера — после CR-006)
  const localTypes = useQuery({
    queryKey: localTypesKey(projectId),
    queryFn: () => [] as NodeType[],
    staleTime: Infinity,
  });
  const profiles = useQuery({
    queryKey: ['dict', 'profiles'],
    queryFn: () => call(() => api.GET('/admin/profiles')),
    staleTime: 10 * 60_000,
    select: (data) => data.items.filter((p) => p.is_active),
  });
  const ops = useTreeOps({ projectId, store, confirmMutation });
  const tags = useQuery({
    queryKey: ['dict', 'tags'],
    queryFn: () => call(() => api.GET('/admin/tags')),
    staleTime: 10 * 60_000,
    select: (data) => data.items,
  });
  const canMoney = data.my_permissions.includes('money.read');
  const money = useQuery({
    queryKey: moneyKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/money', { params: { path: { id: projectId } } })),
    select: (data) => data as Money,
    enabled: canMoney,
    retry: false,
  });
  const locks = useCollabState(collab.store, (s) => s.locks);
  const marks = useCollabState(collab.store, (s) => s.marks);
  const presence = useCollabState(collab.store, (s) => s.presence);
  const nodesRevision = useTree(store, (s) => s.nodes);
  const revision = useTree(store, (s) => s.revision);
  const riskList = (tags.data ?? []).filter((tag) => tag.category === 'risk').map((tag) => tag.id);
  const riskKey = riskList.join(',');
  const riskTags = useMemo(() => new Set(riskKey ? riskKey.split(',') : []), [riskKey]);
  const questions = openQuestions({ nodes: nodesRevision });
  const risks = riskCount({ nodes: nodesRevision }, riskTags);

  const { calc } = store.getState();
  const detailLevel = data.detail_level;
  const mineKey = [...(myDisciplines(members, userId) ?? ['*'])].join(',');
  const input = useMemo<FilterInput>(
    () => ({
      myDisciplines: mineKey === '*' ? null : new Set(mineKey ? mineKey.split(',') : []),
      largeThreshold: largeLeafThreshold(detailLevel, DEFAULT_LARGE_LEAF_HOURS),
      riskTags,
    }),
    [mineKey, detailLevel, riskTags],
  );
  const visible = useMemo(
    () => (calc ? visibleNodes(calc, nodesRevision, view.filters, deferredQuery, input) : null),
    // revision меняется при каждом пересчёте дерева
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [revision, nodesRevision, view.filters, deferredQuery, input],
  );
  const counts = useMemo(
    () => (calc ? chipCounts(calc, nodesRevision, input) : new Map<FilterKey, number>()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [revision, nodesRevision, input],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const unaccounted = useMemo(() => (calc ? unaccountedLeaves(calc) : { empty: 0, invalid: 0 }), [revision]);

  const toggleFilter = (key: FilterKey) =>
    setView((v) => {
      const filters = new Set(v.filters);
      if (filters.has(key)) filters.delete(key);
      else filters.add(key);
      return { ...v, filters };
    });
  const showNode = (id: string) => {
    // строка, скрытая фильтром, показывается после сброса фильтров и поиска
    if (visible && !visible.has(id)) {
      setView((v) => ({ ...v, filters: new Set() }));
      setQuery('');
    }
    tableRef.current?.show(id);
  };

  // ссылка из уведомления `?node=` открывает строку узла (FR-NOTIF-01)
  useEffect(() => {
    if (focusNode) tableRef.current?.show(focusNode);
  }, [focusNode]);

  const allTypes = new Map(nodeTypes.data ?? []);
  for (const local of localTypes.data ?? [])
    allTypes.set(local.id, { name: local.name, icon: local.icon, active: true, norms: [] });
  const localIds = new Set((localTypes.data ?? []).map((l) => l.id));
  const typeName = (id: string) => allTypes.get(id)?.name ?? '?';
  const perms = new Set(data.my_permissions);
  const menus: MenuSetup = {
    projectId,
    ops,
    crossBranch: perms.has('tree.move.cross_branch'),
    config: {
      types: [...allTypes]
        .filter(([, type]) => type.active)
        .map(([id, type]) => ({ id, name: type.name, icon: type.icon, local: localIds.has(id) })),
      chainOf: (disciplineId) => {
        const profileId = data.disciplines.find((d) => d.discipline_id === disciplineId)?.profile_id;
        return profiles.data?.find((p) => p.id === profileId)?.type_chain ?? [];
      },
      can: {
        localType: perms.has('node_type.create_local'),
        profile: perms.has('branch.profile.write'),
        copyFrom: perms.has('branch.copy_from'),
      },
    },
    profilesOf: (disciplineId) =>
      (profiles.data ?? [])
        .filter((p) => p.discipline_id === disciplineId)
        .map((p) => ({ id: p.id, name: p.name, chain: p.type_chain.map(typeName).join(' → ') })),
    profileOf: (disciplineId) => data.disciplines.find((d) => d.discipline_id === disciplineId)?.profile_id ?? null,
  };
  const ctx: TreeContext = {
    roleOf: (id) => (members.some((m) => m.user.id === id && m.role === 'moderator') ? t('history.moderator') : null),
    highlight: deferredQuery,
    collab: { locks, marks, canForce: data.my_permissions.includes('tree.lock.force') },
    canEdit: editRule(data, members, userId, offline),
    withoutExpert: new Set(data.disciplines.filter((d) => !d.has_expert).map((d) => d.discipline_id)),
    disciplineNames: new Map(data.disciplines.map((d) => [d.discipline_id, d.name])),
    nodeTypes: allTypes,
    tags: new Map((tags.data ?? []).map((tag) => [tag.id, tag.short_name])),
    pmPercent: String(data.pm_percent),
    pmReason: data.pm_percent_reason ?? '',
    settingsHref: data.my_permissions.includes('project.settings.write') ? `/projects/${data.id}/settings` : null,
  };

  return (
    <div className="work-page">
      <TopBar
        project={data}
        store={store}
        money={money.data}
        moneyError={money.error}
        questions={questions}
        risks={risks}
        onShowNode={showNode}
        onRiskFilter={() => toggleFilter('risk')}
        presence={presence.filter((p) => p.id !== userId)}
        readOnly={offline}
      />
      <FilterBar
        query={query}
        onQuery={setQuery}
        filters={view.filters}
        onToggle={toggleFilter}
        counts={counts}
        moderator={moderator}
        unaccounted={unaccounted}
        onCollapse={(level) =>
          setView((v) => ({ ...v, collapsed: level === 'none' || !calc ? new Set() : collapseTo(calc, level) }))
        }
      />
      <div className="work">
        {visible && visible.size === 0 ? (
          <div className="tools-nothing">
            {t('filters.nothing')}{' '}
            <button
              type="button"
              className="btn-sm"
              onClick={() => {
                setView((v) => ({ ...v, filters: new Set() }));
                setQuery('');
              }}
            >
              {t('filters.reset')}
            </button>
          </div>
        ) : null}
        <TreeTable
          store={store}
          ctx={ctx}
          apiRef={tableRef}
          collapsed={view.collapsed}
          onCollapsedChange={(collapsed) => setView((v) => ({ ...v, collapsed }))}
          visible={visible}
          onConfirm={confirm}
          locking={collab}
          menus={menus}
        />
      </div>
    </div>
  );
}
