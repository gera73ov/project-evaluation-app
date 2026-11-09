/**
 * FE-025 · ввод в ячейки дерева (FR-TREE-20…22, FR-TREE-02, 11.4 «Ввод с клавиатуры»).
 *
 * Одна ячейка в правке за раз. Enter и уход фокуса сохраняют, Esc отменяет, Tab идёт
 * O → R → P → Комментарий → O следующего листа (Shift+Tab — назад). Сохранение на лету:
 * значения O/R/P/×N сразу попадают в расчёт (оптимистично, ячейка «сохраняется»), запрос —
 * `PATCH /nodes/{id}` с `base_version`. При ошибке значение снимается из расчёта, а в ячейке
 * остаётся введённый текст с красной рамкой и текстом ошибки.
 *
 * FE-026: при начале ввода ячейка захватывается (`lock`), при уходе без изменений и после ответа
 * на сохранение — освобождается; 409 `FIELD_CONFLICT` открывает выбор «Оставить моё» / «Принять»,
 * 423 `CELL_LOCKED` — текст «Сейчас редактирует …».
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { ApiError, call, errorMessage } from '../../../shared/api/problem';
import { dec } from '../../../shared/calc';
import { formatHoursInput } from '../../../shared/format/number';
import type { EditableField, NodeEdit, TreeStore } from '../store/treeStore';
import { parseFork, parseHours, parseMultiplier } from './hours';

type ApiNode = components['schemas']['Node'];
type Changes = components['schemas']['NodeChanges'];
export type CommentLine = components['schemas']['CommentLine'];

export type CellField = 'o' | 'r' | 'p' | 'comment' | 'multiplier';
export type Direction = 1 | -1;

/** Порядок Tab внутри листа; ×N в него не входит (11.4). */
export const TAB_ORDER: readonly CellField[] = ['o', 'r', 'p', 'comment'];

export interface CellRef {
  nodeId: string;
  field: CellField;
}

export interface CellError {
  message: string;
  /** Введённый текст, который не сохранился. */
  draft: string;
}

export const cellKey = (nodeId: string, field: CellField) => `${nodeId}:${field}`;

/** Одинаковые часы: «12» и «12.00» — одно значение. */
export function sameHours(a: string | null, b: string | null): boolean {
  return a === null || b === null ? a === b : dec(a).eq(dec(b));
}

/** Подсказка «округлено до …» держится 4 с. */
const HINT_MS = 4000;

/** Следующая ячейка по Tab: внутри листа, затем первая ячейка следующего листа. */
export function nextCell(leaves: readonly string[], from: CellRef, dir: Direction): CellRef | null {
  const at = TAB_ORDER.indexOf(from.field);
  const inLeaf = TAB_ORDER.at(at + dir);
  if (at >= 0 && inLeaf && at + dir >= 0) return { nodeId: from.nodeId, field: inLeaf };
  const index = leaves.indexOf(from.nodeId);
  const next = index >= 0 ? leaves.at(index + dir) : undefined;
  if (next === undefined || index + dir < 0) return null;
  const field = dir > 0 ? TAB_ORDER[0] : TAB_ORDER.at(-1);
  return field ? { nodeId: next, field } : null;
}

/** Конфликт того же поля (FR-TREE-32): чужое значение и моё. */
export interface CellConflict {
  nodeId: string;
  items: { field: string; current: string | null; yours: string; changedBy: string }[];
}

export type LockResult = { ok: true } | { ok: false; lockedBy: { full_name: string } | null };

interface PendingSend {
  nodeId: string;
  changes: Changes;
  drafts: Map<CellField, string>;
  held: CellRef | null;
  currentVersion: number;
}

export interface CellsApi {
  editing: CellRef | null;
  conflict: CellConflict | null;
  /** «Оставить моё» — повтор с текущей версией, «Принять» — снять своё значение. */
  resolveConflict: (choice: 'mine' | 'theirs') => void;
  errors: ReadonlyMap<string, CellError>;
  hints: ReadonlyMap<string, string>;
  /** Узлы, чей комментарий ещё сохраняется. */
  savingComments: ReadonlySet<string>;
  /** Начать ввод; `force` — модератор перехватывает чужую ячейку. */
  start: (cell: CellRef, force?: boolean) => void;
  cancel: () => void;
  /**
   * Сохранить текст ячейки и уйти: `dir` — Tab вперёд/назад, null — Enter или уход фокуса.
   * `false` — текст не разобран, ячейка остаётся в правке с ошибкой.
   */
  commit: (cell: CellRef, text: string, dir: Direction | null) => boolean;
  saveComment: (nodeId: string, lines: CommentLine[] | null, dir: Direction | null) => void;
  /** Подставить норму в пустой лист (FR-TREE-02). */
  applyNorm: (nodeId: string, norm: { o: string; r: string; p: string }) => void;
}

