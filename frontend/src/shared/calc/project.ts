/**
 * FE-002 · УП и итог проекта (SPEC 6.3, BR-CALC-05, BR-CALC-03). Зеркало `domain/calc/project.py`.
 *
 * Считается по суммам фаз и веток дисциплин из `CalcTree`, поэтому после `updateLeaf` пересчёт
 * итогов проекта стоит O(фазы × дисциплины), а не O(узлы).
 */
import { HUNDRED, ZERO, p80, p90, type Dec } from './decimal';
import type { ProjectInput } from './model';
import {
  CalcTree,
  EMPTY_TOTALS,
  addTotals,
  phaseRoots,
  sigmaOf,
  type Totals,
} from './tree';

export interface Figures {
  e: Dec;
  sigma: Dec;
  p80: Dec;
  p90: Dec;
}

export function figures(e: Dec, sigma: Dec): Figures {
  return { e, sigma, p80: p80(e, sigma), p90: p90(e, sigma) };
}

export function figuresOf(t: Totals): Figures {
  return figures(t.e, sigmaOf(t));
}

export interface PmResult extends Figures {
  baseE: Dec;
  baseSigma: Dec;
  /** Доля УП: 0,18 при 18%. */
  k: Dec;
  enabled: boolean;
}

export interface ProjectResult {
  input: ProjectInput;
  tree: CalcTree;
  /** Фазы работ (без сквозной фазы УП) в порядке входа. */
  phases: Map<string, Figures>;
  /** Свёртка дисциплины через все фазы работ. */
  disciplines: Map<string, Figures>;
  /** Фаза → дисциплина → значения. */
  disciplineByPhase: Map<string, Map<string, Figures>>;
  works: Figures;
  pm: PmResult;
  total: Figures;
  unaccountedLeaves: number;
  /** P80/E и P90/E; при E = 0 не вычисляются (BR-CALC-03). */
  p80Ratio: Dec | null;
  p90Ratio: Dec | null;
}

/** «3 листа без оценки не учтены» (BR-CALC-02). */
export function unaccountedText(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} лист без оценки не учтён`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} листа без оценки не учтены`;
  }
  return `${count} листов без оценки не учтены`;
}

export function unaccountedWarning(result: ProjectResult): string | null {
  return result.unaccountedLeaves > 0 ? unaccountedText(result.unaccountedLeaves) : null;
}

/** Итоги проекта по текущему состоянию дерева. */
export function summarize(tree: CalcTree): ProjectResult {
  const input = tree.input;
  const roots = phaseRoots(tree);
  const workPhases = input.phases.filter((p) => p.enabled && !p.isCrossCutting);
  const phases = new Map<string, Figures>();
  const disciplineByPhase = new Map<string, Map<string, Figures>>();
  const byDiscipline = new Map<string, Totals>(input.disciplines.map((d) => [d.id, EMPTY_TOTALS]));
  let works = EMPTY_TOTALS;
  let base = EMPTY_TOTALS;
  for (const phase of workPhases) {
    const root = roots.get(phase.id);
    const totals = root ? root.totals : EMPTY_TOTALS;
    phases.set(phase.id, figuresOf(totals));
    works = addTotals(works, totals);
    if (phase.inPmBase) base = addTotals(base, totals);
    const row = new Map<string, Totals>(input.disciplines.map((d) => [d.id, EMPTY_TOTALS]));
    for (const childId of root ? (tree.children.get(root.node.id) ?? []) : []) {
      const branch = tree.get(childId);
      const id = branch.node.disciplineId;
      const current = id === null ? undefined : row.get(id);
      if (branch.excluded || id === null || current === undefined) continue;
      row.set(id, addTotals(current, branch.totals));
      byDiscipline.set(id, addTotals(byDiscipline.get(id) ?? EMPTY_TOTALS, branch.totals));
    }
    disciplineByPhase.set(phase.id, new Map([...row].map(([d, t]) => [d, figuresOf(t)])));
  }
  let unaccounted = 0;
  for (const phase of input.phases) {
    const root = roots.get(phase.id);
    if (phase.enabled && root) unaccounted += root.totals.unaccounted;
  }
  const k = input.pmPercent.div(HUNDRED);
  const baseSigma = sigmaOf(base);
  const pmE = k.times(base.e);
  const pmSigma = k.times(baseSigma);
  const worksFigures = figuresOf(works);
  const total = figures(worksFigures.e.plus(pmE), worksFigures.sigma.plus(pmSigma));
  return {
    input,
    tree,
    phases,
    disciplines: new Map([...byDiscipline].map(([d, t]) => [d, figuresOf(t)])),
    disciplineByPhase,
    works: worksFigures,
    pm: { ...figures(pmE, pmSigma), baseE: base.e, baseSigma, k, enabled: k.gt(ZERO) },
    total,
    unaccountedLeaves: unaccounted,
    p80Ratio: total.e.isZero() ? null : total.p80.div(total.e),
    p90Ratio: total.e.isZero() ? null : total.p90.div(total.e),
  };
}

/** Полный расчёт часов проекта. */
export function calculate(input: ProjectInput): ProjectResult {
  return summarize(new CalcTree(input));
}
