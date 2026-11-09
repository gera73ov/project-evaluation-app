/**
 * FE-027 · правки структуры дерева в демо: созданные, перенесённые и удалённые узлы живут до
 * перезагрузки страницы. `GET /projects/{id}/tree` их не видит (данные демо не меняются);
 * ответы операций и PATCH — видят, поэтому дерево на экране остаётся согласованным.
 */
import {
  PEOPLE,
  PROJECTS,
  hours,
  typeId,
  userRef,
  type DemoProject,
} from "./data";
import { NOW, uuidFrom } from "./ids";
import { PERSONAS } from "./personas";

export type DemoNode = Record<string, unknown> & {
  id: string;
  parent_id: string | null;
  position: string;
  version: number;
};

/** Поля узлов демо, изменённые за сессию (в том числе PATCH). */
const edits = new Map<string, Record<string, unknown>>();
/** Узлы, созданные за сессию. */
const created = new Map<string, DemoNode>();
const deleted = new Set<string>();
let projectVersion = 1000;
let counter = 0;

/** Сбросить правки сессии (между тестами). */
export function resetDemoTree(): void {
  edits.clear();
  historyLog.clear();
  created.clear();
  deleted.clear();
}

export function nextProjectVersion(): number {
  projectVersion += 1;
  return projectVersion;
}

function base(p: DemoProject): DemoNode[] {
  return (p.nodes as DemoNode[]).map((n) => ({
    ...n,
    ...edits.get(String(n.id)),
  })) as DemoNode[];
}

/** Узлы проекта с правками сессии, без удалённых. */
export function demoNodes(p: DemoProject): DemoNode[] {
  const mine = [...created.values()].filter((n) => n.__project === p);
  return [...base(p), ...mine].filter((n) => !deleted.has(n.id));
}

export function demoNode(p: DemoProject, id: string): DemoNode | undefined {
  return demoNodes(p).find((n) => n.id === id);
}

/** Записать узел с новой версией; возвращает его без служебных полей. */
export function saveNode(
  p: DemoProject,
  node: DemoNode,
  fields: Record<string, unknown>,
): DemoNode {
  const next = {
    ...node,
    ...fields,
    version: Number(node.version ?? 1) + 1,
  } as DemoNode;
  if (created.has(node.id)) created.set(node.id, { ...next, __project: p });
  else
    edits.set(node.id, {
      ...edits.get(node.id),
      ...fields,
      version: next.version,
    });
  return clean(next);
}

function clean(node: DemoNode): DemoNode {
  return Object.fromEntries(
    Object.entries(node).filter(([k]) => k !== "__project"),
  ) as DemoNode;
}

function childrenOf(nodes: DemoNode[], parent: string | null): DemoNode[] {
  return nodes
    .filter((n) => n.parent_id === parent)
    .sort((a, b) => (a.position < b.position ? -1 : 1));
}

function subtree(nodes: DemoNode[], id: string): DemoNode[] {
  const out: DemoNode[] = [];
  const walk = (parent: string) => {
    for (const child of childrenOf(nodes, parent)) {
      out.push(child);
      walk(child.id);
    }
  };
  walk(id);
  return out;
}

/** Ключ порядка между соседями (как fractional indexing сервера, ARCH-04). */
function between(after: string | null, before: string | null): string {
  if (after === null) {
    if (before === null) return "0001";
    const last = before.charCodeAt(before.length - 1);
    return `${before.slice(0, -1)}${String.fromCharCode(last - 1)}m`;
  }
  let prefix = after;
  for (;;) {
    const candidate = `${prefix}m`;
    if (before === null || candidate < before) return candidate;
    prefix += "0";
  }
}

function positionAfter(
  nodes: DemoNode[],
  parent: string,
  afterId: string | null,
  skip?: string,
): string {
  const siblings = childrenOf(nodes, parent).filter((n) => n.id !== skip);
  const at = afterId ? siblings.findIndex((n) => n.id === afterId) : -1;
  const after = at >= 0 ? (siblings.at(at)?.position ?? null) : null;
  const before = siblings.at(at + 1)?.position ?? null;
  return between(after, before);
}

