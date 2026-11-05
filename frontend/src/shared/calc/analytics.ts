/**
 * FE-002 · доли, контрольные соотношения, объёмы, кандидаты на декомпозицию (SPEC 6.6,
 * BR-TREE-09, C-27, 10.1, 11.10). Зеркало `domain/calc/analytics.py`.
 */
import { D, HUNDRED, ZERO, type Dec } from './decimal';
import type { LeafEstimate } from './leaf';
import type { CalcNode, DetailLevel } from './model';
import type { ProjectResult } from './project';

export const WORK_TYPE = 'Работа';
export const WIDE_FORK_RATIO = new D('0.3');
export const TOP_N = 10;
export const DEFAULT_LARGE_LEAF_HOURS: ReadonlyMap<DetailLevel, Dec | null> = new Map([
  ['coarse', null],
  ['medium', new D(80)],
  ['detailed', new D(40)],
]);

export type Verdict = 'below' | 'within' | 'above';

function pct(part: Dec, whole: Dec): Dec | null {
  return whole.isZero() ? null : part.div(whole).times(HUNDRED);
}

export interface Shares {
  /** Доля дисциплины в часах работ; `null` — «—». */
  disciplines: Map<string, Dec | null>;
  byPhase: Map<string, Map<string, Dec | null>>;
  /** Доля фазы в итоге проекта. */
  phases: Map<string, Dec | null>;
}

export function shares(project: ProjectResult): Shares {
  const worksE = project.works.e;
  const byPhase = new Map<string, Map<string, Dec | null>>();
  for (const [phase, row] of project.disciplineByPhase) {
    const phaseE = project.phases.get(phase)?.e ?? ZERO;
    byPhase.set(phase, new Map([...row].map(([d, f]) => [d, pct(f.e, phaseE)])));
  }
  return {
    disciplines: new Map([...project.disciplines].map(([d, f]) => [d, pct(f.e, worksE)])),
    byPhase,
    phases: new Map([...project.phases].map(([p, f]) => [p, pct(f.e, project.total.e)])),
  };
}

export interface ControlRatio {
  disciplineA: string;
  disciplinesB: string[];
  minPct: Dec;
  maxPct: Dec;
  pct: Dec | null;
  verdict: Verdict | null;
}

/** «A к ΣB» (6.6): границы диапазона входят в норму. */
export function controlRatio(
  project: ProjectResult,
  disciplineA: string,
  disciplinesB: string[],
  minPct: Dec,
  maxPct: Dec,
): ControlRatio {
  const a = project.disciplines.get(disciplineA)?.e ?? ZERO;
  let b = ZERO;
  for (const id of disciplinesB) b = b.plus(project.disciplines.get(id)?.e ?? ZERO);
  const value = pct(a, b);
  let verdict: Verdict | null = null;
  if (value !== null) verdict = value.lt(minPct) ? 'below' : value.gt(maxPct) ? 'above' : 'within';
  return { disciplineA, disciplinesB, minPct, maxPct, pct: value, verdict };
}

/** Объёмы по типам с учётом ×N; узлы-группы не считаются (10.1). */
export function volumes(project: ProjectResult): Map<string, number> {
  const result = new Map<string, number>();
  for (const leaf of project.tree.leaves()) {
    const type = leaf.node.type ?? WORK_TYPE;
    result.set(type, (result.get(type) ?? 0) + leaf.node.multiplier);
  }
  return result;
}

/** «Экран — 13, Функция — 2» (11.10 №2). */
export function volumesText(byType: ReadonlyMap<string, number>): string {
  return [...byType].map(([name, count]) => `${name} — ${count}`).join(', ');
}

export function largeLeafThreshold(
  level: DetailLevel,
  thresholds: ReadonlyMap<DetailLevel, Dec | null> = DEFAULT_LARGE_LEAF_HOURS,
): Dec | null {
  return thresholds.get(level) ?? null;
}

export interface Candidate {
  nodeId: string;
  eUnit: Dec;
  e: Dec;
  sigmaRatio: Dec | null;
  large: boolean;
  repeating: boolean;
  wideFork: boolean;
}

export function candidate(node: CalcNode, leaf: LeafEstimate, threshold: Dec | null): Candidate {
  const ratio = leaf.e.isZero() ? null : leaf.sigma.div(leaf.e);
  const large = threshold !== null && leaf.eUnit.gt(threshold);
  const repeating = threshold !== null && !large && node.multiplier > 1 && leaf.e.gt(threshold);
  return {
    nodeId: node.id,
    eUnit: leaf.eUnit,
    e: leaf.e,
    sigmaRatio: ratio,
    large,
    repeating,
    wideFork: ratio !== null && ratio.gt(WIDE_FORK_RATIO),
  };
}

export interface Decomposition {
  thresholdHours: Dec | null;
  large: string[];
  repeating: string[];
  wideForks: string[];
  topByE: Candidate[];
  topBySigmaRatio: Candidate[];
}

/** «Кандидаты на декомпозицию» и флажки ◆ / ↔ (BR-TREE-09, C-27, 11.10 №3). */
export function decomposition(
  project: ProjectResult,
  thresholds?: ReadonlyMap<DetailLevel, Dec | null>,
): Decomposition {
  const threshold = largeLeafThreshold(project.input.detailLevel, thresholds);
  const candidates: Candidate[] = [];
  for (const leaf of project.tree.leaves()) {
    if (leaf.leaf && (leaf.leaf.state === 'valid' || leaf.leaf.state === 'zero')) {
      candidates.push(candidate(leaf.node, leaf.leaf, threshold));
    }
  }
  const byRatio = candidates.filter((c) => c.sigmaRatio !== null);
  return {
    thresholdHours: threshold,
    large: candidates.filter((c) => c.large).map((c) => c.nodeId),
    repeating: candidates.filter((c) => c.repeating).map((c) => c.nodeId),
    wideForks: candidates.filter((c) => c.wideFork).map((c) => c.nodeId),
    topByE: [...candidates].sort((a, b) => b.e.comparedTo(a.e)).slice(0, TOP_N),
    topBySigmaRatio: [...byRatio]
      .sort((a, b) => (b.sigmaRatio ?? ZERO).comparedTo(a.sigmaRatio ?? ZERO))
      .slice(0, TOP_N),
  };
}
