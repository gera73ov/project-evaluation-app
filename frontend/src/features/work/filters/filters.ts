/**
 * FE-024 · поиск и чипы-фильтры дерева (FR-TREE-12, 11.4 №5–6, FR-REV-04; DESIGN.md 9.3).
 *
 * Фильтры отбирают узлы-работы; видимыми остаются найденные узлы вместе с родителями (фаза,
 * ветка дисциплины, промежуточные узлы). Включённые фильтры и поиск складываются по «И». Итоги
 * в верхней полосе считаются по всему дереву и от фильтров не зависят.
 */
import { candidate, type CalcTree, type Dec, type NodeResult } from '../../../shared/calc';
import type { TreeNode } from '../store/treeStore';

export type FilterKey = 'mine' | 'unestimated' | 'large' | 'unreviewed' | 'questions' | 'selfReview' | 'risk';

/** Чипы в порядке полосы инструментов; «Риски» включается из верхней полосы. */
export const CHIPS: readonly FilterKey[] = ['mine', 'unestimated', 'large', 'unreviewed', 'questions', 'selfReview'];
export const FILTER_KEYS: readonly FilterKey[] = [...CHIPS, 'risk'];

/** Поиск начинается с 2 символов (FR-TREE-12). */
export const SEARCH_MIN = 2;

export interface FilterInput {
  /** Дисциплины «моих веток»; null — все (модератор без экспертной роли). */
  myDisciplines: ReadonlySet<string> | null;
  largeThreshold: Dec | null;
  riskTags: ReadonlySet<string>;
}

interface CommentLine {
  tag_id: string | null;
  text: string;
}

function extraOf(node: TreeNode | undefined): Map<string, unknown> {
  return new Map(Object.entries(node?.extra ?? {}));
}

function commentLines(node: TreeNode | undefined): CommentLine[] {
  return (extraOf(node).get('comment_lines') as CommentLine[] | null | undefined) ?? [];
}

/** Узел подходит под один фильтр. Фильтры по оценке смотрят только на листья. */
export function matchesFilter(
  key: FilterKey,
  result: NodeResult,
  node: TreeNode | undefined,
  input: FilterInput,
): boolean {
  if (result.node.kind !== 'item') return false;
  const leaf = result.isLeaf ? result.leaf : null;
  const extra = extraOf(node);
  switch (key) {
    case 'mine':
      return (
        input.myDisciplines === null ||
        (result.node.disciplineId !== null && input.myDisciplines.has(result.node.disciplineId))
      );
    case 'unestimated':
      return leaf !== null && (leaf.state === 'empty' || leaf.state === 'invalid');
    case 'large':
      return leaf !== null && input.largeThreshold !== null && candidate(result.node, leaf, input.largeThreshold).large;
    case 'unreviewed':
      return leaf !== null && !extra.get('reviewed_by');
    case 'selfReview':
      return leaf !== null && Boolean(extra.get('reviewed_by')) && extra.get('self_review') === true;
    case 'questions':
      return Number(extra.get('open_questions') ?? 0) > 0;
    case 'risk':
      return commentLines(node).some((l) => l.tag_id !== null && input.riskTags.has(l.tag_id));
  }
}

/** Совпадение поиска в названии или в тексте строк комментария, без учёта регистра. */
export function matchesSearch(result: NodeResult, node: TreeNode | undefined, query: string): boolean {
  if (result.node.kind !== 'item') return false;
  const q = query.toLocaleLowerCase('ru');
  if (result.node.title.toLocaleLowerCase('ru').includes(q)) return true;
  return commentLines(node).some((l) => l.text.toLocaleLowerCase('ru').includes(q));
}

export function searchActive(query: string): boolean {
  return query.trim().length >= SEARCH_MIN;
}

/**
 * Видимые узлы: найденные и все их предки. null — фильтров и поиска нет, дерево показывается
 * целиком (с учётом свёртки).
 */
export function visibleNodes(
  calc: CalcTree,
  nodes: ReadonlyMap<string, TreeNode>,
  active: ReadonlySet<FilterKey>,
  query: string,
  input: FilterInput,
): Set<string> | null {
  const q = query.trim();
  const searching = searchActive(q);
  if (!active.size && !searching) return null;
  const visible = new Set<string>();
  const show = (from: string) => {
    for (let id: string | null = from; id !== null && !visible.has(id); ) {
      visible.add(id);
      id = calc.nodes.get(id)?.node.parentId ?? null;
    }
  };
  // только «Мои ветки»: свои ветки видны и пустыми — в новом проекте эксперту есть куда нажать «+»
  const onlyMine = !searching && active.size === 1 && active.has('mine');
  for (const result of calc.nodes.values()) {
    const node = nodes.get(result.node.id);
    const { kind, disciplineId } = result.node;
    if (
      onlyMine &&
      kind === 'discipline' &&
      (input.myDisciplines === null || (disciplineId !== null && input.myDisciplines.has(disciplineId)))
    ) {
      show(result.node.id);
      continue;
    }
    if (searching && !matchesSearch(result, node, q)) continue;
    if ([...active].some((key) => !matchesFilter(key, result, node, input))) continue;
    show(result.node.id);
  }
  return visible;
}

/** Число строк под каждым чипом отдельно (11.4 №5). */
export function chipCounts(
  calc: CalcTree,
  nodes: ReadonlyMap<string, TreeNode>,
  input: FilterInput,
): Map<FilterKey, number> {
  const counts = new Map<FilterKey, number>(FILTER_KEYS.map((key) => [key, 0]));
  for (const result of calc.nodes.values()) {
    const node = nodes.get(result.node.id);
    for (const key of FILTER_KEYS) {
      if (matchesFilter(key, result, node, input)) counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

/** Неучтённые листья по видам: пустые и неверные (11.4 №6). */
export function unaccountedLeaves(calc: CalcTree): { empty: number; invalid: number } {
  let empty = 0;
  let invalid = 0;
  for (const result of calc.leaves()) {
    if (result.leaf?.state === 'empty') empty += 1;
    else if (result.leaf?.state === 'invalid') invalid += 1;
  }
  return { empty, invalid };
}

/** «До фаз» и «до дисциплин»: какие узлы свернуть. */
export function collapseTo(calc: CalcTree, level: 'phases' | 'disciplines'): Set<string> {
  const out = new Set<string>();
  for (const result of calc.nodes.values()) {
    const kind = result.node.kind;
    if (level === 'phases' ? kind === 'phase' : kind === 'discipline') out.add(result.node.id);
  }
  return out;
}
