/**
 * FE-021 · хранилище дерева проекта (ARCH-03, 13.3, NFR-PERF-03, FR-TREE-30).
 *
 * Источник правды — сервер: `nodes` хранит узлы в том виде, как их последним прислал сервер
 * (`GET /projects/{id}/tree`, ответы PATCH, события WS). Поверх них лежат `pending` — значения,
 * которые пользователь уже ввёл, но сервер ещё не подтвердил («ячейка сохраняется»). Расчёт
 * (`CalcTree` из FE-002) строится по узлам с наложенными `pending`, поэтому итоги и суммы предков
 * меняются сразу при вводе, а итоги проекта всегда считаются по всему дереву.
 *
 * Правка оценки листа пересчитывает только лист и его предков (`updateLeaf`); правка структуры
 * (создание, перенос, удаление, восстановление, смена «лист/узел») пересобирает расчёт целиком.
 * Событие с `project_version` не новее применённой отбрасывается (повтор после переподключения).
 */
import { createStore, type StoreApi } from 'zustand/vanilla';

import type { components } from '../../../shared/api/client';
import {
  CalcTree,
  branchKey,
  dec,
  summarize,
  type BranchStatus,
  type CalcNode,
  type ProjectInput,
  type ProjectResult,
} from '../../../shared/calc';

type ApiNode = components['schemas']['Node'];
type Tree = components['schemas']['Tree'];
type Project = components['schemas']['Project'];

/** Поля узла, которые хранит клиент; вычисляемые сервером суммы не нужны — считаем сами. */
export interface TreeNode {
  id: string;
  parent_id: string | null;
  kind: 'phase' | 'discipline' | 'item';
  phase_id: string;
  discipline_id: string | null;
  type_id: string | null;
  title: string;
  position: string;
  o: string | null;
  r: string | null;
  p: string | null;
  multiplier: number;
  version: number;
  /** Остальные поля ответа (комментарий, «Проверено», версии полей) — как прислал сервер. */
  extra: Readonly<Record<string, unknown>>;
}

/** Поля `extra`, которые читает экран: обращение по имени поля, без копирования объекта. */
export interface NodeExtra {
  comment_lines?: components['schemas']['CommentLine'][] | null;
  reviewed_by?: unknown;
  self_review?: boolean;
  open_questions?: number;
  questions_to_me?: number;
  messages_count?: number;
}

export function extraOf(node: TreeNode | undefined): NodeExtra {
  return (node?.extra ?? {}) as NodeExtra;
}

/** Поля, которые пользователь правит в ячейках. */
export type EditableField = 'title' | 'o' | 'r' | 'p' | 'multiplier' | 'type_id';
export type NodeEdit = Partial<Pick<TreeNode, EditableField>>;

const OWN_KEYS = new Set([
  'id',
  'parent_id',
  'kind',
  'phase_id',
  'discipline_id',
  'type_id',
  'title',
  'position',
  'o',
  'r',
  'p',
  'multiplier',
  'version',
]);

export function toTreeNode(node: ApiNode | Record<string, unknown>): TreeNode {
  const n = node as Record<string, unknown>;
  const text = (v: unknown) => (v === null || v === undefined ? null : String(v as string));
  return {
    id: String(n.id as string),
    parent_id: text(n.parent_id),
    kind: n.kind as TreeNode['kind'],
    phase_id: String(n.phase_id as string),
    discipline_id: text(n.discipline_id),
    type_id: text(n.type_id),
    title: typeof n.title === 'string' ? n.title : '',
    position: typeof n.position === 'string' ? n.position : '',
    o: text(n.o),
    r: text(n.r),
    p: text(n.p),
    multiplier: typeof n.multiplier === 'number' ? n.multiplier : 1,
    version: typeof n.version === 'number' ? n.version : 0,
    extra: Object.fromEntries(Object.entries(n).filter(([k]) => !OWN_KEYS.has(k))),
  };
}

/** Настройки проекта, от которых зависит расчёт. */
export interface CalcSettings {
  pmPercent: string;
  quoteFigure: ProjectInput['quoteFigure'];
  detailLevel: ProjectInput['detailLevel'];
  phases: { id: string; name: string; isCrossCutting: boolean; inPmBase: boolean; enabled: boolean }[];
  disciplines: { id: string; name: string }[];
}

