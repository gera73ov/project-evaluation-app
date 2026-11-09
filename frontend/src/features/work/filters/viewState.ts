/**
 * FE-024 · состояние вида дерева на сервере (FR-TREE-14, `/me/view-state/{project_id}`): свёрнутые
 * узлы и включённые фильтры. Поиск не сохраняется. Ширины столбцов пока фиксированы (FE-022),
 * поэтому в состоянии их нет.
 *
 * Сервер принимает до 64 КБ: список свёрнутых узлов обрезается до {@link MAX_COLLAPSED}.
 */
import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { FILTER_KEYS, type FilterKey } from './filters';

export interface WorkView {
  collapsed: ReadonlySet<string>;
  filters: ReadonlySet<FilterKey>;
}

/** 1 400 uuid ≈ 55 КБ JSON — с запасом до 64 КБ. */
export const MAX_COLLAPSED = 1400;
const SAVE_DELAY_MS = 800;

export const viewStateKey = (projectId: string) => ['view-state', projectId] as const;

/**
 * Разбор сохранённого состояния. Пустое состояние — первый вход: «Мои ветки» включён у эксперта
 * и выключен у модератора (11.4 №5).
 */
export function parseView(state: unknown, firstVisitMine: boolean): WorkView {
  const map = new Map(Object.entries(state && typeof state === 'object' ? state : {}));
  const known = new Set<string>(FILTER_KEYS);
  const rawFilters = map.get('filters');
  const filters = Array.isArray(rawFilters)
    ? new Set(rawFilters.filter((k): k is FilterKey => typeof k === 'string' && known.has(k)))
    : new Set<FilterKey>(firstVisitMine ? ['mine'] : []);
  const rawCollapsed = map.get('collapsed');
  const collapsed = new Set(
    Array.isArray(rawCollapsed) ? rawCollapsed.filter((id): id is string => typeof id === 'string') : [],
  );
  return { collapsed, filters };
}

export function serializeView(view: WorkView): { collapsed: string[]; filters: FilterKey[] } {
  return { collapsed: [...view.collapsed].slice(0, MAX_COLLAPSED), filters: [...view.filters] };
}

/** Сохранённое состояние; ошибка чтения — как первый вход (вид не важнее дерева). */
export function useSavedView(projectId: string) {
  return useQuery({
    queryKey: viewStateKey(projectId),
    queryFn: () => call(() => api.GET('/me/view-state/{project_id}', { params: { path: { project_id: projectId } } })),
    select: (data) => data.state as unknown,
    staleTime: Infinity,
    retry: false,
  });
}

/** Сохраняет вид с задержкой после последнего изменения; первое значение не отправляется. */
export function useSaveView(projectId: string, view: WorkView) {
  const body = JSON.stringify(serializeView(view));
  const saved = useRef(body);
  useEffect(() => {
    if (body === saved.current) return;
    const timer = setTimeout(() => {
      saved.current = body;
      void api.PUT('/me/view-state/{project_id}', {
        params: { path: { project_id: projectId } },
        body: { state: JSON.parse(body) as Record<string, never> },
      });
    }, SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [projectId, body]);
}
