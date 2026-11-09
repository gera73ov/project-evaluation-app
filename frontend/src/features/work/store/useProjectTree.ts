/**
 * FE-021 · дерево проекта в React: загрузка `GET /projects/{id}/tree`, подписка на канал проекта
 * с `since` = версии загруженного дерева, применение событий и ответов сервера.
 *
 * Подписка начинается только после загрузки дерева: иначе событие, пришедшее до ответа GET,
 * затёрлось бы загрузкой. `resync` перезагружает дерево целиком (ws-events.md, «Версии и догрузка»).
 */
import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useStore } from 'zustand';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import type { WsEvent } from '../../../shared/ws/client';
import { useProjectChannel, useWsClient } from '../../../shared/ws/WsProvider';
import { createTreeStore, settingsOf, type TreeEvent, type TreeState, type TreeStore } from './treeStore';

type Project = components['schemas']['Project'];

const TREE_EVENTS = new Set([
  'node.created',
  'node.updated',
  'node.moved',
  'node.deleted',
  'node.restored',
  'branch.status',
]);

export interface ProjectTree {
  store: TreeStore;
  loaded: boolean;
  error: Error | null;
  /** Ответ сервера на правку узла: применить и сообщить WS-клиенту версию. */
  confirm: (node: components['schemas']['Node'], projectVersion: number) => void;
  reload: () => Promise<void>;
}

/**
 * `onOtherEvent` — остальные события каналов проекта (деньги, обсуждения): у WS-клиента одна
 * подписка на проект, поэтому все события приходят сюда.
 */
export function useProjectTree(project: Project | undefined, onOtherEvent?: (event: WsEvent) => void): ProjectTree {
  const projectId = project?.id ?? null;
  const ws = useWsClient();
  const [store] = useState(createTreeStore);
  const version = useStore(store, (s) => s.version);
  const loaded = useStore(store, (s) => s.settings !== null);
  const tree = useQuery({
    queryKey: ['tree', projectId, 'full'],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id: projectId ?? '' } } })),
    enabled: projectId !== null,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  // свежая выдача дерева заменяет хранилище; правка настроек меняет только расчёт
  const projectRef = useRef(project);
  useLayoutEffect(() => {
    projectRef.current = project;
  });
  useEffect(() => {
    const current = projectRef.current;
    if (!tree.data || !current) return;
    store.getState().load(tree.data as components['schemas']['Tree'], settingsOf(current));
    ws?.markApplied(current.id, store.getState().version);
  }, [tree.data, tree.dataUpdatedAt, store, ws]);
  useEffect(() => {
    if (project && store.getState().settings) store.getState().setSettings(settingsOf(project));
  }, [project, store]);

  useProjectChannel(loaded ? projectId : null, loaded ? version : null, {
    onEvent: (event) => {
      if (!TREE_EVENTS.has(event.event) || typeof event.project_version !== 'number') {
        onOtherEvent?.(event);
        return;
      }
      store.getState().applyEvent(event as unknown as TreeEvent);
    },
    onResync: () => void tree.refetch(),
  });

  const confirm = useCallback(
    (node: components['schemas']['Node'], projectVersion: number) => {
      store.getState().applyNode(node, projectVersion);
      if (projectId) ws?.markApplied(projectId, projectVersion);
    },
    [projectId, store, ws],
  );

  return {
    store,
    loaded,
    error: tree.error,
    confirm,
    reload: async () => {
      await tree.refetch();
    },
  };
}

/** Выборка из хранилища дерева с подпиской на изменения. */
export function useTree<T>(store: TreeStore, selector: (state: TreeState) => T): T {
  return useStore(store, selector);
}