function newNode(
  p: DemoProject,
  parent: DemoNode,
  fields: Record<string, unknown>,
): DemoNode {
  counter += 1;
  const node = {
    id: uuidFrom("node", "demo", String(counter)),
    parent_id: parent.id,
    kind: "item",
    phase_id: parent.phase_id,
    discipline_id: parent.discipline_id,
    type_id: typeId("Работа"),
    title: "",
    position: "0001",
    o: null,
    r: null,
    p: null,
    multiplier: 1,
    comment_lines: [],
    reviewed_by: null,
    reviewed_at: null,
    self_review: false,
    version: 1,
    field_versions: {},
    e: null,
    sigma: null,
    p80: null,
    p90: null,
    sum_o: null,
    sum_r: null,
    sum_p: null,
    leaf_state: "empty",
    is_large: false,
    is_repeating: false,
    unaccounted_leaves: 0,
    messages_count: 0,
    open_questions: 0,
    questions_to_me: 0,
    ...fields,
  } as DemoNode;
  created.set(node.id, { ...node, __project: p });
  return node;
}

const mutation = (nodes: DemoNode[], deletedIds: string[] = []) => ({
  nodes,
  deleted_ids: deletedIds,
  project_version: nextProjectVersion(),
  totals: { e: hours(0), sigma: hours(0), p80: hours(0), p90: hours(0) },
  branch_statuses: [],
  batch_id: null,
});

type Body = Record<string, unknown>;

export function createNode(p: DemoProject, body: Body) {
  const nodes = demoNodes(p);
  const parent = nodes.find((n) => n.id === body.parent_id);
  if (!parent) return undefined;
  const afterId = typeof body.after_id === "string" ? body.after_id : null;
  const node = newNode(p, parent, {
    title: String(body.title ?? ""),
    position: positionAfter(nodes, parent.id, afterId),
    ...(typeof body.type_id === "string" ? { type_id: body.type_id } : {}),
  });
  return {
    node,
    project_version: nextProjectVersion(),
    ancestors: [],
    totals: { e: hours(0), sigma: hours(0), p80: hours(0), p90: hours(0) },
    branch_status: null,
    rounded: [],
  };
}

/** «Разбить лист» (BR-TREE-02): оценка переходит в лист «… — часть 1». */
export function splitNode(p: DemoProject, id: string) {
  const node = demoNode(p, id);
  if (!node) return undefined;
  const suffix = " — часть 1";
  const title = `${String(node.title).slice(0, 200 - suffix.length)}${suffix}`;
  const child = newNode(p, node, {
    title,
    type_id: node.type_id,
    o: node.o,
    r: node.r,
    p: node.p,
    multiplier: node.multiplier,
    leaf_state: node.o === null ? "empty" : "valid",
  });
  const parent = saveNode(p, node, {
    o: null,
    r: null,
    p: null,
    multiplier: 1,
    leaf_state: null,
  });
  return mutation([parent, child]);
}

/** Сумма O/R/P листьев поддерева с учётом ×N (BR-TREE-03). */
export function collapseSuggestion(p: DemoProject, id: string) {
  const nodes = demoNodes(p);
  const sum = { o: 0, r: 0, p: 0 };
  for (const n of subtree(nodes, id)) {
    if (childrenOf(nodes, n.id).length) continue;
    const times = Number(n.multiplier ?? 1);
    sum.o += Number(n.o ?? 0) * times;
    sum.r += Number(n.r ?? 0) * times;
    sum.p += Number(n.p ?? 0) * times;
  }
  return {
    o: hours(String(sum.o)),
    r: hours(String(sum.r)),
    p: hours(String(sum.p)),
    multiplier: 1,
  };
}

