/**
 * FE-025 · ввод в ячейки дерева (FR-TREE-20…22, FR-TREE-02, 11.4 «Ввод с клавиатуры»).
 *
 * Одна ячейка в правке за раз. Enter и уход фокуса сохраняют, Esc отменяет, Tab идёт
 * O → R → P → Комментарий → O следующего листа (Shift+Tab — назад). Сохранение на лету:
 * значения O/R/P/×N сразу попадают в расчёт (оптимистично, ячейка «сохраняется»), запрос —
 * `PATCH /nodes/{id}` с `base_version`. При ошибке значение снимается из расчёта, а в ячейке
 * остаётся введённый текст с красной рамкой и текстом ошибки. Захват ячеек, чужой ввод и
 * диалог конфликта — FE-026.
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call, errorMessage } from '../../../shared/api/problem';
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

export interface CellsApi {
  editing: CellRef | null;
  errors: ReadonlyMap<string, CellError>;
  hints: ReadonlyMap<string, string>;
  /** Узлы, чей комментарий ещё сохраняется. */
  savingComments: ReadonlySet<string>;
  start: (cell: CellRef) => void;
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
}: {
  store: TreeStore;
  confirm: (node: ApiNode, projectVersion: number) => void;
  /** Листья, которые пользователь может править, в порядке строк. */
  leaves: readonly string[];
  /** Ячейка стала активной (прокрутить к строке). */
  onMove?: (cell: CellRef) => void;
}): CellsApi {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<CellRef | null>(null);
  const [errors, setErrors] = useState<ReadonlyMap<string, CellError>>(new Map());
  const [hints, setHints] = useState<ReadonlyMap<string, string>>(new Map());
  const [savingComments, setSavingComments] = useState<ReadonlySet<string>>(new Set());
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

  const go = (from: CellRef, dir: Direction | null) => {
    const to = dir === null ? null : nextCell(leaves, from, dir);
    setEditing(to);
    if (to) onMove?.(to);
  };

  /** Отправить правку; `drafts` — введённый текст по полям на случай ошибки. */
  const send = async (nodeId: string, changes: Changes, drafts: Map<CellField, string>) => {
    const node = store.getState().nodes.get(nodeId);
    if (!node) return;
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
        api.PATCH('/nodes/{id}', { params: { path: { id: nodeId } }, body: { base_version: node.version, changes } }),
      );
      confirm(result.node as unknown as ApiNode, result.project_version);
    } catch (error) {
      store.getState().revert(nodeId, fields.filter((f) => f !== 'comment') as EditableField[]);
      const message = errorMessage(error);
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
      if (parsed.value !== was) void send(nodeId, { multiplier: parsed.value }, new Map([[field, text]]));
      else setError(key, null);
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
    if (drafts.size) void send(nodeId, changes, drafts);
    else setError(key, null);
    // после вилки в O курсор идёт в комментарий: R и P уже заполнены
    go(fork && dir === 1 ? { nodeId, field: 'p' } : cell, dir);
    return true;
  };

  return {
    editing,
    errors,
    hints,
    savingComments,
    start: (cell) => setEditing(cell),
    cancel: () => setEditing(null),
    commit,
    saveComment: (nodeId, lines, dir) => {
      const before = JSON.stringify(store.getState().nodes.get(nodeId)?.extra.comment_lines ?? null);
      const after = JSON.stringify(lines);
      if (before !== after)
        void send(
          nodeId,
          { comment_lines: lines },
          new Map([['comment', (lines ?? []).map((l) => l.text).join('\n')]]),
        );
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
