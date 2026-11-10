/**
 * FE-029 · правила статуса ветки и отметки «Проверено» (4.3, BR-BR-01…03, FR-REV-01…04, GAP-10).
 */
import { extraOf, type TreeState } from '../store/treeStore';

type Tree = Pick<TreeState, 'nodes' | 'children' | 'calc'>;

export interface BranchReadiness {
  /** Листья с пустой оценкой. */
  empty: number;
  /** Листья с нарушением O ≤ R ≤ P. */
  invalid: number;
  /** Открытые вопросы в ветке: «Готово · 2 открытых вопроса». */
  open: number;
  /** В ветке есть узлы (для «не нужно»: только пустая ветка). */
  hasNodes: boolean;
}

function subtree(tree: Tree, id: string): string[] {
  const out: string[] = [];
  const stack = [...(tree.children.get(id) ?? [])];
  while (stack.length) {
    const next = stack.pop() as string;
    out.push(next);
    stack.push(...(tree.children.get(next) ?? []));
  }
  return out;
}

/** Готова ли ветка к «Готово» (BR-BR-01): нет пустых и неверных листьев. */
export function branchReadiness(tree: Tree, branchNodeId: string): BranchReadiness {
  const ids = subtree(tree, branchNodeId);
  let empty = 0;
  let invalid = 0;
  let open = 0;
  for (const id of ids) {
    const state = tree.calc?.nodes.get(id)?.leaf?.state;
    if (state === 'empty') empty += 1;
    if (state === 'invalid') invalid += 1;
    const node = tree.nodes.get(id);
    open += Number(extraOf(node).open_questions ?? 0);
  }
  return { empty, invalid, open, hasNodes: ids.length > 0 };
}

/** Поля, правка которых возвращает «готовую» ветку в черновик (BR-BR-02). */
export const RESETS_DONE: ReadonlySet<string> = new Set(['o', 'r', 'p', 'multiplier']);