export function collapseNode(p: DemoProject, id: string, body: Body) {
  const nodes = demoNodes(p);
  const node = nodes.find((n) => n.id === id);
  if (!node) return undefined;
  const gone = subtree(nodes, id).map((n) => n.id);
  for (const g of gone) deleted.add(g);
  const s = collapseSuggestion(p, id);
  const leaf = saveNode(p, node, {
    o: body.o ?? s.o,
    r: body.r ?? s.r,
    p: body.p ?? s.p,
    multiplier: 1,
    leaf_state: "valid",
  });
  return mutation([leaf], gone);
}

export function moveNode(p: DemoProject, id: string, body: Body) {
  const nodes = demoNodes(p);
  const node = nodes.find((n) => n.id === id);
  const parent = nodes.find((n) => n.id === body.new_parent_id);
  if (!node || !parent) return undefined;
  const afterId = typeof body.after_id === "string" ? body.after_id : null;
  const branch = {
    phase_id: parent.phase_id,
    discipline_id: parent.discipline_id,
  };
  const moved = saveNode(p, node, {
    ...branch,
    parent_id: parent.id,
    position: positionAfter(nodes, parent.id, afterId, id),
  });
  const inner =
    node.discipline_id === parent.discipline_id &&
    node.phase_id === parent.phase_id
      ? []
      : subtree(nodes, id).map((n) => saveNode(p, n, branch));
  return mutation([moved, ...inner]);
}

/** Копия поддерева `source` детьми `target` (или соседом после `afterId`). */
function copyTree(
  p: DemoProject,
  from: DemoNode[],
  source: DemoNode,
  parent: DemoNode,
  position: string,
): DemoNode[] {
  const copy = newNode(p, parent, {
    ...Object.fromEntries(
      Object.entries(source).filter(
        ([k]) =>
          ![
            "id",
            "parent_id",
            "phase_id",
            "discipline_id",
            "version",
            "__project",
          ].includes(k),
      ),
    ),
    position,
    reviewed_by: null,
    reviewed_at: null,
    self_review: false,
    messages_count: 0,
    open_questions: 0,
    questions_to_me: 0,
  });
  return [
    copy,
    ...childrenOf(from, source.id).flatMap((child) =>
      copyTree(p, from, child, copy, child.position),
    ),
  ];
}

export function duplicateNode(p: DemoProject, id: string) {
  const nodes = demoNodes(p);
  const node = nodes.find((n) => n.id === id);
  const parent = nodes.find((n) => n.id === node?.parent_id);
  if (!node || !parent) return undefined;
  return mutation(
    copyTree(p, nodes, node, parent, positionAfter(nodes, parent.id, id)),
  );
}

export function deleteNode(p: DemoProject, id: string) {
  const nodes = demoNodes(p);
  if (!nodes.some((n) => n.id === id)) return undefined;
  const gone = [id, ...subtree(nodes, id).map((n) => n.id)];
  for (const g of gone) deleted.add(g);
  return mutation([], gone);
}

/** «Скопировать ветку из проекта…» (FR-PRJ-03): дети источника — детьми выбранной строки. */
export function copyBranchFrom(p: DemoProject, id: string, body: Body) {
  const target = demoNode(p, id);
  const source = Object.values(PROJECTS)
    .map((sp) => ({ sp, n: demoNode(sp, String(body.source_node_id)) }))
    .find((x) => x.n);
  if (!target || !source?.n) return undefined;
  const from = demoNodes(source.sp);
  const roots =
    source.n.kind === "discipline" ? childrenOf(from, source.n.id) : [source.n];
  const nodes = demoNodes(p);
  let after = childrenOf(nodes, id).at(-1)?.position ?? null;
  const out: DemoNode[] = [];
  for (const root of roots) {
    const position = between(after, null);
    out.push(...copyTree(p, from, root, target, position));
    after = position;
  }
  return mutation(out);
}

