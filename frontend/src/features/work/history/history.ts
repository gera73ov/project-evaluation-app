/**
 * FE-028 · история листа (FR-TREE-25, 11.5 №3): записи `getNodeHistory` → строки панели.
 *
 * Сервер отдаёт по каждой записи только изменённые поля `{поле: [было, стало]}`. Чтобы показать
 * вилку целиком («30–40–60 → 40–60–100») и что вернёт «Вернуть», история проходится от текущих
 * значений листа назад во времени: «стало» записи — состояние после неё, «было» — до неё.
 */
import type { components } from '../../../shared/api/client';
import { sameHours } from '../cells/useCells';

export type HistoryEntry = components['schemas']['HistoryEntry'];

export interface Fork {
  o: string | null;
  r: string | null;
  p: string | null;
}

export type HistoryKind =
  | 'fork'
  | 'create'
  | 'comment'
  | 'title'
  | 'multiplier'
  | 'type'
  | 'move'
  | 'split'
  | 'collapse'
  | 'review'
  | 'delete'
  | 'restore'
  | 'other';

export interface HistoryRow {
  entry: HistoryEntry;
  kind: HistoryKind;
  /** Вилка до и после записи (для `fork`, `create`, `split`, `collapse`). */
  before: Fork;
  after: Fork;
  /** Было → стало для одного поля (название, ×N, тип, комментарий). */
  was: unknown;
  now: unknown;
  /** Значение после записи совпадает с текущим: серая «текущее» вместо кнопки. */
  current: boolean;
  /** Вилку этой записи можно вернуть новой правкой. */
  revert: Fork | null;
}

const FORK = ['o', 'r', 'p'] as const;

const text = (value: unknown): string | null =>
  value === null || value === undefined ? null : String(value as string);

export function sameFork(a: Fork, b: Fork): boolean {
  return FORK.every((f) => {
    const x = f === 'o' ? a.o : f === 'r' ? a.r : a.p;
    const y = f === 'o' ? b.o : f === 'r' ? b.r : b.p;
    return x === y || (x !== null && y !== null && sameHours(x, y));
  });
}

const complete = (fork: Fork) => fork.o !== null && fork.r !== null && fork.p !== null;

function kindOf(entry: HistoryEntry, changes: ReadonlyMap<string, unknown>): HistoryKind {
  if (entry.action !== 'update') return entry.action;
  if (FORK.some((f) => changes.has(f))) return 'fork';
  if (changes.has('comment_lines')) return 'comment';
  if (changes.has('title')) return 'title';
  if (changes.has('multiplier')) return 'multiplier';
  if (changes.has('type_id')) return 'type';
  return 'other';
}

/** Строки панели истории; `entries` — от новых к старым, как отдаёт сервер. */
export function historyRows(entries: readonly HistoryEntry[], current: Fork): HistoryRow[] {
  let state: Fork = { ...current };
  let currentShown = false;
  return entries.map((entry) => {
    const changes = new Map(Object.entries(entry.changes as Record<string, unknown>));
    const pair = (field: string): [unknown, unknown] => {
      const value = changes.get(field);
      return Array.isArray(value) ? [value.at(0), value.at(1)] : [undefined, undefined];
    };
    const after = { ...state };
    const before: Fork =
      entry.action === 'create'
        ? { o: null, r: null, p: null }
        : {
            o: changes.has('o') ? text(pair('o')[0]) : state.o,
            r: changes.has('r') ? text(pair('r')[0]) : state.r,
            p: changes.has('p') ? text(pair('p')[0]) : state.p,
          };
    state = before;
    const kind = kindOf(entry, changes);
    const field =
      kind === 'comment'
        ? 'comment_lines'
        : kind === 'title'
          ? 'title'
          : kind === 'multiplier'
            ? 'multiplier'
            : 'type_id';
    const [was, now] = pair(field);
    const forkRow = kind === 'fork' || kind === 'create' || kind === 'split' || kind === 'collapse';
    const isCurrent = forkRow && !currentShown && sameFork(after, current);
    if (forkRow) currentShown = true;
    return {
      entry,
      kind,
      before,
      after,
      was,
      now,
      current: isCurrent,
      revert: forkRow && !isCurrent && complete(after) && !sameFork(after, current) ? after : null,
    };
  });
}
