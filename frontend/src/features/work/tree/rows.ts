/**
 * FE-022 · плоский список видимых строк дерева для виртуализированной таблицы (FR-TREE-10, FR-TREE-13,
 * 11.4 №15; DESIGN.md 9.5).
 *
 * Порядок: фазы в порядке дерева, внутри — ветки дисциплин и узлы по `position`; сквозная фаза
 * не рисуется деревом — вместо неё последняя строка «Управление проектом». Выключенные фазы не
 * показываются. Свёрнутые узлы скрывают потомков; по умолчанию всё раскрыто.
 *
 * С фильтром или поиском (FE-024) показываются только узлы из `visible` (найденные и их предки),
 * свёртка при этом не действует (кнопок свёртки нет), строка УП остаётся последней.
 */
import type { CalcTree } from '../../../shared/calc';
import type { CalcSettings } from '../store/treeStore';

export type RowKind = 'phase' | 'discipline' | 'node' | 'leaf' | 'pm';

export interface TreeRow {
  key: string;
  kind: RowKind;
  /** id узла; у строки УП — id узла сквозной фазы или null. */
  id: string | null;
  /** 0 — фаза, 1 — дисциплина, 2… — узлы. */
  depth: number;
  hasChildren: boolean;
  collapsed: boolean;
  /** Дерево под фильтром: свёртка не действует, кнопки свёртки нет. */
  filtered: boolean;
  phaseId: string;
  disciplineId: string | null;
}

/** После 5-го уровня отступ не растёт, у иконки появляется цифра глубины (FR-TREE-13). */
export const MAX_INDENT_DEPTH = 5;

/** Отступ строки: базовые 8 px и по 16 px на уровень, не глубже 5-го. */
export function indentOf(depth: number): number {
  return 8 + 16 * Math.min(depth, MAX_INDENT_DEPTH);
}

export function buildRows(
  calc: CalcTree,
  children: ReadonlyMap<string | null, readonly string[]>,
  settings: CalcSettings,
  collapsed: ReadonlySet<string>,
  visible: ReadonlySet<string> | null = null,
): TreeRow[] {
  const phases = new Map(settings.phases.map((p) => [p.id, p]));
  const rows: TreeRow[] = [];
  let pm: TreeRow | null = null;

  const visit = (id: string, depth: number) => {
    const result = calc.nodes.get(id);
    if (!result) return;
    if (visible && !visible.has(id)) return;
    const node = result.node;
    const kids = children.get(id) ?? [];
    const isCollapsed = !visible && collapsed.has(id);
    const kind: RowKind =
      node.kind === 'phase' ? 'phase' : node.kind === 'discipline' ? 'discipline' : result.isLeaf ? 'leaf' : 'node';
    rows.push({
      key: id,
      kind,
      id,
      depth,
      hasChildren: kids.length > 0,
      filtered: visible !== null,
      collapsed: isCollapsed,
      phaseId: node.phaseId,
      disciplineId: node.disciplineId,
    });
    if (isCollapsed) return;
    for (const child of kids) visit(child, depth + 1);
  };

  for (const id of children.get(null) ?? []) {
    const result = calc.nodes.get(id);
    if (!result) continue;
    const phase = phases.get(result.node.phaseId);
    if (!phase?.enabled) continue;
    if (phase.isCrossCutting) {
      pm = {
        key: 'pm',
        kind: 'pm',
        id,
        depth: 0,
        hasChildren: false,
        collapsed: false,
        filtered: false,
        phaseId: phase.id,
        disciplineId: null,
      };
      continue;
    }
    if (visible && !visible.has(id)) continue;
    visit(id, 0);
  }
  const cross = settings.phases.find((p) => p.isCrossCutting && p.enabled);
  if (!pm && cross) {
    pm = {
      key: 'pm',
      kind: 'pm',
      id: null,
      depth: 0,
      hasChildren: false,
      collapsed: false,
      filtered: false,
      phaseId: cross.id,
      disciplineId: null,
    };
  }
  if (pm) rows.push(pm);
  return rows;
}

/** Предки узла (для раскрытия найденной строки и подсказки пути). */
export function ancestorsOf(calc: CalcTree, id: string): string[] {
  const out: string[] = [];
  for (let parent = calc.nodes.get(id)?.node.parentId ?? null; parent !== null; ) {
    out.push(parent);
    parent = calc.nodes.get(parent)?.node.parentId ?? null;
  }
  return out;
}
