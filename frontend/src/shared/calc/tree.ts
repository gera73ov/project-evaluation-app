/**
 * FE-002 · свёртка дерева с инкрементальным пересчётом (SPEC 6.2, BR-CALC-01/02, BR-TREE-03,
 * NFR-PERF-03). Зеркало `domain/calc/rollup.py`.
 *
 * `CalcTree` держит суммы всех узлов. Правка листа (`updateLeaf`) пересчитывает только этот лист
 * и его предков: сумма каждого предка заново складывается из сумм его детей, поэтому результат
 * не накапливает ошибку и совпадает с полным пересчётом.
 */
import { ZERO, p80, p90, type Dec } from './decimal';
import { estimate, isCounted, type LeafEstimate } from './leaf';
import { branchKey, type CalcNode, type ProjectInput } from './model';

export interface Totals {
  e: Dec;
  /** σ хранится квадратом: так суммы складываются без потери точности. */
  sigmaSq: Dec;
  sumO: Dec;
  sumR: Dec;
  sumP: Dec;
  /** Листья без оценки или с неверной оценкой (BR-CALC-02). */
  unaccounted: number;
}

export const EMPTY_TOTALS: Totals = {
  e: ZERO,
  sigmaSq: ZERO,
  sumO: ZERO,
  sumR: ZERO,
  sumP: ZERO,
  unaccounted: 0,
};

export function addTotals(a: Totals, b: Totals): Totals {
  return {
    e: a.e.plus(b.e),
    sigmaSq: a.sigmaSq.plus(b.sigmaSq),
    sumO: a.sumO.plus(b.sumO),
    sumR: a.sumR.plus(b.sumR),
    sumP: a.sumP.plus(b.sumP),
    unaccounted: a.unaccounted + b.unaccounted,
  };
}

export function sigmaOf(t: Totals): Dec {
  return t.sigmaSq.sqrt();
}

export function totalsP80(t: Totals): Dec {
  return p80(t.e, sigmaOf(t));
}

export function totalsP90(t: Totals): Dec {
  return p90(t.e, sigmaOf(t));
}

export interface NodeResult {
  node: CalcNode;
  isLeaf: boolean;
  /** Ветка «не нужно» или выключенная фаза (BR-CALC-01). */
  excluded: boolean;
  leaf: LeafEstimate | null;
  totals: Totals;
}

export interface CollapseSuggestion {
  o: Dec;
  r: Dec;
  p: Dec;
  multiplier: 1;
}

export class TreeError extends Error {
  override name = 'TreeError';
}

function leafTotals(leaf: LeafEstimate): Totals {
  if (!isCounted(leaf.state)) return { ...EMPTY_TOTALS, unaccounted: 1 };
  return {
    e: leaf.e,
    sigmaSq: leaf.sigma.times(leaf.sigma),
    sumO: leaf.sumO,
    sumR: leaf.sumR,
    sumP: leaf.sumP,
    unaccounted: 0,
  };
}

export interface LeafValues {
  o: Dec | null;
  r: Dec | null;
  p: Dec | null;
  multiplier: number;
}

export class CalcTree {
  readonly nodes = new Map<string, NodeResult>();
  readonly children = new Map<string | null, string[]>();

  constructor(readonly input: ProjectInput) {
    const ids = new Set(input.nodes.map((n) => n.id));
    for (const node of input.nodes) {
      if (node.parentId !== null && !ids.has(node.parentId)) {
        throw new TreeError(`у узла ${node.id} нет родителя ${node.parentId}`);
      }
      const list = this.children.get(node.parentId) ?? [];
      list.push(node.id);
      this.children.set(node.parentId, list);
    }
    const disabled = new Set(input.phases.filter((p) => !p.enabled).map((p) => p.id));
    for (const node of input.nodes) {
      const isLeaf = node.kind === 'item' && !this.children.has(node.id);
      const leaf = isLeaf ? estimate(node.o, node.r, node.p, node.multiplier) : null;
      const excluded =
        disabled.has(node.phaseId) ||
        (node.disciplineId !== null &&
          input.branchStatus.get(branchKey(node.phaseId, node.disciplineId)) === 'not_needed');
      this.nodes.set(node.id, {
        node,
        isLeaf,
        excluded,
        leaf,
        totals: leaf ? leafTotals(leaf) : EMPTY_TOTALS,
      });
    }
    const order = [...this.walk()];
    if (order.length !== this.nodes.size) throw new TreeError('в дереве есть цикл');
    for (const id of order.reverse()) {
      const result = this.get(id);
      if (!result.isLeaf) result.totals = this.sumChildren(id);
    }
  }

  get(id: string): NodeResult {
    const result = this.nodes.get(id);
    if (!result) throw new TreeError(`нет узла ${id}`);
    return result;
  }

  /** Прямой обход: родитель раньше детей, соседи — в порядке входа. */
  *walk(): Generator<string> {
    const stack = [...(this.children.get(null) ?? [])].reverse();
    for (let id = stack.pop(); id !== undefined; id = stack.pop()) {
      yield id;
      stack.push(...[...(this.children.get(id) ?? [])].reverse());
    }
  }

  *leaves(includeExcluded = false): Generator<NodeResult> {
    for (const id of this.walk()) {
      const result = this.get(id);
      if (result.isLeaf && (includeExcluded || !result.excluded)) yield result;
    }
  }

  /** Сумма детей; граница исключения: ветка «не нужно» не попадает в фазу (BR-CALC-01). */
  private sumChildren(id: string): Totals {
    const parent = this.get(id);
    let totals = EMPTY_TOTALS;
    for (const childId of this.children.get(id) ?? []) {
      const child = this.get(childId);
      if (!child.excluded || parent.excluded) totals = addTotals(totals, child.totals);
    }
    return totals;
  }

  /**
   * Применить новую оценку листа и пересчитать его предков (NFR-PERF-03: ≤ 100 мс на 5 000
   * узлах). Возвращает id изменённых узлов — от листа к корню.
   */
  updateLeaf(id: string, values: LeafValues): string[] {
    const result = this.get(id);
    if (!result.isLeaf) throw new TreeError(`узел ${id} не лист`);
    result.node = { ...result.node, ...values };
    result.leaf = estimate(values.o, values.r, values.p, values.multiplier);
    result.totals = leafTotals(result.leaf);
    const changed = [id];
    for (let parentId = result.node.parentId; parentId !== null; ) {
      const parent = this.get(parentId);
      parent.totals = this.sumChildren(parentId);
      changed.push(parentId);
      parentId = parent.node.parentId;
    }
    return changed;
  }

  collapseSuggestion(id: string): CollapseSuggestion {
    const t = this.get(id).totals;
    return { o: t.sumO, r: t.sumR, p: t.sumP, multiplier: 1 };
  }
}

/** Узлы верхнего уровня (фазы) по id фазы. */
export function phaseRoots(tree: CalcTree): Map<string, NodeResult> {
  const roots = new Map<string, NodeResult>();
  for (const id of tree.children.get(null) ?? []) {
    const result = tree.get(id);
    roots.set(result.node.phaseId, result);
  }
  return roots;
}
