/**
 * FE-018 · правила корзины (FR-TREE-24, G-15): сколько дней до окончательного удаления и куда
 * можно восстановить пакет, если прежнее место недоступно.
 */
import type { MoveTarget } from '../work/menu/ops';

interface Node {
  id: string;
  parent_id: string | null;
  kind: MoveTarget['kind'];
  phase_id: string;
  discipline_id: string | null;
  title: string;
  position: string;
  o: unknown;
}
/** Выдача `GET /projects/{id}/tree` — только нужные поля. */
interface Tree {
  nodes: readonly Node[];
  branch_statuses: readonly { phase_id: string; discipline_id: string; status: string }[];
}

const DAY = 24 * 60 * 60 * 1000;
/** За сколько дней до очистки элемент помечается «будет удалён через N дн.». */
export const SOON_DAYS = 3;

/** Полных или неполных дней до окончательного удаления; 0 — удалится сегодня ночью. */
export function daysLeft(purgeAt: string, now: number = Date.now()): number {
  return Math.max(0, Math.ceil((Date.parse(purgeAt) - now) / DAY));
}

/**
 * Узлы той же дисциплины, куда можно восстановить пакет: ветки дисциплины в фазах проекта (кроме
 * «не нужно» и ветки-листа с оценкой) и узлы с детьми. Порядок — как в дереве.
 */
export function restoreTargets(tree: Tree, disciplineId: string): MoveTarget[] {
  const children = new Map<string | null, Node[]>();
  for (const node of tree.nodes) {
    const list = children.get(node.parent_id) ?? [];
    list.push(node);
    children.set(node.parent_id, list);
  }
  for (const list of children.values()) list.sort((a, b) => a.position.localeCompare(b.position));
  const notNeeded = new Set(
    tree.branch_statuses.filter((b) => b.status === 'not_needed').map((b) => `${b.phase_id}/${b.discipline_id}`),
  );
  const out: MoveTarget[] = [];
  const walk = (parentId: string, level: number) => {
    for (const node of children.get(parentId) ?? []) {
      if (!children.get(node.id)?.length) continue;
      out.push({ id: node.id, title: node.title, level, kind: node.kind });
      walk(node.id, level + 1);
    }
  };
  for (const phase of children.get(null) ?? []) {
    for (const branch of children.get(phase.id) ?? []) {
      if (branch.kind !== 'discipline' || branch.discipline_id !== disciplineId) continue;
      if (notNeeded.has(`${branch.phase_id}/${disciplineId}`)) continue;
      const leaf = !children.get(branch.id)?.length;
      if (leaf && branch.o !== null) continue;
      out.push({ id: branch.id, title: `${phase.title} › ${branch.title}`, level: 0, kind: 'discipline' });
      walk(branch.id, 1);
    }
  }
  return out;
}