// --- FE-028: история листа ---------------------------------------------------------------

type HistoryEntry = {
  id: string;
  created_at: string;
  user: ReturnType<typeof userRef> | null;
  action: string;
  changes: Record<string, [unknown, unknown]>;
  node_version: number;
  project_version: number;
};

/** Правки сессии по узлу, от старых к новым. */
const historyLog = new Map<string, HistoryEntry[]>();

/** Записать правку узла в историю демо. */
export function recordHistory(
  nodeId: string,
  user: ReturnType<typeof userRef>,
  changes: Record<string, [unknown, unknown]>,
  nodeVersion: number,
  version: number,
): void {
  const list = historyLog.get(nodeId) ?? [];
  list.push({
    id: uuidFrom("history", nodeId, String(list.length)),
    created_at: new Date(Date.parse(NOW) + (list.length + 1) * 60_000)
      .toISOString()
      .replace(".000Z", "Z"),
    user,
    action: "update",
    changes,
    node_version: nodeVersion,
    project_version: version,
  });
  historyLog.set(nodeId, list);
}

const at = (iso: string) => iso;

/**
 * История узла: начальные записи демо (у «Обмен с 1С» — как на макете tree-menu.png) и правки
 * сессии; от новых к старым.
 */
export function nodeHistory(p: DemoProject, id: string) {
  const node = demoNode(p, id);
  if (!node) return undefined;
  const original =
    (p.nodes as DemoNode[]).find((n) => n.id === id) ?? created.get(id);
  const ivanov = userRef(PERSONAS.expert);
  const smirnova = userRef(PERSONAS.moderator);
  const novikov = userRef(PEOPLE.novikov);
  const entry = (
    key: string,
    created_at: string,
    user: HistoryEntry["user"],
    action: string,
    changes: HistoryEntry["changes"],
    version: number,
  ): HistoryEntry => ({
    id: uuidFrom("history", id, key),
    created_at,
    user,
    action,
    changes,
    node_version: version,
    project_version: 10 + version,
  });
  const fork = (o: unknown, r: unknown, p2: unknown) => ({ o, r, p: p2 });
  const pairs = (
    a: ReturnType<typeof fork>,
    b: ReturnType<typeof fork>,
  ): HistoryEntry["changes"] => ({
    o: [a.o, b.o],
    r: [a.r, b.r],
    p: [a.p, b.p],
  });
  let initial: HistoryEntry[];
  if (original?.title === "Обмен с 1С") {
    const f1 = fork("24", "32", "48");
    const f2 = fork("30", "40", "60");
    const f3 = fork(original.o, original.r, original.p);
    initial = [
      entry(
        "create",
        at("2026-10-30T12:44:00Z"),
        novikov,
        "create",
        pairs(fork(null, null, null), f1),
        1,
      ),
      entry(
        "comment",
        at("2026-10-31T07:02:00Z"),
        novikov,
        "update",
        {
          comment_lines: [
            [],
            [{ tag_id: null, text: "Обмен по расписанию, раз в час" }],
          ],
        },
        2,
      ),
      entry(
        "smirnova",
        at("2026-10-31T15:20:00Z"),
        smirnova,
        "update",
        pairs(f1, f2),
        3,
      ),
      entry(
        "ivanov",
        at("2026-11-01T08:07:00Z"),
        ivanov,
        "update",
        pairs(f2, f3),
        4,
      ),
    ];
  } else if (original) {
    const f = fork(original.o ?? null, original.r ?? null, original.p ?? null);
    const author = created.has(id) ? ivanov : novikov;
    initial = [
      entry(
        "create",
        created.has(id) ? NOW : at("2026-10-30T12:44:00Z"),
        author,
        "create",
        pairs(fork(null, null, null), f),
        1,
      ),
    ];
  } else initial = [];
  return {
    items: [...initial, ...(historyLog.get(id) ?? [])].reverse(),
    next_cursor: null,
  };
}