export function useCells({
  store,
  confirm,
  leaves,
  onMove,
  lock,
  unlock,
}: {
  store: TreeStore;
  confirm: (node: ApiNode, projectVersion: number) => void;
  /** Листья, которые пользователь может править, в порядке строк. */
  leaves: readonly string[];
  /** Ячейка стала активной (прокрутить к строке). */
  onMove?: (cell: CellRef) => void;
  /** Захват ячейки (FE-026); без него ввод не захватывает ячейки. */
  lock?: (cell: CellRef, force?: boolean) => Promise<LockResult>;
  unlock?: (cell: CellRef) => void;
}): CellsApi {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<CellRef | null>(null);
  const [errors, setErrors] = useState<ReadonlyMap<string, CellError>>(new Map());
  const [hints, setHints] = useState<ReadonlyMap<string, string>>(new Map());
  const [savingComments, setSavingComments] = useState<ReadonlySet<string>>(new Set());
  const [conflict, setConflict] = useState<(CellConflict & { retry: PendingSend }) | null>(null);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const setError = (key: string, error: CellError | null) =>
    setErrors((prev) => {
      const next = new Map(prev);
      if (error) next.set(key, error);
      else next.delete(key);
      return next;
    });

  const hint = (key: string, text: string) => {
    setHints((prev) => new Map(prev).set(key, text));
    const old = timers.current.get(key);
    if (old) clearTimeout(old);
    timers.current.set(
      key,
      setTimeout(() => {
        timers.current.delete(key);
        setHints((prev) => {
          const next = new Map(prev);
          next.delete(key);
          return next;
        });
      }, HINT_MS),
    );
  };

  /** Начать ввод в ячейку и захватить её; занятая другим ячейка ввод не начинает. */
  const begin = (cell: CellRef, force = false) => {
    setEditing(cell);
    if (!lock) return;
    void lock(cell, force).then((result) => {
      if (result.ok) return;
      setEditing((now) => (now && now.nodeId === cell.nodeId && now.field === cell.field ? null : now));
      if (result.lockedBy)
        hint(cellKey(cell.nodeId, cell.field), t('cells.lockedBy', { name: result.lockedBy.full_name }));
    });
  };

  const go = (from: CellRef, dir: Direction | null) => {
    const to = dir === null ? null : nextCell(leaves, from, dir);
    if (to) {
      begin(to);
      onMove?.(to);
    } else setEditing(null);
  };

  const release = (cell: CellRef | null) => {
    if (cell) unlock?.(cell);
  };

  /**
   * Отправить правку; `drafts` — введённый текст по полям на случай ошибки, `held` — захваченная
   * ячейка, которую освободить после ответа, `baseVersion` — версия для «Оставить моё».
   */
  const send = async (
    nodeId: string,
    changes: Changes,
    drafts: Map<CellField, string>,
    held: CellRef | null = null,
    baseVersion?: number,
  ) => {
    const node = store.getState().nodes.get(nodeId);
    if (!node) {
      release(held);
      return;
    }
    const fields = [...drafts.keys()];
    const optimistic: NodeEdit = {};
    const values = new Map(Object.entries(changes));
    for (const field of ['o', 'r', 'p', 'multiplier'] as const) {
      if (values.has(field)) Object.assign(optimistic, { [field]: values.get(field) });
    }
    if (Object.keys(optimistic).length) store.getState().edit(nodeId, optimistic);
    if (values.has('comment_lines')) setSavingComments((prev) => new Set(prev).add(nodeId));
    for (const field of fields) setError(cellKey(nodeId, field), null);
    try {
      const result = await call(() =>
        api.PATCH('/nodes/{id}', {
          params: { path: { id: nodeId } },
          body: { base_version: baseVersion ?? node.version, changes },
        }),
      );
      confirm(result.node as unknown as ApiNode, result.project_version);
      release(held);
    } catch (error) {
      if (error instanceof ApiError && error.code === 'FIELD_CONFLICT') {
        // своё значение остаётся в расчёте до выбора; захват держим до решения
        setConflict({
          nodeId,
          items: conflictItems(error, drafts),
          retry: { nodeId, changes, drafts, held, currentVersion: Number(error.extension('current_version') ?? 0) },
        });
        return;
      }
      release(held);
      store.getState().revert(nodeId, fields.filter((f) => f !== 'comment') as EditableField[]);
      const message = lockedMessage(error, t) ?? errorMessage(error);
      for (const [field, draft] of drafts) setError(cellKey(nodeId, field), { message, draft });
    } finally {
      if (values.has('comment_lines'))
        setSavingComments((prev) => {
          const next = new Set(prev);
          next.delete(nodeId);
          return next;
        });
    }
  };

  const current = (nodeId: string, field: 'o' | 'r' | 'p') => {
    const node = store.getState().effective(nodeId);
    if (!node) return null;
    return field === 'o' ? node.o : field === 'r' ? node.r : node.p;
  };

  const commit = (cell: CellRef, text: string, dir: Direction | null): boolean => {
    const { nodeId, field } = cell;
    const key = cellKey(nodeId, field);
    if (field === 'comment') return true;
    if (field === 'multiplier') {
      const parsed = parseMultiplier(text);
      if (!parsed.ok) {
        setError(key, { message: t('cells.multiplierError'), draft: text });
        return false;
      }
      const was = store.getState().effective(nodeId)?.multiplier;
      if (parsed.value !== was) void send(nodeId, { multiplier: parsed.value }, new Map([[field, text]]), cell);
      else {
        setError(key, null);
        release(cell);
      }
      go(cell, dir);
      return true;
    }
    // быстрый ввод вилки в поле O: «8-12-20» или «8/12/20» (FR-TREE-21)
    const fork = field === 'o' ? parseFork(text) : null;
    const entries: ['o' | 'r' | 'p', string][] = fork
      ? [
          ['o', fork[0]],
          ['r', fork[1]],
          ['p', fork[2]],
        ]
      : [[field, text]];
    const changes: Changes = {};
    const drafts = new Map<CellField, string>();
    for (const [f, raw] of entries) {
      const parsed = parseHours(raw);
      if (!parsed.ok) {
        setError(key, {
          message: t(parsed.error === 'range' ? 'cells.rangeError' : 'cells.numberError'),
          draft: text,
        });
        return false;
      }
      if (parsed.rounded && parsed.value !== null)
        hint(cellKey(nodeId, f), t('cells.rounded', { value: formatHoursInput(parsed.value) }));
      if (!sameHours(parsed.value, current(nodeId, f))) {
        Object.assign(changes, { [f]: parsed.value });
        drafts.set(f, raw);
      }
    }
    if (drafts.size) void send(nodeId, changes, drafts, cell);
    else {
      setError(key, null);
      release(cell);
    }
    // после вилки в O курсор идёт в комментарий: R и P уже заполнены
    go(fork && dir === 1 ? { nodeId, field: 'p' } : cell, dir);
    return true;
  };

  return {
    editing,
    conflict: conflict ? { nodeId: conflict.nodeId, items: conflict.items } : null,
    resolveConflict: (choice) => {
      if (!conflict) return;
      const { retry } = conflict;
      setConflict(null);
      if (choice === 'mine') {
        void send(retry.nodeId, retry.changes, retry.drafts, retry.held, retry.currentVersion);
        return;
      }
      release(retry.held);
      const fields = [...retry.drafts.keys()].filter((f) => f !== 'comment') as EditableField[];
      store.getState().revert(retry.nodeId, fields);
    },
    errors,
    hints,
    savingComments,
    start: begin,
    cancel: () => {
      release(editing);
      setEditing(null);
    },
    commit,
    saveComment: (nodeId, lines, dir) => {
      const before = JSON.stringify(store.getState().nodes.get(nodeId)?.extra.comment_lines ?? null);
      const after = JSON.stringify(lines);
      const held: CellRef = { nodeId, field: 'comment' };
      if (before !== after)
        void send(
          nodeId,
          { comment_lines: lines },
          new Map([['comment', (lines ?? []).map((l) => l.text).join('\n')]]),
          held,
        );
      else release(held);
      go({ nodeId, field: 'comment' }, dir);
    },
    applyNorm: (nodeId, norm) => {
      void send(
        nodeId,
        { o: norm.o, r: norm.r, p: norm.p } as Changes,
        new Map<CellField, string>([
          ['o', formatHoursInput(norm.o)],
          ['r', formatHoursInput(norm.r)],
          ['p', formatHoursInput(norm.p)],
        ]),
      );
    },
  };
}