export function settingsOf(project: Project): CalcSettings {
  return {
    pmPercent: String(project.pm_percent),
    quoteFigure: project.quote_figure,
    detailLevel: project.detail_level,
    phases: project.phases.map((p) => ({
      id: p.phase_id,
      name: p.name,
      isCrossCutting: p.is_cross_cutting,
      inPmBase: p.in_pm_base,
      enabled: p.is_enabled,
    })),
    disciplines: project.disciplines.map((d) => ({ id: d.discipline_id, name: d.name })),
  };
}

/** Соседи по ключу порядка (fractional indexing, ARCH-04): сравнение побайтно, как COLLATE "C". */
export function byPosition(a: TreeNode, b: TreeNode): number {
  if (a.position !== b.position) return a.position < b.position ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Событие канала проекта, которое меняет дерево (ws-events.schema.json). */
export type TreeEvent =
  | { event: 'node.created' | 'node.updated' | 'node.moved'; project_version: number; data: { node: ApiNode } }
  | { event: 'node.deleted'; project_version: number; data: { node_ids: string[] } }
  | { event: 'node.restored'; project_version: number; data: { nodes: ApiNode[] } }
  | {
      event: 'branch.status';
      project_version: number;
      data: { phase_id: string; discipline_id: string; status: BranchStatus };
    };

export interface TreeMutation {
  nodes: readonly ApiNode[];
  deleted_ids?: readonly string[] | undefined;
  project_version: number;
  branch_statuses?: readonly { phase_id: string; discipline_id: string; status: string }[] | undefined;
}

export interface TreeState {
  /** Последняя применённая версия проекта. */
  version: number;
  settings: CalcSettings | null;
  nodes: ReadonlyMap<string, TreeNode>;
  branchStatus: ReadonlyMap<string, BranchStatus>;
  /** Введённые, но не подтверждённые сервером значения: узел → поля. */
  pending: ReadonlyMap<string, NodeEdit>;
  /** Дети по родителю (`null` — фазы) в порядке `position`. */
  children: ReadonlyMap<string | null, readonly string[]>;
  calc: CalcTree | null;
  result: ProjectResult | null;
  /** Растёт при каждом изменении расчёта: по нему подписываются строки таблицы. */
  revision: number;
}

export interface TreeActions {
  load(tree: Tree, settings: CalcSettings): void;
  setSettings(settings: CalcSettings): void;
  /** Применить событие WS; `false` — событие старое и пропущено. */
  applyEvent(event: TreeEvent): boolean;
  /** Узел из ответа PATCH/POST: сервер подтвердил правку. */
  applyNode(node: ApiNode, projectVersion: number): void;
  /**
   * Ответ операции с поддеревом (FE-027: разбить, свернуть, переместить, дублировать, удалить,
   * скопировать ветку): изменённые узлы, удалённые и новые статусы веток.
   */
  applyMutation(mutation: TreeMutation): void;
  /** Оптимистичная правка: значения сразу в расчёте, ячейки помечены «сохраняется». */
  edit(nodeId: string, values: NodeEdit): void;
  /** Сервер отказал: снять несохранённые значения полей. */
  revert(nodeId: string, fields: readonly EditableField[]): void;
  isPending(nodeId: string, field: EditableField): boolean;
  /** Узел с наложенными несохранёнными значениями. */
  effective(nodeId: string): TreeNode | undefined;
}

export type TreeStore = StoreApi<TreeState & TreeActions>;

function childrenOf(nodes: ReadonlyMap<string, TreeNode>): Map<string | null, string[]> {
  const groups = new Map<string | null, TreeNode[]>();
  for (const node of nodes.values()) {
    const list = groups.get(node.parent_id) ?? [];
    list.push(node);
    groups.set(node.parent_id, list);
  }
  return new Map([...groups].map(([parent, list]) => [parent, list.sort(byPosition).map((n) => n.id)]));
}

function merged(node: TreeNode, edit: NodeEdit | undefined): TreeNode {
  return edit ? { ...node, ...edit } : node;
}

function calcNode(node: TreeNode): CalcNode {
  const num = (v: string | null) => (v === null ? null : dec(v));
  return {
    id: node.id,
    parentId: node.parent_id,
    kind: node.kind,
    phaseId: node.phase_id,
    disciplineId: node.discipline_id,
    type: node.type_id,
    title: node.title,
    o: num(node.o),
    r: num(node.r),
    p: num(node.p),
    multiplier: node.multiplier,
  };
}

/** Удалить узлы вместе с потомками (в корзину уходит поддерево, 8.4). */
function withoutSubtrees(nodes: Map<string, TreeNode>, ids: readonly string[]): void {
  const children = childrenOf(nodes);
  const stack = [...ids];
  for (let id = stack.pop(); id !== undefined; id = stack.pop()) {
    if (!nodes.delete(id)) continue;
    stack.push(...(children.get(id) ?? []));
  }
}

export function createTreeStore(): TreeStore {
  return createStore<TreeState & TreeActions>()((set, get) => {
    /** Пересобрать расчёт по узлам, статусам веток и настройкам. */
    function rebuild(
      nodes: ReadonlyMap<string, TreeNode>,
      pending: ReadonlyMap<string, NodeEdit>,
      branchStatus: ReadonlyMap<string, BranchStatus>,
      settings: CalcSettings | null,
    ): Pick<TreeState, 'children' | 'calc' | 'result'> {
      const children = childrenOf(nodes);
      if (!settings) return { children, calc: null, result: null };
      // вход CalcTree — в порядке обхода, чтобы порядок детей совпадал с `position`
      const ordered: CalcNode[] = [];
      const stack = [...(children.get(null) ?? [])].reverse();
      for (let id = stack.pop(); id !== undefined; id = stack.pop()) {
        const node = nodes.get(id);
        if (!node) continue;
        ordered.push(calcNode(merged(node, pending.get(id))));
        stack.push(...[...(children.get(id) ?? [])].reverse());
      }
      const input: ProjectInput = {
        pmPercent: dec(settings.pmPercent),
        quoteFigure: settings.quoteFigure,
        detailLevel: settings.detailLevel,
        phases: settings.phases,
        disciplines: settings.disciplines,
        nodes: ordered,
        branchStatus: new Map(branchStatus),
        money: null,
      };
      const calc = new CalcTree(input);
      return { children, calc, result: summarize(calc) };
    }

    /** Правка только оценки листа — пересчёт листа и предков; иначе полная пересборка. */
    function recompute(
      nodes: ReadonlyMap<string, TreeNode>,
      pending: ReadonlyMap<string, NodeEdit>,
      touched: string | null,
    ): Partial<TreeState> {
      const state = get();
      const calc = state.calc;
      const result = touched && calc ? calc.nodes.get(touched) : undefined;
      const node = touched ? nodes.get(touched) : undefined;
      if (calc && result && !result.isLeaf && node && sameShape(state.nodes, nodes, touched)) {
        // название или тип узла: суммы не меняются
        const n = merged(node, pending.get(node.id));
        result.node = { ...result.node, title: n.title, type: n.type_id };
        return { nodes, pending, revision: state.revision + 1 };
      }
      if (calc && result?.isLeaf && node && sameShape(state.nodes, nodes, touched)) {
        const n = merged(node, pending.get(node.id));
        calc.updateLeaf(node.id, {
          o: n.o === null ? null : dec(n.o),
          r: n.r === null ? null : dec(n.r),
          p: n.p === null ? null : dec(n.p),
          multiplier: n.multiplier,
        });
        result.node = { ...result.node, title: n.title, type: n.type_id };
        return { nodes, pending, result: summarize(calc), revision: state.revision + 1 };
      }
      return {
        nodes,
        pending,
        ...rebuild(nodes, pending, state.branchStatus, state.settings),
        revision: state.revision + 1,
      };
    }

    return {
      version: 0,
      settings: null,
      nodes: new Map(),
      branchStatus: new Map(),
      pending: new Map(),
      children: new Map(),
      calc: null,
      result: null,
      revision: 0,

      load(tree, settings) {
        const nodes = new Map(tree.nodes.map((n) => [n.id, toTreeNode(n)]));
        const branchStatus = new Map(
          tree.branch_statuses.map((b) => [branchKey(b.phase_id, b.discipline_id), b.status as BranchStatus]),
        );
        // перезагрузка (resync) не теряет введённое, но ещё не подтверждённое
        const pending = new Map([...get().pending].filter(([id]) => nodes.has(id)));
        set({
          version: tree.project_version,
          settings,
          nodes,
          branchStatus,
          pending,
          ...rebuild(nodes, pending, branchStatus, settings),
          revision: get().revision + 1,
        });
      },

      setSettings(settings) {
        const { nodes, pending, branchStatus, revision } = get();
        set({ settings, ...rebuild(nodes, pending, branchStatus, settings), revision: revision + 1 });
      },

      applyEvent(event) {
        const state = get();
        if (event.project_version <= state.version) return false;
        const nodes = new Map(state.nodes);
        let touched: string | null = null;
        switch (event.event) {
          case 'node.created':
          case 'node.moved':
            nodes.set(event.data.node.id, toTreeNode(event.data.node));
            break;
          case 'node.updated': {
            const node = toTreeNode(event.data.node);
            nodes.set(node.id, node);
            touched = node.id;
            break;
          }
          case 'node.deleted':
            withoutSubtrees(nodes, event.data.node_ids);
            break;
          case 'node.restored':
            for (const n of event.data.nodes) nodes.set(n.id, toTreeNode(n));
            break;
          case 'branch.status': {
            const branchStatus = new Map(state.branchStatus);
            branchStatus.set(branchKey(event.data.phase_id, event.data.discipline_id), event.data.status);
            set({
              version: event.project_version,
              branchStatus,
              ...rebuild(nodes, state.pending, branchStatus, state.settings),
              nodes,
              revision: state.revision + 1,
            });
            return true;
          }
        }
        // правки, которые сервер уже не применит (узел удалён), снимаем
        const pending = new Map([...state.pending].filter(([id]) => nodes.has(id)));
        set({ version: event.project_version, ...recompute(nodes, pending, touched) });
        return true;
      },

      applyNode(apiNode, projectVersion) {
        const state = get();
        const node = toTreeNode(apiNode);
        const known = state.nodes.get(node.id);
        const nodes = new Map(state.nodes);
        // ответ PATCH может прийти позже события той же правки — не откатываем более новый узел
        if (!known || known.version <= node.version) nodes.set(node.id, node);
        const pending = new Map(state.pending);
        pending.delete(node.id);
        set({ version: Math.max(state.version, projectVersion), ...recompute(nodes, pending, node.id) });
      },

      applyMutation(mutation) {
        const state = get();
        const nodes = new Map(state.nodes);
        withoutSubtrees(nodes, mutation.deleted_ids ?? []);
        for (const apiNode of mutation.nodes) {
          const node = toTreeNode(apiNode);
          const known = nodes.get(node.id);
          if (!known || known.version <= node.version) nodes.set(node.id, node);
        }
        const branchStatus = new Map(state.branchStatus);
        for (const b of mutation.branch_statuses ?? [])
          branchStatus.set(branchKey(b.phase_id, b.discipline_id), b.status as BranchStatus);
        const changed = new Set(mutation.nodes.map((n) => n.id));
        const pending = new Map([...state.pending].filter(([id]) => nodes.has(id) && !changed.has(id)));
        set({
          version: Math.max(state.version, mutation.project_version),
          nodes,
          branchStatus,
          pending,
          ...rebuild(nodes, pending, branchStatus, state.settings),
          revision: state.revision + 1,
        });
      },

      edit(nodeId, values) {
        const state = get();
        if (!state.nodes.has(nodeId)) return;
        const pending = new Map(state.pending);
        pending.set(nodeId, { ...pending.get(nodeId), ...values });
        set(recompute(state.nodes, pending, nodeId));
      },

      revert(nodeId, fields) {
        const state = get();
        const current = state.pending.get(nodeId);
        if (!current) return;
        const rest = Object.fromEntries(
          Object.entries(current).filter(([k]) => !fields.includes(k as EditableField)),
        ) as NodeEdit;
        const pending = new Map(state.pending);
        if (Object.keys(rest).length) pending.set(nodeId, rest);
        else pending.delete(nodeId);
        set(recompute(state.nodes, pending, nodeId));
      },

      isPending(nodeId, field) {
        const edit = get().pending.get(nodeId);
        return edit !== undefined && field in edit;
      },

      effective(nodeId) {
        const { nodes, pending } = get();
        const node = nodes.get(nodeId);
        return node ? merged(node, pending.get(nodeId)) : undefined;
      },
    };
  });
}

/**
 * Изменился только сам узел и не его место в дереве: тот же родитель и порядок, тот же вид.
 * Тогда достаточно пересчитать лист и предков.
 */
function sameShape(before: ReadonlyMap<string, TreeNode>, after: ReadonlyMap<string, TreeNode>, id: string | null) {
  if (id === null || before.size !== after.size) return false;
  const a = before.get(id);
  const b = after.get(id);
  return (
    a !== undefined &&
    b !== undefined &&
    a.parent_id === b.parent_id &&
    a.position === b.position &&
    a.kind === b.kind &&
    a.phase_id === b.phase_id &&
    a.discipline_id === b.discipline_id
  );
}
