/**
 * FE-027 · правила операций с узлами дерева (FR-TREE-01, FR-TREE-23, FR-TREE-24, BR-TREE-01…05).
 *
 * Чистые функции над состоянием дерева: какой тип предложить новому узлу, какие пункты меню
 * доступны и почему нет, куда можно переместить узел. Окончательно всё проверяет сервер.
 */
import { extraOf, type TreeNode, type TreeState } from '../store/treeStore';

type Tree = Pick<TreeState, 'nodes' | 'children'>;

/** Максимальная глубина ниже ветки дисциплины (BR-TREE-05). */
export const MAX_DEPTH = 8;

export function childrenOf(tree: Tree, id: string | null): readonly string[] {
  return tree.children.get(id) ?? [];
}

/** Лист: строка без детей (ветка дисциплины тоже может быть листом, BR-TREE-04). */
export function isLeaf(tree: Tree, id: string): boolean {
  return childrenOf(tree, id).length === 0;
}

/** Уровень узла ниже ветки дисциплины: ребёнок ветки — 1. Фаза и ветка — 0. */
export function depthOf(tree: Tree, id: string): number {
  let depth = 0;
  for (let node = tree.nodes.get(id); node && node.kind === 'item'; node = tree.nodes.get(node.parent_id ?? '')) {
    depth += 1;
  }
  return depth;
}

/** Высота поддерева: лист — 1. */
export function heightOf(tree: Tree, id: string): number {
  let height = 1;
  for (const child of childrenOf(tree, id)) height = Math.max(height, 1 + heightOf(tree, child));
  return height;
}

export function descendantsOf(tree: Tree, id: string): Set<string> {
  const out = new Set<string>();
  const stack = [...childrenOf(tree, id)];
  while (stack.length) {
    const next = stack.pop() as string;
    out.add(next);
    stack.push(...childrenOf(tree, next));
  }
  return out;
}

/**
 * Тип нового ребёнка по профилю ветки (FR-TREE-01): у ветки дисциплины — первый тип цепочки;
 * у узла с N-м типом цепочки — (N+1)-й; иначе — тип родителя.
 */
export function suggestType(tree: Tree, parentId: string, chain: readonly string[]): string | null {
  const parent = tree.nodes.get(parentId);
  if (!parent) return null;
  if (parent.kind === 'discipline') return chain.at(0) ?? null;
  const at = parent.type_id ? chain.indexOf(parent.type_id) : -1;
  if (at >= 0 && at + 1 < chain.length) return chain.at(at + 1) ?? null;
  return parent.type_id;
}

/** `after_id` для «Вверх» (−1) и «Вниз» (+1); null — двигать некуда. */
export function reorderAfter(tree: Tree, id: string, dir: -1 | 1): { afterId: string | null } | null {
  const node = tree.nodes.get(id);
  if (!node) return null;
  const siblings = childrenOf(tree, node.parent_id);
  const at = siblings.indexOf(id);
  if (dir < 0) return at <= 0 ? null : { afterId: at >= 2 ? (siblings.at(at - 2) ?? null) : null };
  return at < 0 || at >= siblings.length - 1 ? null : { afterId: siblings.at(at + 1) ?? null };
}

/**
 * `after_id` для перетаскивания `id` на строку `targetId` — выше (`below` false) или ниже неё —
 * в пределах того же родителя (порядок, 11.5 №4). null — нельзя или порядок не изменится.
 */
export function dropAfter(tree: Tree, id: string, targetId: string, below: boolean): { afterId: string | null } | null {
  const node = tree.nodes.get(id);
  const target = tree.nodes.get(targetId);
  if (!node || !target || id === targetId || node.kind !== 'item' || node.parent_id !== target.parent_id) return null;
  const siblings = childrenOf(tree, node.parent_id);
  const rest = siblings.filter((s) => s !== id);
  const at = rest.indexOf(targetId);
  if (at < 0) return null;
  const afterId = below ? targetId : at > 0 ? (rest.at(at - 1) ?? null) : null;
  const cur = siblings.indexOf(id);
  const currentAfter = cur > 0 ? (siblings.at(cur - 1) ?? null) : null;
  return afterId === currentAfter ? null : { afterId };
}

export interface MoveTarget {
  id: string;
  title: string;
  /** Отступ в списке диалога: ветка — 0. */
  level: number;
  kind: TreeNode['kind'];
}

/**
 * Куда можно переместить узел (FR-TREE-23): ветки дисциплин и узлы с детьми; эксперту — в
 * пределах своей ветки (`sameBranch`), модератору — по всему проекту. Без самого узла, его
 * потомков, нынешнего родителя и мест, где поддерево превысит глубину 8.
 */
export function moveTargets(
  tree: Tree,
  id: string,
  options: { sameBranch: boolean; canEdit: (disciplineId: string | null) => boolean },
): MoveTarget[] {
  const node = tree.nodes.get(id);
  if (!node) return [];
  const skip = descendantsOf(tree, id);
  skip.add(id);
  const height = heightOf(tree, id);
  const out: MoveTarget[] = [];
  const walk = (parent: string | null, level: number) => {
    for (const childId of childrenOf(tree, parent)) {
      const child = tree.nodes.get(childId);
      if (!child || skip.has(childId)) continue;
      if (child.kind === 'phase') {
        if (!options.sameBranch || child.phase_id === node.phase_id) walk(childId, 0);
        continue;
      }
      if (options.sameBranch && (child.phase_id !== node.phase_id || child.discipline_id !== node.discipline_id))
        continue;
      if (!options.canEdit(child.discipline_id)) continue;
      const leaf = isLeaf(tree, childId);
      // в лист с оценкой переносить нельзя (BR-TREE-01); пустая ветка дисциплины принимает детей
      const accepts = child.kind === 'discipline' ? !leaf || child.o === null : !leaf;
      if (accepts && childId !== node.parent_id && depthOf(tree, childId) + height <= MAX_DEPTH)
        out.push({ id: childId, title: child.title, level, kind: child.kind });
      walk(childId, level + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** Удаление спрашивает подтверждение, если у узла есть дети или обсуждения (FR-TREE-24). */
export function needsDeleteConfirm(tree: Tree, id: string): boolean {
  const node = tree.nodes.get(id);
  if (!node) return false;
  const messages = Number(extraOf(node).messages_count ?? 0);
  return !isLeaf(tree, id) || messages > 0;
}

/** Узлы ответа, которых ещё нет в дереве (созданные операцией). */
export function createdIds(tree: Tree, nodes: readonly { id: string }[]): string[] {
  return nodes.filter((n) => !tree.nodes.has(n.id)).map((n) => n.id);
}