/** Строки конфликта из 409 `FIELD_CONFLICT` (errors.yaml: conflicts[{field, current, changed_by}]). */
function conflictItems(error: ApiError, drafts: Map<CellField, string>): CellConflict['items'] {
  const raw = error.extension('conflicts');
  const list = Array.isArray(raw) ? raw : [];
  const draftOf = new Map([...drafts].map(([f, d]) => [f === 'comment' ? 'comment_lines' : f, d]));
  return list.map((item: unknown) => {
    const map = new Map(Object.entries(item && typeof item === 'object' ? item : {}));
    const field = String(map.get('field') ?? '');
    const by = map.get('changed_by');
    const byMap = new Map(Object.entries(by && typeof by === 'object' ? by : {}));
    const current = map.get('current');
    return {
      field,
      current: current === null || current === undefined ? null : String(current),
      yours: draftOf.get(field) ?? '',
      changedBy: typeof by === 'string' ? by : String(byMap.get('full_name') ?? byMap.get('name') ?? ''),
    };
  });
}

/** 423 `CELL_LOCKED`: «Сейчас редактирует …» по `locked_by` (errors.yaml). */
function lockedMessage(error: unknown, t: (key: string, params: Record<string, unknown>) => string): string | null {
  if (!(error instanceof ApiError) || error.code !== 'CELL_LOCKED') return null;
  const by = error.extension('locked_by');
  const map = new Map(Object.entries(by && typeof by === 'object' ? by : {}));
  const name = String(map.get('full_name') ?? map.get('name') ?? '');
  return name ? t('cells.lockedBy', { name }) : null;
}
