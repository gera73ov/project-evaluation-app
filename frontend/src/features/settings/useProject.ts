/**
 * FE-012 · данные настроек проекта: `GET /projects/{id}` (без денег), итоги дерева для «сейчас …»,
 * сохранение поля `PATCH /projects/{id}` и подписка на `project.updated` / `member.updated`.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { api, type components } from '../../shared/api/client';
import { ApiError, call } from '../../shared/api/problem';
import { useProjectChannel } from '../../shared/ws/WsProvider';

export type Project = components['schemas']['Project'];
/** Поля PATCH без `confirm`: его добавляет только повтор после диалога подтверждения. */
export type ProjectPatch = Omit<components['schemas']['ProjectPatch'], 'confirm'>;
type PatchBody = components['schemas']['ProjectPatch'];

export const projectKey = (id: string) => ['project', id] as const;

/** `onEvent` — прочие события проекта для экрана (подписка на проект у клиента WS одна). */
export function useProject(id: string, onEvent?: (event: { event: string; data?: unknown }) => void) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: projectKey(id),
    queryFn: () => call(() => api.GET('/projects/{id}', { params: { path: { id } } })),
  });
  const [revoked, setRevoked] = useState<string | null>(null);
  // правки других модераторов приходят событиями; перечитываем настройки и команду
  useProjectChannel(id, query.data?.version ?? null, {
    // FE-091: доступ отозван (исключили из команды, кончилась сессия поддержки) — экран закрывается
    onRevoked: (reason) => {
      setRevoked(reason || 'rights_changed');
      void client.cancelQueries({ queryKey: projectKey(id) });
    },
    onEvent: (event) => {
      if (event.event === 'project.updated' || event.event === 'member.updated') {
        void client.invalidateQueries({ queryKey: projectKey(id) });
        void client.invalidateQueries({ queryKey: ['members', id] });
      } else onEvent?.(event);
    },
    onResync: () => void client.invalidateQueries({ queryKey: projectKey(id) }),
  });
  return { ...query, data: query.data as Project | undefined, revoked };
}

/** Итоги дерева: часы E/P80/P90 проекта для подсказки «сейчас 425,5 ч». */
export function useTreeTotals(id: string) {
  return useQuery({
    queryKey: ['tree', id],
    queryFn: () => call(() => api.GET('/projects/{id}/tree', { params: { path: { id } } })),
    staleTime: 30_000,
    select: (tree) => tree.totals as components['schemas']['TreeTotals'],
  });
}

/** Запрос подтверждения от сервера: 409 CONFIRMATION_REQUIRED с числом затронутых объектов. */
export interface PendingConfirm {
  patch: PatchBody;
  affected: number;
  field: string;
}

/**
 * Сохранение одного поля при уходе фокуса. `saved` — имя поля, у которого 2 с горит
 * «✓ сохранено» (DESIGN.md 10.5); `confirm` — ждущее подтверждение выключения фазы.
 */
export function useProjectPatch(id: string) {
  const client = useQueryClient();
  const [saved, setSaved] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const mutation = useMutation({
    mutationFn: ({ patch }: { patch: PatchBody; field: string }) =>
      call(() => api.PATCH('/projects/{id}', { params: { path: { id } }, body: patch })),
    onSuccess: (result, { field }) => {
      client.setQueryData(projectKey(id), result.project as Project);
      void client.invalidateQueries({ queryKey: ['tree', id] });
      setConfirm(null);
      setSaved(field);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setSaved(null), 2000);
    },
    onError: (error, { patch, field }) => {
      if (error instanceof ApiError && error.code === 'CONFIRMATION_REQUIRED') {
        const affected = Number(error.extension('affected') ?? 0);
        setConfirm({ patch: { ...patch, confirm: true }, affected, field });
      }
    },
  });

  const needsConfirm = mutation.error instanceof ApiError && mutation.error.code === 'CONFIRMATION_REQUIRED';
  return {
    save: (field: string, patch: ProjectPatch) => mutation.mutate({ field, patch: { ...patch, confirm: false } }),
    retryConfirmed: (pending: PendingConfirm) => mutation.mutate({ field: pending.field, patch: pending.patch }),
    saved,
    busy: mutation.isPending,
    error: needsConfirm ? null : mutation.error,
    confirm,
    cancelConfirm: () => {
      setConfirm(null);
      mutation.reset();
    },
  };
}
