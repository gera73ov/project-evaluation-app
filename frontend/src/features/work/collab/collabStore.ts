/**
 * FE-026 · что делают в проекте другие (FR-TREE-30, FR-TREE-31, 11.4 №4, №8; ws-events.md).
 *
 * Чужие захваты ячеек (`cell.locked` / `cell.unlocked`), метки чужих правок (`node.updated` с
 * автором: подсветка строки 2 с и «АС изменил» 10 с, DESIGN.md 9.7) и кто сейчас в проекте
 * (`presence`).
 * Свои захваты и свои правки сюда не попадают.
 */
import { createStore, type StoreApi } from 'zustand/vanilla';

import type { WsEvent } from '../../../shared/ws/client';
import { cellKey, type CellField } from '../cells/useCells';

export interface Peer {
  id: string;
  full_name: string;
  initials: string;
  color?: string;
}

export interface CellLock {
  user: Peer;
  expiresAt: string;
  forced: boolean;
}

export interface CellMark {
  user: Peer;
  /** Время правки, мс. */
  at: number;
}

/** Метка автора держится 10 с, подсветка строки — 2 с (CSS-анимация). */
export const MARK_MS = 10_000;

const CELL_FIELDS = new Map<string, CellField>([
  ['o', 'o'],
  ['r', 'r'],
  ['p', 'p'],
  ['multiplier', 'multiplier'],
  ['comment', 'comment'],
  ['comment_lines', 'comment'],
]);

export interface CollabState {
  /** Захваты по `cellKey(узел, поле)`. */
  locks: ReadonlyMap<string, CellLock>;
  /** Метки чужих правок по id узла. */
  marks: ReadonlyMap<string, CellMark>;
  presence: readonly Peer[];
}

export interface CollabActions {
  /** Применить событие канала проекта; `selfId` — свои события пропускаются. */
  applyEvent(event: Pick<WsEvent, 'event' | 'data'>, selfId: string | null, now?: number): void;
  setLock(nodeId: string, field: CellField, lock: CellLock | null): void;
  /** Снять метки старше {@link MARK_MS}. */
  prune(now?: number): void;
}

export type CollabStore = StoreApi<CollabState & CollabActions>;

/** UserRef из события или ошибки WS. */
export function asPeer(value: unknown): Peer | null {
  if (!value || typeof value !== 'object') return null;
  const map = new Map(Object.entries(value));
  const id = map.get('id');
  if (typeof id !== 'string') return null;
  const color = map.get('color');
  return {
    id,
    full_name: String(map.get('full_name') ?? ''),
    initials: String(map.get('initials') ?? ''),
    ...(typeof color === 'string' ? { color } : {}),
  };
}

export function createCollabStore(): CollabStore {
  return createStore<CollabState & CollabActions>()((set, get) => ({
    locks: new Map(),
    marks: new Map(),
    presence: [],

    applyEvent(event, selfId, now = Date.now()) {
      const data = new Map(Object.entries(event.data));
      switch (event.event) {
        case 'cell.locked': {
          const user = asPeer(data.get('user'));
          const field = CELL_FIELDS.get(String(data.get('field')));
          if (!user || !field || user.id === selfId) return;
          get().setLock(String(data.get('node_id')), field, {
            user,
            expiresAt: String(data.get('expires_at') ?? ''),
            forced: data.get('forced') === true,
          });
          return;
        }
        case 'cell.unlocked': {
          const field = CELL_FIELDS.get(String(data.get('field')));
          if (field) get().setLock(String(data.get('node_id')), field, null);
          return;
        }
        case 'presence': {
          const users = data.get('users');
          set({ presence: (Array.isArray(users) ? users : []).map(asPeer).filter((p): p is Peer => p !== null) });
          return;
        }
        case 'node.updated': {
          const author = asPeer(data.get('author'));
          const node = data.get('node') as { id?: unknown } | undefined;
          const changed = data.get('changed_fields');
          if (!author || author.id === selfId || typeof node?.id !== 'string') return;
          const marks = new Map(get().marks).set(node.id, { user: author, at: now });
          const locks = new Map(get().locks);
          for (const name of Array.isArray(changed) ? changed : []) {
            const field = CELL_FIELDS.get(String(name));
            // правка сохранена — захват автора снят (reason: saved), даже если событие unlock опоздало
            if (field) locks.delete(cellKey(node.id, field));
          }
          set({ marks, locks });
          return;
        }
      }
    },

    setLock(nodeId, field, lock) {
      const locks = new Map(get().locks);
      if (lock) locks.set(cellKey(nodeId, field), lock);
      else locks.delete(cellKey(nodeId, field));
      set({ locks });
    },

    prune(now = Date.now()) {
      const marks = [...get().marks].filter(([, m]) => now - m.at < MARK_MS);
      if (marks.length !== get().marks.size) set({ marks: new Map(marks) });
    },
  }));
}
