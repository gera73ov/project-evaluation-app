/**
 * FE-040 · сетка готовности «фаза × дисциплина» (SPEC 11.8, 10.1): данные `GET /projects/{id}/stats`
 * (`readiness`, `money.cost_by_discipline`) плюс из дерева — кто правил ветку последним, открытые
 * вопросы и неучтённые листья (`branch_statuses`, узлы `kind = discipline`).
 */
import type { components } from '../../../shared/api/client';

type Stats = components['schemas']['Stats'];
type Project = components['schemas']['Project'];
type Tree = components['schemas']['Tree'];
export type Readiness = Stats['readiness'][number];
export type BranchStatusValue = Readiness['status'];

export interface Cell {
  phaseId: string;
  disciplineId: string;
  /** Узел ветки — для перехода на рабочий экран `?node=`. */
  nodeId: string | null;
  status: BranchStatusValue;
  e: string | null;
  who: string | null;
  at: string | null;
  large: boolean;
  wideFork: boolean;
  questions: number;
  unaccounted: number;
  noExpert: boolean;
  overdueDays: number | null;
}

export interface Grid {
  phases: { id: string; name: string }[];
  disciplines: { id: string; name: string; hasExpert: boolean }[];
  cells: Map<string, Cell>;
}

export const cellKey = (phaseId: string, disciplineId: string) => `${phaseId}/${disciplineId}`;

/** Сетка: включённые фазы проекта с ветками × его дисциплины. */
export function buildGrid(project: Project, stats: Stats, tree: Tree | undefined): Grid {
  // фазы с ветками дисциплин; «Управление проектом» считается процентом и веток не имеет
  const withBranches = new Set([
    ...stats.readiness.map((r) => r.phase_id),
    ...(tree?.branch_statuses ?? []).map((b) => b.phase_id),
  ]);
  const phases = project.phases
    .filter((p) => p.is_enabled && withBranches.has(p.phase_id))
    .map((p) => ({ id: p.phase_id, name: p.name }));
  const disciplines = project.disciplines.map((d) => ({
    id: d.discipline_id,
    name: d.name,
    hasExpert: d.has_expert,
  }));
  const readiness = new Map(stats.readiness.map((r) => [cellKey(r.phase_id, r.discipline_id), r]));
  const branches = new Map((tree?.branch_statuses ?? []).map((b) => [cellKey(b.phase_id, b.discipline_id), b]));
  const nodes = new Map(
    (tree?.nodes ?? [])
      .filter((n) => n.kind === 'discipline' && n.phase_id && n.discipline_id)
      .map((n) => [cellKey(n.phase_id ?? '', n.discipline_id ?? ''), n]),
  );
  const cells = new Map<string, Cell>();
  for (const phase of phases)
    for (const disc of disciplines) {
      const key = cellKey(phase.id, disc.id);
      const r = readiness.get(key);
      const b = branches.get(key);
      const flags = new Set(r?.flags ?? []);
      cells.set(key, {
        phaseId: phase.id,
        disciplineId: disc.id,
        nodeId: nodes.get(key)?.id ?? null,
        // ветки нет — дисциплина в фазе не участвует, как «не нужно»
        status: r?.status ?? b?.status ?? 'not_needed',
        e: r?.e ?? null,
        who: b?.changed_by?.full_name ?? null,
        at: r?.last_change_at ?? b?.changed_at ?? null,
        large: flags.has('large'),
        wideFork: flags.has('wide_fork'),
        questions: b?.open_questions ?? (flags.has('open_question') ? 1 : 0),
        unaccounted: nodes.get(key)?.unaccounted_leaves ?? 0,
        noExpert: flags.has('no_expert') || (!disc.hasExpert && (r?.status ?? 'not_started') === 'not_started'),
        overdueDays: flags.has('overdue') ? (r?.overdue_working_days ?? null) : null,
      });
    }
  return { phases, disciplines, cells };
}

/** «Напомнить не начавшим»: есть ли ветки «не начато» с экспертом; кому некому напомнить. */
export function remindState(grid: Grid): { canRemind: boolean; withoutExpert: string[] } {
  let canRemind = false;
  const without = new Set<string>();
  for (const cell of grid.cells.values()) {
    if (cell.status !== 'not_started') continue;
    if (cell.noExpert) {
      const name = grid.disciplines.find((d) => d.id === cell.disciplineId)?.name;
      if (name) without.add(name);
    } else canRemind = true;
  }
  return { canRemind, withoutExpert: [...without] };
}

/** Правый край шкалы соотношения, %: верхняя граница нормы с запасом, кратно 10, не меньше 50 (норма 25–35 → 50). */
export function ratioScale(maxPct: number): number {
  return Math.max(50, Math.ceil((maxPct * 1.4) / 10) * 10);
}
