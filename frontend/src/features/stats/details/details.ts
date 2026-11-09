/**
 * FE-042 · правила вкладок «Доли и соотношения», «Объёмы по типам», «Кандидаты на декомпозицию»,
 * «Допущения и риски» (SPEC 11.10 №1–4, 6.6, BR-TREE-09, R-03). Доли с фильтром по фазе и E по
 * типам считаются по дереву; число единиц типа — из статистики (`volumes`, с учётом ×N).
 */
import type { components } from '../../../shared/api/client';
import { D, type Dec } from '../../../shared/calc/decimal';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];
type Node = components['schemas']['Node'];

const roundPct = (part: Dec, whole: Dec) => (whole.isZero() ? 0 : Math.round(part.div(whole).times(100).toNumber()));

export interface Share {
  id: string;
  name: string;
  e: string;
  pct: number;
}

/**
 * Доли дисциплин в часах работ (11.10 №1): E узлов-дисциплин, все фазы или одна; доли округлены
 * до целого (6.6), дисциплины без часов не показываются.
 */
export function shares(project: Project, nodes: readonly Node[], phaseId: string | null): Share[] {
  const byDisc = new Map<string, Dec>();
  for (const n of nodes) {
    if (n.kind !== 'discipline' || !n.discipline_id || n.e === null) continue;
    if (phaseId !== null && n.phase_id !== phaseId) continue;
    byDisc.set(n.discipline_id, (byDisc.get(n.discipline_id) ?? new D(0)).plus(n.e));
  }
  const works = [...byDisc.values()].reduce((a, b) => a.plus(b), new D(0));
  return project.disciplines
    .filter((d) => byDisc.has(d.discipline_id) && !(byDisc.get(d.discipline_id) ?? new D(0)).isZero())
    .map((d) => {
      const e = byDisc.get(d.discipline_id) ?? new D(0);
      return { id: d.discipline_id, name: d.name, e: e.toFixed(), pct: roundPct(e, works) };
    });
}

/** Листья дерева: узлы-позиции без детей (узлы-группы не считаются). */
export function leavesOf(nodes: readonly Node[]): Node[] {
  const parents = new Set(nodes.map((n) => n.parent_id));
  return nodes.filter((n) => n.kind === 'item' && !parents.has(n.id));
}

export interface VolumeRow {
  typeId: string;
  name: string;
  count: number;
  e: string;
  /** E на единицу; у «Работы» не показывается */
  eUnit: string | null;
  disciplines: string[];
  isWork: boolean;
}

/** Объёмы по типам (11.10 №2): единицы — из статистики, E и дисциплины — по листьям дерева. */
export function volumeRows(
  stats: Stats,
  nodes: readonly Node[],
  project: Project,
  isWork: (typeId: string, name: string) => boolean,
): VolumeRow[] {
  const discNames = new Map(project.disciplines.map((d) => [d.discipline_id, d.name]));
  const leaves = leavesOf(nodes);
  return stats.volumes
    .map((v) => {
      const own = leaves.filter((n) => n.type_id === v.type_id);
      const e = own.reduce((acc, n) => acc.plus(n.e ?? '0'), new D(0));
      const work = isWork(v.type_id, v.name);
      const discs = [...new Set(own.map((n) => n.discipline_id).filter((id): id is string => id !== null))];
      return {
        typeId: v.type_id,
        name: v.name,
        count: v.count,
        e: e.toFixed(),
        eUnit: work || v.count === 0 ? null : e.div(v.count).toFixed(),
        disciplines: discs.map((id) => discNames.get(id) ?? '?'),
        isWork: work,
      };
    })
    .sort((a, b) => Number(b.e) - Number(a.e));
}

/** Строка-сводка для КП: «Экран — 13, Функция — 2…» без «Работы». */
export function volumeSummary(rows: readonly VolumeRow[]): string {
  return rows
    .filter((r) => !r.isWork)
    .map((r) => `${r.name} — ${r.count}`)
    .join(', ');
}

export interface CandidateRow {
  nodeId: string;
  title: string;
  path: string;
  e: string;
  eUnit: string;
  multiplier: number;
  mark: 'above' | 'repeating' | null;
  fork: { o: string; r: string; p: string } | null;
}

/** Путь узла без его названия: «Разработка › Бэкенд». */
export function pathOf(nodeId: string, byId: ReadonlyMap<string, Node>): string[] {
  const out: string[] = [];
  let cur = byId.get(nodeId);
  cur = cur?.parent_id ? byId.get(cur.parent_id) : undefined;
  while (cur) {
    out.unshift(cur.title);
    cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
  }
  return out;
}

/**
 * Крупные листья (11.10 №3, BR-TREE-09): порог сравнивается с E одной штуки; «повторяющийся» —
 * ×N > 1 и E за штуку не выше порога. Без порога (уровень «Крупно») пометок нет.
 */
export function largeRows(stats: Stats, nodes: readonly Node[], threshold: Dec | null): CandidateRow[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return stats.candidates.large.flatMap((c) => {
    const n = byId.get(c.node_id);
    if (!n) return [];
    const above = threshold !== null && new D(c.e_unit).greaterThan(threshold);
    return [
      {
        nodeId: c.node_id,
        title: n.title,
        path: pathOf(c.node_id, byId).join(' › '),
        e: c.e,
        eUnit: c.e_unit,
        multiplier: n.multiplier,
        mark: above ? 'above' : c.repeating ? 'repeating' : null,
        fork: null,
      },
    ];
  });
}

/** Широкие вилки (11.10 №3): топ по σ/E; вилка O–R–P листа для подписи. */
export function wideRows(stats: Stats, nodes: readonly Node[]): (CandidateRow & { ratio: string })[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return stats.candidates.wide_fork.flatMap((c) => {
    const n = byId.get(c.node_id);
    if (!n) return [];
    return [
      {
        nodeId: c.node_id,
        title: n.title,
        path: pathOf(c.node_id, byId).join(' › '),
        e: n.e ?? '0',
        eUnit: n.e ?? '0',
        multiplier: n.multiplier,
        mark: null,
        fork: n.o !== null && n.r !== null && n.p !== null ? { o: n.o, r: n.r, p: n.p } : null,
        ratio: c.ratio_pct,
      },
    ];
  });
}

export type TagCategory = Stats['tag_lists'][number]['category'];
export const TAG_ORDER: readonly TagCategory[] = ['assumption', 'constraint', 'risk', 'tech'];

export interface TagLine {
  key: string;
  category: TagCategory;
  text: string;
  path: string;
  nodeId: string | null;
}

/**
 * Черновик раздела КП (11.10 №4): строки по меткам в порядке «Допущение», «Огр.», «Риск», «Тех.»;
 * обоснование процента УП — допущением «из настроек проекта».
 */
export function tagLines(stats: Stats, pm: { pct: string; reason: string } | null, settingsPath: string): TagLine[] {
  const lists = new Map(stats.tag_lists.map((l) => [l.category, l.items]));
  const out: TagLine[] = [];
  for (const category of TAG_ORDER) {
    for (const item of lists.get(category) ?? [])
      out.push({
        key: `${item.node_id}/${item.tag_id}/${out.length}`,
        category,
        text: item.text,
        path: item.path.join(' › '),
        nodeId: item.node_id,
      });
    if (category === 'assumption' && pm && pm.reason.trim())
      out.push({ key: 'pm', category, text: `УП ${pm.pct}%: ${pm.reason}`, path: settingsPath, nodeId: null });
  }
  return out;
}
