/**
 * FE-042 · общая обёртка вкладок статистики: шапка с вкладками, загрузка проекта и статистики,
 * ошибка. Содержимое вкладки получает проект, статистику и права.
 */
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { useProject } from '../../settings/useProject';
import { statsKey } from '../grid/ReadinessPage';
import { StatsHeader, type StatsTab } from '../StatsTabs';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];
type Tree = components['schemas']['Tree'];

export function useStats(projectId: string) {
  return useQuery({
    queryKey: statsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/stats', { params: { path: { id: projectId } } })),
    select: (data) => data as Stats,
  });
}

/** Дерево проекта (тот же ключ, что у сетки готовности) — для названий, путей и долей по фазе. */
export function useTree(projectId: string) {
  return useQuery({
    queryKey: ['tree', projectId],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id: projectId } } })),
    select: (data) => data as Tree,
    staleTime: 30_000,
  });
}

export function StatsShell({
  projectId,
  active,
  actions,
  children,
}: {
  projectId: string;
  active: StatsTab;
  actions?: (project: Project) => ReactNode;
  children: (data: { project: Project; stats: Stats; perms: readonly string[] }) => ReactNode;
}) {
  const project = useProject(projectId);
  const stats = useStats(projectId);
  const data = project.data;
  const perms = data?.my_permissions ?? [];
  return (
    <div className="settings stats">
      <StatsHeader
        projectId={projectId}
        projectName={data?.name ?? ''}
        active={active}
        canReadQuestions={perms.includes('cq.read')}
        actions={data && actions ? actions(data) : null}
      />
      {data && stats.data ? (
        children({ project: data, stats: stats.data, perms })
      ) : (
        <ErrorText error={project.error ?? stats.error} />
      )}
    </div>
  );
}
