/**
 * FE-026 · захват ячеек по WebSocket (FR-TREE-31, TC-CONC-04; ws-events.md «Захват ячеек»).
 *
 * `lock` — при начале ввода (модератор может перехватить: `force`), `heartbeat` каждые 10 с
 * отправляет WS-клиент по списку своих захватов, `unlock` — при отмене, уходе без изменений и
 * после ответа на сохранение. Без WebSocket (тесты таблицы, нет связи) захват не мешает вводу:
 * без связи поля и так только для чтения, а окончательно захват проверяет сервер (423).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from 'zustand';

import { WsCommandError, type LockRef, type WsEvent } from '../../../shared/ws/client';
import { useWsClient } from '../../../shared/ws/WsProvider';
import { cellKey, type CellRef } from '../cells/useCells';
import { asPeer, createCollabStore, MARK_MS, type CollabState, type CollabStore, type Peer } from './collabStore';

export type LockResult = { ok: true } | { ok: false; lockedBy: Peer | null };

export interface Collab {
  store: CollabStore;
  /** Событие канала проекта (cell.*, presence, node.updated). */
  onEvent: (event: WsEvent) => void;
  lock: (cell: CellRef, force?: boolean) => Promise<LockResult>;
  unlock: (cell: CellRef) => void;
}

export function useCollab(projectId: string, selfId: string | null): Collab {
  const ws = useWsClient();
  const [store] = useState(createCollabStore);
  const own = useRef(new Map<string, LockRef>());

  useEffect(() => {
    if (!ws) return undefined;
    const mine = own.current;
    ws.setLockSource(() => [...mine.values()]);
    ws.setCallbacks({
      onLocksLost: (lost) => {
        for (const l of lost) mine.delete(`${l.node_id}:${l.field}`);
      },
    });
    return () => {
      // уход с экрана снимает свои захваты
      for (const l of mine.values()) ws.send({ op: 'unlock', project_id: projectId, ...l });
      mine.clear();
      ws.setLockSource(() => []);
    };
  }, [ws, projectId]);

  // метки чужих правок гаснут через 10 с
  useEffect(() => {
    const timer = setInterval(() => store.getState().prune(), 1000);
    return () => clearInterval(timer);
  }, [store]);

  return useMemo<Collab>(
    () => ({
      store,
      onEvent: (event) => {
        // перехват моего захвата модератором: сервер больше его не держит
        if (event.event === 'cell.unlocked') {
          const data = new Map(Object.entries(event.data));
          if (data.get('user_id') === selfId)
            own.current.delete(`${String(data.get('node_id'))}:${String(data.get('field'))}`);
        }
        store.getState().applyEvent(event, selfId);
      },
      lock: async (cell, force = false) => {
        if (!ws || ws.getStatus() !== 'open') return { ok: true };
        const ref = { node_id: cell.nodeId, field: cell.field };
        try {
          await ws.request({ op: 'lock', project_id: projectId, ...ref, ...(force ? { force: true } : {}) });
          own.current.set(cellKey(cell.nodeId, cell.field), ref);
          store.getState().setLock(cell.nodeId, cell.field, null);
          return { ok: true };
        } catch (error) {
          if (!(error instanceof WsCommandError) || error.code === 'OFFLINE') return { ok: true };
          const details = new Map(Object.entries(error.details));
          const lockedBy = error.code === 'CELL_LOCKED' ? asPeer(details.get('locked_by')) : null;
          if (lockedBy)
            store.getState().setLock(cell.nodeId, cell.field, {
              user: lockedBy,
              expiresAt: String(details.get('expires_at') ?? ''),
              forced: false,
            });
          return { ok: false, lockedBy };
        }
      },
      unlock: (cell) => {
        const key = cellKey(cell.nodeId, cell.field);
        const ref = own.current.get(key);
        if (!ref) return;
        own.current.delete(key);
        ws?.send({ op: 'unlock', project_id: projectId, ...ref });
      },
    }),
    [store, ws, projectId, selfId],
  );
}

export function useCollabState<T>(store: CollabStore, selector: (s: CollabState) => T): T {
  return useStore(store, selector);
}

export { MARK_MS };
